"""
Quiz grading (POST /api/quiz/{id}/grade, routers/quizzes.py), driven through the real route as the
test account.

Each test gives the account a throwaway material with one quiz at a chosen review stage, grades it,
and checks the stage, XP and next due date the route returns and stores. Grading writes for real:
an attempt row, an XP ledger row, and the account's XP, level, streak and badges. The fixture
deletes every row it created and puts the profile fields back, whatever the test's outcome.

Expected due dates come from the account's own review settings, read through the same helpers the
route uses, so the tests hold whatever intervals the account has configured.
"""
import pytest

from app import database, local_days, notifications
from app.dependencies import (
    compute_max_stages,
    get_srs_caps_and_repetition,
    get_srs_intervals,
    get_srs_multipliers,
    get_user_timezone,
)

PROFILE_FIELDS = ("xp", "level", "streak", "last_quiz_at", "badges")


@pytest.fixture
def account(test_username, monkeypatch):
    """The test account's database connection, with a factory for throwaway quizzes and a
    cleanup that removes them and restores the profile."""
    # Reminder conversion bookkeeping updates counters shared by every account's reminders. Not
    # what these tests are about, and not something a test run should move.
    monkeypatch.setattr(notifications, "mark_converted", lambda *args, **kwargs: None)

    conn = database.get_db_connection(test_username)
    cursor = conn.cursor()
    user_uuid = conn.user_uuid
    cursor.execute(f"SELECT {', '.join(PROFILE_FIELDS)} FROM user_profile WHERE user_uuid = %s;", (user_uuid,))
    profile = dict(cursor.fetchone())
    created = []

    def new_quiz(stage=0, importance=3):
        cursor.execute(
            """INSERT INTO videos (user_uuid, title, category, importance_rating, status)
               VALUES (%s, 'Quiz grading test material', 'Test', %s, 'ready') RETURNING id;""",
            (user_uuid, importance),
        )
        video_id = cursor.fetchone()["id"]
        cursor.execute(
            """INSERT INTO quizzes (user_uuid, video_id, importance_level, srs_stage, next_review_at, quiz_type)
               VALUES (%s, %s, %s, %s, NOW() + INTERVAL '1 day', 'video') RETURNING id;""",
            (user_uuid, video_id, importance, stage),
        )
        quiz_id = cursor.fetchone()["id"]
        created.append((video_id, quiz_id))
        return quiz_id

    state = {"cursor": cursor, "user_uuid": user_uuid, "username": test_username, "new_quiz": new_quiz,
             "profile": profile}
    try:
        yield state
    finally:
        for video_id, quiz_id in created:
            cursor.execute(
                """DELETE FROM xp_events WHERE quiz_attempt_id IN
                       (SELECT id FROM quiz_attempts WHERE quiz_id = %s AND user_uuid = %s);""",
                (quiz_id, user_uuid),
            )
            cursor.execute("DELETE FROM quiz_attempts WHERE quiz_id = %s AND user_uuid = %s;", (quiz_id, user_uuid))
            cursor.execute("DELETE FROM quizzes WHERE id = %s AND user_uuid = %s;", (quiz_id, user_uuid))
            cursor.execute("DELETE FROM videos WHERE id = %s AND user_uuid = %s;", (video_id, user_uuid))
        cursor.execute(
            f"UPDATE user_profile SET {', '.join(f'{f} = %s' for f in PROFILE_FIELDS)} WHERE user_uuid = %s;",
            tuple(profile[f] for f in PROFILE_FIELDS) + (user_uuid,),
        )
        conn.close()


@pytest.fixture
def grade(client_as, test_username):
    logged_in = client_as(test_username)

    def post(quiz_id, grade_value, question_index=0, is_final=True, progress=True):
        return logged_in.post(f"/api/quiz/{quiz_id}/grade", data={
            "grade": grade_value,
            "question_index": question_index,
            "question": "What does a node do?",
            "given_answer": "It applies one adjustment.",
            "correct_answer": "It applies one adjustment to the image.",
            "progress_srs": str(progress).lower(),
            "is_final_question": str(is_final).lower(),
        })
    return post


def _quiz_row(account, quiz_id):
    account["cursor"].execute(
        "SELECT srs_stage, next_review_at, in_progress_index FROM quizzes WHERE id = %s AND user_uuid = %s;",
        (quiz_id, account["user_uuid"]),
    )
    return account["cursor"].fetchone()


def _schedule(account, importance=3):
    """The account's review settings, as grade_quiz reads them."""
    cursor = account["cursor"]
    intervals = [x for x in get_srs_intervals(cursor, user_uuid=account["user_uuid"]) if x is not None]
    caps = get_srs_caps_and_repetition(cursor, user_uuid=account["user_uuid"])
    return {
        "intervals": intervals,
        "multiplier": get_srs_multipliers(account["username"]).get(importance, 1.5),
        "tz": get_user_timezone(cursor, account["user_uuid"]),
        "max_stages": compute_max_stages(caps["cap_by_importance"], caps["caps"], importance, len(intervals)),
        "repeat_after_last": caps["enable_stage_5_repetition"],
    }


