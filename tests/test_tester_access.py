"""
Coverage for time-boxed tester access (app/database.py, tester_access in app/schema.py).

Access control is the thing being changed here, so the failure modes are all silent: a
tester who cannot log in, or a paywall that never fires. Nothing announces itself. Hence
the density of cases below.

Scope, deliberately: everything that decides *whether* access is granted is derived by
`_derive_tester_state` and the `has_app_access` branch order, both of which are pure
functions of one database row. Those are tested exhaustively here with hand-built rows and
no database at all.

What is NOT covered here is grant/extend/end round-tripping through real rows, because
conftest.py's rule for this suite is that it runs against the shared staging database and
must never create, modify or delete real data. The two places where the *database* rather
than Python holds the invariant (the CHECK constraint and the GREATEST extension
expression) are covered against the real database inside transactions that always roll
back, so nothing is written.
"""
from datetime import datetime, timedelta, timezone

import pytest

from app import database


NOW = datetime.now(timezone.utc)


def _row(**overrides):
    """One _TESTER_ACCESS_SQL result row: profile columns plus the joined current grant."""
    row = {
        "user_uuid": "00000000-0000-0000-0000-000000000000",
        "subscription_status": "inactive",
        "is_tester": False,
        "ls_ends_at": None,
        "grant_id": None,
        "granted_at": None,
        "expires_at": None,
        "period_days": None,
        "revoked_at": None,
        "welcome_seen_at": NOW,
        "reminder_7d_seen_at": None,
        "reminder_1d_seen_at": None,
        "expiry_seen_at": None,
    }
    row.update(overrides)
    return row


def _grant(days_from_now, **overrides):
    """A row carrying an active grant expiring `days_from_now` days out."""
    fields = {
        "grant_id": 1,
        "granted_at": NOW - timedelta(days=1),
        "expires_at": NOW + timedelta(days=days_from_now),
        "period_days": 14,
        "is_tester": True,
    }
    fields.update(overrides)
    return _row(**fields)


def _unlimited(**overrides):
    """A row carrying an unlimited grant: period_days = 0, expires_at NULL."""
    fields = {"grant_id": 1, "granted_at": NOW, "expires_at": None,
              "period_days": 0, "is_tester": True}
    fields.update(overrides)
    return _row(**fields)


# --- Derived state -------------------------------------------------------------------

@pytest.mark.parametrize("row, expected", [
    (None, "none"),
    (_row(), "none"),
    (_row(is_tester=True), "active"),                       # legacy flag, no grant row
    (_grant(10), "active"),
    (_unlimited(), "active"),
    (_grant(-1), "expired"),
    (_grant(5, revoked_at=NOW), "revoked"),
    (_unlimited(revoked_at=NOW), "revoked"),
])
def test_derived_state(row, expected):
    assert database._derive_tester_state(row)["state"] == expected


def test_unlimited_and_legacy_are_not_the_same_state():
    """Both grant access forever, but one is a decision and the other is unmigrated
    history the admin surfaces still need to distinguish."""
    legacy = database._derive_tester_state(_row(is_tester=True))
    unlimited = database._derive_tester_state(_unlimited())

    assert (legacy["legacy"], legacy["unlimited"]) == (True, False)
    assert (unlimited["legacy"], unlimited["unlimited"]) == (False, True)
    assert legacy["days_left"] is unlimited["days_left"] is None


def test_unlimited_reports_period_days_zero():
    assert database._derive_tester_state(_unlimited())["period_days"] == 0


# --- has_app_access branch order -----------------------------------------------------
#
# The LEFT JOIN yields expires_at = NULL both for an unlimited grant and for no grant at
# all. Branching on expires_at alone would grandfather every account that ever had the flag
# set and make the expiry check unreachable, so grant_id is what separates them. These two
# tests are the guard on that.

def test_expired_grant_does_not_fall_back_to_the_legacy_branch():
    """An expired grant on an account whose is_tester cache is still TRUE must read as
    expired. This is the regression that would silently grandfather everyone."""
    state = database._derive_tester_state(_grant(-1, is_tester=True))
    assert state["state"] == "expired"
    assert state["legacy"] is False


def test_legacy_flag_without_a_grant_row_stays_active():
    """Deploying time-boxing must not cut off testers who predate the table."""
    assert database._derive_tester_state(_row(is_tester=True))["state"] == "active"


# --- days_left -----------------------------------------------------------------------

def test_days_left_uses_calendar_dates_not_24_hour_blocks():
    """Granted at 23:50, someone must not read as '0 days left' ten minutes later."""
    tomorrow_early = datetime.now(timezone.utc).replace(hour=0, minute=10) + timedelta(days=1)
    assert database._tester_days_left(tomorrow_early) == 1


def test_days_left_is_zero_on_the_final_day_not_negative():
    assert database._tester_days_left(NOW + timedelta(hours=2)) == 0
    assert database._tester_days_left(NOW - timedelta(days=30)) == 0


def test_days_left_is_none_when_unlimited():
    assert database._tester_days_left(None) is None


def test_naive_timestamps_do_not_raise():
    """Columns are TIMESTAMPTZ, but a naive value can arrive via a direct DB edit, and
    comparing naive to aware raises rather than answering wrongly."""
    naive = (NOW + timedelta(days=3)).replace(tzinfo=None)
    assert database._tester_days_left(naive) == 3
    assert database._derive_tester_state(_grant(3, expires_at=naive))["state"] == "active"


# --- Reminder thresholds -------------------------------------------------------------

