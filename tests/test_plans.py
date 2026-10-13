"""
Coverage for the free plan's gate (app/plans.py and its use in ai.enforce_usage_limits).

The decision logic runs without a database: get_plan reads one access row, which the tests
replace. The claim table is exercised against the shared staging database under a random
throwaway account id, never a real account: the rows are written and removed within the test,
and nothing else (no user_profile, no video) is touched.
"""
import threading
import uuid

import pytest

from app import ai, plans


def _row(status="inactive", tester_grant=False, is_tester=False):
    return {
        "user_uuid": str(uuid.uuid4()), "subscription_status": status, "is_tester": is_tester,
        "ls_ends_at": None, "ls_renews_at": None, "ls_customer_portal_url": None,
        "grant_id": 1 if tester_grant else None, "granted_at": None, "expires_at": None,
        "period_days": 0 if tester_grant else None, "revoked_at": None, "welcome_seen_at": None,
        "reminder_7d_seen_at": None, "reminder_1d_seen_at": None, "expiry_seen_at": None,
    }


@pytest.fixture
def cloud(monkeypatch):
    monkeypatch.setattr(plans, "IS_CLOUD", True)


def _plan_for(monkeypatch, row):
    monkeypatch.setattr(plans.database, "_fetch_access_row", lambda username: row)
    return plans.get_plan("someone")


def test_no_subscription_and_no_grant_is_free(cloud, monkeypatch):
    assert _plan_for(monkeypatch, _row()) == plans.PLAN_FREE


def test_missing_profile_row_is_free(cloud, monkeypatch):
    assert _plan_for(monkeypatch, None) == plans.PLAN_FREE


def test_active_subscription_is_paid(cloud, monkeypatch):
    assert _plan_for(monkeypatch, _row("active")) == plans.PLAN_PAID


def test_unlimited_tester_grant_is_tester(cloud, monkeypatch):
    assert _plan_for(monkeypatch, _row(tester_grant=True, is_tester=True)) == plans.PLAN_TESTER


def test_tester_who_also_subscribed_is_paid(cloud, monkeypatch):
    assert _plan_for(monkeypatch, _row("active", tester_grant=True, is_tester=True)) == plans.PLAN_PAID


def test_unreadable_standing_fails_closed_to_free(cloud, monkeypatch):
    def boom(username):
        raise RuntimeError("database unreachable")
    monkeypatch.setattr(plans.database, "_fetch_access_row", boom)
    assert plans.get_plan("someone") == plans.PLAN_FREE


def test_self_hosted_is_never_metered(monkeypatch):
    monkeypatch.setattr(plans, "IS_CLOUD", False)
    assert plans.get_plan("someone") == plans.PLAN_PAID


def test_ip_hash_needs_a_salt_and_an_address(monkeypatch):
    monkeypatch.delenv("FREE_VIDEO_IP_SALT", raising=False)
    assert plans.hash_client_ip("203.0.113.9") is None
    monkeypatch.setenv("FREE_VIDEO_IP_SALT", "test-salt")
    assert plans.hash_client_ip("") is None
    assert plans.hash_client_ip(None) is None
    first = plans.hash_client_ip("203.0.113.9")
    assert first and first != "203.0.113.9" and first == plans.hash_client_ip(" 203.0.113.9 ")
    assert first != plans.hash_client_ip("203.0.113.10")


# --- the chokepoint -------------------------------------------------------------------------

@pytest.fixture
def chokepoint(monkeypatch):
    monkeypatch.setattr(ai, "IS_CLOUD", True)
    monkeypatch.setattr(ai, "get_monthly_budget_usd", lambda username: 10.0)
    monkeypatch.setattr(ai, "get_monthly_cost_usd", lambda username: 0.0)
    monkeypatch.setattr(ai, "get_recent_call_count", lambda username, minutes=None: 0)
    monkeypatch.setattr(ai, "_get_app_setting_int", lambda key, default: default)


