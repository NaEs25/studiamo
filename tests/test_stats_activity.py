"""Per-day activity buckets for the Stats tab: local-day boundaries, zero fill, month clamp."""
from datetime import date, datetime

from app import local_days, stats_activity


def test_activity_lands_on_the_users_local_day():
    berlin = local_days.resolve_timezone("Europe/Berlin")
    # 23:30 UTC on the 3rd is 00:30 on the 4th in Berlin (UTC+2 in October).
    attempts = [(7, datetime(2026, 10, 3, 23, 30)), (7, datetime(2026, 10, 3, 10, 0))]
    xp = [(5, datetime(2026, 10, 3, 23, 30)), (5, datetime(2026, 10, 3, 10, 0))]
    days = stats_activity.bucket_by_local_day(attempts, xp, berlin)
    assert days[date(2026, 10, 3)] == {"quizzes": 1, "xp": 5}
    assert days[date(2026, 10, 4)] == {"quizzes": 1, "xp": 5}


def test_quizzes_count_distinct_quizzes_not_questions():
    attempts = [(1, datetime(2026, 10, 5, 8)), (1, datetime(2026, 10, 5, 9)), (2, datetime(2026, 10, 5, 10))]
    days = stats_activity.bucket_by_local_day(attempts, [], local_days.resolve_timezone(None))
    assert days[date(2026, 10, 5)]["quizzes"] == 2


def test_last_days_is_seven_days_oldest_first_and_zero_filled():
    today = date(2026, 10, 25)
    week = stats_activity.last_days({date(2026, 10, 24): {"quizzes": 3, "xp": 12}}, today)
    assert [d["date"] for d in week][0] == "2026-10-19" and week[-1]["date"] == "2026-10-25"
    assert week[-2] == {"date": "2026-10-24", "quizzes": 3, "xp": 12}
    assert week[-1]["quizzes"] == 0


def test_parse_month_falls_back_and_never_looks_ahead():
    today = date(2026, 10, 25)
    assert stats_activity.parse_month("2026-09", today) == date(2026, 9, 1)
    assert stats_activity.parse_month("2027-01", today) == date(2026, 10, 1)
    assert stats_activity.parse_month("garbage", today) == date(2026, 10, 1)
    assert stats_activity.parse_month("", today) == date(2026, 10, 1)


def test_month_days_covers_december_rollover():
    days = {date(2026, 12, 31): {"quizzes": 1, "xp": 1}, date(2027, 1, 1): {"quizzes": 1, "xp": 1}}
    got = stats_activity.month_days(days, date(2026, 12, 1))
    assert [d["date"] for d in got] == ["2026-12-31"]


def test_activity_route_shape_for_the_test_account(client_as, test_username):
    """Read-only: the route answers with seven zero-filled days and a month, bad months fall back."""
    client = client_as(test_username)
    res = client.get("/api/stats/activity")
    assert res.status_code == 200
    body = res.json()
    assert len(body["week"]) == 7 and body["week"][-1]["date"] == body["today"]
    assert body["month"] == body["today"][:7]
    assert client.get("/api/stats/activity?month=nonsense").json()["month"] == body["month"]
    assert client.get("/api/stats/activity?month=2999-01").json()["month"] == body["month"]


def test_activity_route_requires_login(client):
    assert client.get("/api/stats/activity").status_code in (401, 403)