@pytest.mark.parametrize("days_out, expected", [
    (14, None), (8, None), (7, "7d"), (5, "7d"), (2, "7d"), (1, "1d"),
])
def test_reminder_thresholds(days_out, expected):
    assert database._derive_tester_state(_grant(days_out))["needs_reminder"] == expected


def test_one_day_reminder_wins_over_seven_day():
    """A short extension must not fire both modals at once."""
    assert database._derive_tester_state(_grant(1))["needs_reminder"] == "1d"


def test_reminders_are_not_repeated_once_seen():
    assert database._derive_tester_state(_grant(5, reminder_7d_seen_at=NOW))["needs_reminder"] is None
    assert database._derive_tester_state(
        _grant(1, reminder_7d_seen_at=NOW, reminder_1d_seen_at=NOW)
    )["needs_reminder"] is None


def test_unlimited_grants_never_get_reminders():
    """`None <= 7` raises in Python and is silently false-y in JS, so the None guard has to
    come before any comparison."""
    state = database._derive_tester_state(_unlimited(welcome_seen_at=NOW))
    assert state["needs_reminder"] is None


def test_legacy_grants_never_get_reminders():
    assert database._derive_tester_state(_row(is_tester=True))["needs_reminder"] is None


def test_welcome_is_offered_once_and_only_while_active():
    assert database._derive_tester_state(_grant(10, welcome_seen_at=None))["needs_welcome"] is True
    assert database._derive_tester_state(_grant(10))["needs_welcome"] is False
    assert database._derive_tester_state(_grant(-1, welcome_seen_at=None))["needs_welcome"] is False


def test_unlimited_grants_still_get_a_welcome():
    assert database._derive_tester_state(_unlimited(welcome_seen_at=None))["needs_welcome"] is True


# --- Period clamping -----------------------------------------------------------------

def test_zero_survives_the_clamp():
    """max(1, min(days, cap)) would turn an intentional unlimited grant into a one-day one,
    which is the opposite of what was asked for."""
    assert database._clamp_period_days(0) == 0


def test_clamp_keeps_ordinary_values_and_caps_absurd_ones():
    assert database._clamp_period_days(14) == 14
    assert database._clamp_period_days(99999) <= database.get_tester_period_setting(
        "tester_max_period_days", database._TESTER_MAX_PERIOD_DAYS
    )


def test_negative_periods_are_rejected():
    with pytest.raises(ValueError):
        database._clamp_period_days(-1)


def test_default_period_is_fourteen_days():
    assert database._TESTER_DEFAULT_PERIOD_DAYS == 14


def test_period_setting_falls_back_on_unparseable_values(monkeypatch):
    monkeypatch.setattr(database, "get_app_setting", lambda key, default="": "not-a-number")
    assert database.get_tester_period_setting("tester_default_period_days", 14) == 14


# --- API payload ---------------------------------------------------------------------

def test_payload_is_json_safe_and_complete():
    payload = database.tester_state_payload(database._derive_tester_state(_grant(10)))
    assert isinstance(payload["expires_at"], str)
    assert set(payload) == {
        "state", "granted_at", "expires_at", "period_days", "days_left",
        "unlimited", "legacy", "needs_welcome", "needs_reminder",
    }


def test_payload_nulls_dates_for_unlimited():
    payload = database.tester_state_payload(database._derive_tester_state(_unlimited()))
    assert payload["expires_at"] is None
    assert payload["days_left"] is None
    assert payload["unlimited"] is True


def test_unknown_notice_kind_is_rejected():
    """The column name is interpolated into SQL, so the whitelist is load-bearing."""
    with pytest.raises(ValueError):
        database.mark_tester_notice_seen("someone", "'; DROP TABLE tester_access; --")


# --- Invariants the database holds, not Python ---------------------------------------
#
# Both run inside a transaction that is always rolled back, so nothing is written to the
# shared staging database (see conftest.py).

pytest.importorskip("psycopg2")
import psycopg2  # noqa: E402


@pytest.fixture
def rolled_back_cursor():
    try:
        conn = psycopg2.connect(database.get_supabase_db_url())
    except Exception as exc:
        pytest.skip(f"no database connection available: {exc}")
    try:
        conn.autocommit = False
        yield conn.cursor()
    finally:
        conn.rollback()
        conn.close()


@pytest.mark.parametrize("period_days, expires_at", [
    (0, "CURRENT_TIMESTAMP"),   # unlimited must not carry an end date
    (14, "NULL"),               # a timed grant must have one
])
def test_check_constraint_rejects_disagreeing_columns(rolled_back_cursor, period_days, expires_at):
    """period_days and expires_at encode one fact. Three code paths write this row, so the
    invariant is the database's job, not a convention they each have to remember."""
    with pytest.raises(psycopg2.errors.CheckViolation):
        rolled_back_cursor.execute(
            f"""INSERT INTO tester_access (user_uuid, period_days, expires_at)
                VALUES ('00000000-0000-0000-0000-000000000000', %s, {expires_at});""",
            (period_days,),
        )


def test_extension_of_an_expired_grant_starts_from_today(rolled_back_cursor):
    """Extending a lapsed grant by 7 days must mean 7 days from now, not 7 days from a date
    already in the past, which would change nothing visible."""
    rolled_back_cursor.execute(
        """SELECT GREATEST(%s::timestamptz, CURRENT_TIMESTAMP) + (7 * INTERVAL '1 day')
                  > CURRENT_TIMESTAMP + INTERVAL '6 days' AS lands_in_the_future;""",
        (NOW - timedelta(days=30),),
    )
    assert rolled_back_cursor.fetchone()[0] is True