def test_chokepoint_refuses_free_account_outside_its_scope(chokepoint, monkeypatch):
    monkeypatch.setattr(plans, "get_plan", lambda username: plans.PLAN_FREE)
    monkeypatch.setattr(plans, "scope_allows", lambda username: False)
    with pytest.raises(ai.PlanRequired) as caught:
        ai.enforce_usage_limits("someone")
    assert caught.value.kind == "plan_required"
    assert isinstance(caught.value, ai.UsageLimitExceeded)


def test_chokepoint_lets_free_account_through_inside_its_scope(chokepoint, monkeypatch):
    monkeypatch.setattr(plans, "get_plan", lambda username: plans.PLAN_FREE)
    monkeypatch.setattr(plans, "scope_allows", lambda username: True)
    ai.enforce_usage_limits("someone")


@pytest.mark.parametrize("plan", [plans.PLAN_PAID, plans.PLAN_TESTER])
def test_chokepoint_does_not_ask_paying_accounts_for_a_scope(chokepoint, monkeypatch, plan):
    monkeypatch.setattr(plans, "get_plan", lambda username: plan)
    monkeypatch.setattr(plans, "scope_allows", lambda username: False)
    ai.enforce_usage_limits("someone")


def test_refused_ai_call_is_402_with_a_code_and_limits_stay_429():
    plan_error = ai.usage_http_exception(ai.PlanRequired())
    assert plan_error.status_code == 402 and plan_error.detail["code"] == ai.PLAN_REQUIRED_CODE
    cap_error = ai.usage_http_exception(ai.UsageLimitExceeded("budget", "over"))
    assert cap_error.status_code == 429


# --- the claim, against the staging database --------------------------------------------------

@pytest.fixture
def claimant(monkeypatch):
    user_uuid = str(uuid.uuid4())
    settings = {"free_video_ip_max": 1, "free_video_ip_window_days": 30, "free_video_max_releases": 1}
    monkeypatch.setattr(plans, "_setting_int", lambda key, default: settings.get(key, default))
    yield user_uuid, settings
    conn = plans._connect()
    try:
        conn.cursor().execute("DELETE FROM free_video_claims WHERE user_uuid = %s OR ip_hash LIKE 'test-%%';", (user_uuid,))
    finally:
        plans.database.release_pooled_connection(conn)


def test_claim_without_an_address_hash_is_unavailable(claimant):
    user_uuid, _ = claimant
    assert plans.claim_free_video(user_uuid, None) == plans.CLAIM_UNAVAILABLE
    assert plans.get_free_video_state(user_uuid)["state"] == "available"


def test_second_claim_for_one_account_is_refused(claimant):
    user_uuid, _ = claimant
    assert plans.claim_free_video(user_uuid, "test-" + user_uuid[:8]) == plans.CLAIM_OK
    assert plans.claim_free_video(user_uuid, "test-" + user_uuid[:8]) == plans.CLAIM_USED
    assert plans.get_free_video_state(user_uuid)["state"] == "used"


