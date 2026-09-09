"""
Coverage for the AI spend-limiting logic in app/ai.py (enforce_usage_limits,
get_usage_status, _row_cost_usd): the guard that turns a runaway loop or a shared-key
abuse case into a 429 instead of an open-ended Gemini bill.

No database and no network: get_monthly_budget_usd/get_monthly_cost_usd/get_app_setting
are the only things here that touch Postgres, and every test replaces them, in line with
the rest of this suite, which runs against the shared staging database and must never
write to it.
"""
import pytest

from app import ai


def test_row_cost_usd_known_model():
    pricing = {"gemini-3.6-flash": (1.50, 7.50)}
    # 1000 prompt tokens + 1000 completion tokens, priced per 1M tokens.
    cost = ai._row_cost_usd(pricing, "gemini-3.6-flash", 1000, 1000)
    assert cost == pytest.approx((1000 * 1.50 + 1000 * 7.50) / 1_000_000)


def test_row_cost_usd_unknown_model_uses_fallback_pricing():
    pricing = {"gemini-3.6-flash": (1.50, 7.50)}
    cost = ai._row_cost_usd(pricing, "some-future-model", 1_000_000, 0)
    in_price, _ = ai._FALLBACK_DEFAULT_PRICING
    assert cost == pytest.approx(in_price)


def test_row_cost_usd_zero_tokens_is_free():
    assert ai._row_cost_usd({}, "anything", 0, 0) == 0.0


@pytest.fixture
def usage(monkeypatch):
    """Lets a test fix the budget/spend/warning-threshold inputs to get_usage_status and
    enforce_usage_limits without touching the database."""
    state = {"budget": 10.0, "spent": 0.0, "warning_pct": 10, "recent_calls": 0, "max_calls": 40}
    monkeypatch.setattr(ai, "get_monthly_budget_usd", lambda username: state["budget"])
    monkeypatch.setattr(ai, "get_monthly_cost_usd", lambda username: state["spent"])
    monkeypatch.setattr(ai, "get_recent_call_count", lambda username, minutes=None: state["recent_calls"])
    monkeypatch.setattr(
        ai, "_get_app_setting_float",
        lambda key, default: state["warning_pct"] if key == "ai_warning_remaining_pct" else default,
    )
    monkeypatch.setattr(
        ai, "_get_app_setting_int",
        lambda key, default: state["max_calls"] if key == "ai_rate_limit_max_calls" else default,
    )
    monkeypatch.setattr(ai, "IS_CLOUD", True)
    return state


def test_usage_status_under_budget_no_warning(usage):
    usage["budget"], usage["spent"] = 10.0, 1.0
    status = ai.get_usage_status("someone")
    assert status["percent_used"] == 10.0
    assert status["percent_remaining"] == 90.0
    assert status["show_warning"] is False
    assert status["is_exhausted"] is False


def test_usage_status_within_warning_threshold(usage):
    usage["budget"], usage["spent"], usage["warning_pct"] = 10.0, 9.5, 10
    status = ai.get_usage_status("someone")
    assert status["percent_remaining"] == 5.0
    assert status["show_warning"] is True
    assert status["is_exhausted"] is False


def test_usage_status_over_budget_clamps_and_exhausts(usage):
    # Spend can exceed budget (the last call that tipped it over already happened),
    # percent_used must clamp at 100 rather than reporting e.g. 150%.
    usage["budget"], usage["spent"] = 10.0, 15.0
    status = ai.get_usage_status("someone")
    assert status["percent_used"] == 100.0
    assert status["percent_remaining"] == 0.0
    assert status["is_exhausted"] is True


def test_enforce_usage_limits_noop_when_under_budget(usage):
    usage["budget"], usage["spent"] = 10.0, 1.0
    ai.enforce_usage_limits("someone")  # must not raise


def test_enforce_usage_limits_raises_budget_kind_when_over(usage):
    usage["budget"], usage["spent"] = 10.0, 10.0
    with pytest.raises(ai.UsageLimitExceeded) as exc_info:
        ai.enforce_usage_limits("someone")
    assert exc_info.value.kind == "budget"


def test_enforce_usage_limits_raises_rate_limit_kind_before_budget_check(usage):
    # Rate-limit is checked first: a caller hammering the endpoint should get the
    # rate_limit message even if they also happen to still have budget left.
    usage["recent_calls"], usage["max_calls"] = 40, 40
    usage["budget"], usage["spent"] = 10.0, 0.0
    with pytest.raises(ai.UsageLimitExceeded) as exc_info:
        ai.enforce_usage_limits("someone")
    assert exc_info.value.kind == "rate_limit"


def test_enforce_usage_limits_is_noop_outside_cloud_mode(usage, monkeypatch):
    # Self-hosted users spend their own configured API key, so this module's shared-budget
    # guard does not apply to them (see the module docstring in app/ai.py).
    usage["budget"], usage["spent"] = 10.0, 999.0
    usage["recent_calls"], usage["max_calls"] = 999, 40
    monkeypatch.setattr(ai, "IS_CLOUD", False)
    ai.enforce_usage_limits("someone")  # must not raise despite being far over both limits