def _due_day(next_review_at, tz):
    return local_days.local_date(next_review_at, tz)


def _attempts(account, quiz_id):
    account["cursor"].execute(
        """SELECT a.grade, a.xp_gained, x.xp AS ledger_xp FROM quiz_attempts a
             LEFT JOIN xp_events x ON x.quiz_attempt_id = a.id
            WHERE a.quiz_id = %s AND a.user_uuid = %s ORDER BY a.id;""",
        (quiz_id, account["user_uuid"]),
    )
    return [dict(r) for r in account["cursor"].fetchall()]


def test_remembering_moves_the_review_stage_forward(account, grade):
    quiz_id = account["new_quiz"](stage=0)
    schedule = _schedule(account)
    before_xp = account["profile"]["xp"] or 0

    response = grade(quiz_id, "remembered")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["new_stage"] == 1
    assert body["xp_gained"] == 10
    assert body["total_xp"] == before_xp + 10

    row = _quiz_row(account, quiz_id)
    assert row["srs_stage"] == 1
    assert row["in_progress_index"] is None
    expected = local_days.schedule_review(schedule["intervals"][0] * schedule["multiplier"], schedule["tz"])
    assert _due_day(row["next_review_at"], schedule["tz"]) == _due_day(expected, schedule["tz"])
    assert _attempts(account, quiz_id) == [{"grade": "remembered", "xp_gained": 10, "ledger_xp": 10}]


def test_forgetting_still_moves_the_stage_forward(account, grade):
    # Intended: a finished review counts as a review, whatever the answers. The next interval is
    # the next stage's, so the material comes back later than this time, not sooner.
    quiz_id = account["new_quiz"](stage=1)
    schedule = _schedule(account)

    response = grade(quiz_id, "forgot")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["new_stage"] == 2
    assert body["xp_gained"] == 3

    row = _quiz_row(account, quiz_id)
    assert row["srs_stage"] == 2
    expected = local_days.schedule_review(schedule["intervals"][1] * schedule["multiplier"], schedule["tz"])
    assert _due_day(row["next_review_at"], schedule["tz"]) == _due_day(expected, schedule["tz"])
    assert _attempts(account, quiz_id) == [{"grade": "forgot", "xp_gained": 3, "ledger_xp": 3}]


def test_the_next_review_is_never_before_tomorrow(account, grade):
    quiz_id = account["new_quiz"](stage=0, importance=5)
    schedule = _schedule(account, importance=5)
    grade(quiz_id, "remembered")
    row = _quiz_row(account, quiz_id)
    today = local_days.local_today(schedule["tz"])
    assert (_due_day(row["next_review_at"], schedule["tz"]) - today).days >= 1


def test_a_question_before_the_last_only_saves_the_position(account, grade):
    quiz_id = account["new_quiz"](stage=2)
    before = _quiz_row(account, quiz_id)

    response = grade(quiz_id, "remembered", question_index=1, is_final=False)
    assert response.status_code == 200, response.text
    row = _quiz_row(account, quiz_id)
    assert row["srs_stage"] == 2
    assert row["next_review_at"] == before["next_review_at"]
    assert row["in_progress_index"] == 2
    # Each answer earns its XP when given, not only at the end.
    assert response.json()["xp_gained"] == 10


def test_practice_outside_the_schedule_leaves_it_alone(account, grade):
    quiz_id = account["new_quiz"](stage=2)
    before = _quiz_row(account, quiz_id)

    response = grade(quiz_id, "remembered", progress=False)
    assert response.status_code == 200, response.text
    row = _quiz_row(account, quiz_id)
    assert row["srs_stage"] == 2
    assert row["next_review_at"] == before["next_review_at"]
    assert response.json()["xp_gained"] == 10


def test_the_last_stage_graduates_the_quiz(account, grade):
    schedule = _schedule(account)
    last = schedule["max_stages"]
    quiz_id = account["new_quiz"](stage=last - 1)

    response = grade(quiz_id, "remembered")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["new_stage"] == last
    assert body["mastered"] is True

    row = _quiz_row(account, quiz_id)
    assert row["srs_stage"] == last
    if not schedule["repeat_after_last"]:
        # Graduated quizzes get a far-future date instead of a real schedule (grade_quiz).
        assert local_days.as_naive_utc(row["next_review_at"]).year == 2999


def test_an_unknown_grade_is_rejected(account, grade):
    quiz_id = account["new_quiz"](stage=0)
    response = grade(quiz_id, "maybe")
    assert response.status_code == 400
    assert _quiz_row(account, quiz_id)["srs_stage"] == 0
    assert _attempts(account, quiz_id) == []


def test_no_test_material_is_left_behind(test_username):
    # Guards the fixture's cleanup: by now every test above has removed what it created.
    conn = database.get_db_connection(test_username)
    try:
        cursor = conn.cursor()
        cursor.execute(
            """SELECT COUNT(*) AS n FROM videos
                WHERE user_uuid = %s AND title = 'Quiz grading test material';""",
            (conn.user_uuid,),
        )
        assert cursor.fetchone()["n"] == 0
    finally:
        conn.close()