def test_parallel_claims_for_one_account_have_exactly_one_winner(claimant):
    user_uuid, _ = claimant
    results = []
    barrier = threading.Barrier(6)

    def attempt(n):
        barrier.wait()
        results.append(plans.claim_free_video(user_uuid, f"test-{user_uuid[:6]}-{n}"))

    threads = [threading.Thread(target=attempt, args=(n,)) for n in range(6)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert results.count(plans.CLAIM_OK) == 1


def test_address_threshold_stops_a_second_account_from_the_same_address(claimant):
    user_uuid, _ = claimant
    other = str(uuid.uuid4())
    address = "test-" + user_uuid[:8]
    assert plans.claim_free_video(user_uuid, address) == plans.CLAIM_OK
    assert plans.claim_free_video(other, address) == plans.CLAIM_IP_LIMIT
    assert plans.get_free_video_state(other)["state"] == "available"


def test_failed_import_gives_the_claim_back_once(claimant):
    user_uuid, _ = claimant
    address = "test-" + user_uuid[:8]
    assert plans.claim_free_video(user_uuid, address) == plans.CLAIM_OK
    plans.attach_free_video(user_uuid, 4242)
    assert plans.release_free_video(user_uuid, 4242) is True
    assert plans.get_free_video_state(user_uuid)["state"] == "available"
    # The same address checks out again for its own account on a second claim.
    assert plans.claim_free_video(user_uuid, address) == plans.CLAIM_OK
    plans.attach_free_video(user_uuid, 4243)
    # The release cap is spent: the generation stays used.
    assert plans.release_free_video(user_uuid, 4243) is False
    assert plans.get_free_video_state(user_uuid)["state"] == "used"


def test_release_only_touches_the_material_the_claim_is_on(claimant):
    user_uuid, _ = claimant
    assert plans.claim_free_video(user_uuid, "test-" + user_uuid[:8]) == plans.CLAIM_OK
    plans.attach_free_video(user_uuid, 1)
    assert plans.release_free_video(user_uuid, 2) is False
    assert plans.get_free_video_state(user_uuid)["state"] == "used"


def test_unattached_claim_is_released_when_no_import_was_enqueued(claimant):
    user_uuid, _ = claimant
    assert plans.claim_free_video(user_uuid, "test-" + user_uuid[:8]) == plans.CLAIM_OK
    assert plans.release_unattached_claim(user_uuid) is True
    assert plans.get_free_video_state(user_uuid)["state"] == "available"


def test_unattached_release_does_not_free_a_claim_that_is_on_a_material(claimant):
    user_uuid, _ = claimant
    assert plans.claim_free_video(user_uuid, "test-" + user_uuid[:8]) == plans.CLAIM_OK
    plans.attach_free_video(user_uuid, 7)
    assert plans.release_unattached_claim(user_uuid) is False
    assert plans.get_free_video_state(user_uuid)["state"] == "used"


def test_scope_opens_only_for_the_claimed_material(claimant, monkeypatch):
    user_uuid, _ = claimant
    monkeypatch.setattr(plans, "IS_CLOUD", True)
    monkeypatch.setattr(plans, "get_user_uuid_from_db", lambda username: user_uuid)
    monkeypatch.setattr(plans, "get_plan", lambda username: plans.PLAN_FREE)
    assert plans.claim_free_video(user_uuid, "test-" + user_uuid[:8]) == plans.CLAIM_OK
    plans.attach_free_video(user_uuid, 99)
    with plans.generation_scope("someone", 99) as opened:
        assert opened and plans.scope_allows("someone")
    assert not plans.scope_allows("someone")
    with plans.generation_scope("someone", 100) as opened:
        assert not opened and not plans.scope_allows("someone")


# --- storage limits and link cap ------------------------------------------------------------

def test_free_plan_gets_its_own_tight_storage_limits(monkeypatch):
    monkeypatch.setattr(plans, "get_plan", lambda username: plans.PLAN_FREE)
    monkeypatch.setattr(plans, "_setting_int", lambda key, default: default)
    quota, per_file = plans.storage_limits("someone")
    assert quota == plans._FALLBACK_FREE_QUOTA_MB * 1024 * 1024
    assert per_file == plans._FALLBACK_FREE_MAX_FILE_MB * 1024 * 1024
    assert plans.max_links("someone") == plans._FALLBACK_FREE_MAX_LINKS


def test_paying_account_keeps_the_normal_limits_and_no_link_cap(monkeypatch):
    from app import config
    monkeypatch.setattr(plans, "get_plan", lambda username: plans.PLAN_PAID)
    assert plans.storage_limits("someone") == (config.get_user_storage_quota_bytes(), config.get_max_file_upload_bytes())
    assert plans.max_links("someone") == 0
