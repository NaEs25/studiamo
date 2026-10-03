"""
Every goal, video and quiz belongs to exactly one account. Here the test account asks for, and
tries to change, a goal, a video and a quiz that belong to the second test account, through every
route that takes their id in its path, and must be refused with 404 or 403 each time, leaving
those rows as they were and creating nothing of its own.

The second account's rows are written straight to the database before the tests and deleted
afterwards. Calls a route would only make after letting a request through (the AI client, the
YouTube search, the import queue) are replaced with failures, so a regression here costs nothing
and shows up as a failed test rather than as work done on someone else's behalf.
"""
import json

import pytest

from app import ai, database, youtube
from app.dependencies import card_id_of
from app.import_manager import ImportQueueManager

CARD = {"stage": 1, "topic": "Nodes", "question": "What does a node do?", "answer": "One adjustment."}


def _rows(cursor, user_uuid):
    """Everything about the second account's goal, video and quiz that a route could change."""
    cursor.execute("SELECT * FROM goals WHERE user_uuid = %s ORDER BY id;", (user_uuid,))
    goals = [dict(r) for r in cursor.fetchall()]
    cursor.execute("SELECT * FROM videos WHERE user_uuid = %s ORDER BY id;", (user_uuid,))
    videos = [dict(r) for r in cursor.fetchall()]
    cursor.execute("SELECT * FROM quizzes WHERE user_uuid = %s ORDER BY id;", (user_uuid,))
    quizzes = [dict(r) for r in cursor.fetchall()]
    cursor.execute("SELECT COUNT(*) AS n FROM quiz_attempts WHERE user_uuid = %s;", (user_uuid,))
    attempts = cursor.fetchone()["n"]
    return {"goals": goals, "videos": videos, "quizzes": quizzes, "attempts": attempts}


def _counts(cursor, user_uuid):
    counts = {}
    for table in ("goals", "videos", "quizzes", "quiz_attempts"):
        cursor.execute(f"SELECT COUNT(*) AS n FROM {table} WHERE user_uuid = %s;", (user_uuid,))
        counts[table] = cursor.fetchone()["n"]
    return counts


@pytest.fixture(scope="module")
def others(other_test_username, test_username):
    """A goal, a video in it and the video's quiz, all owned by the second test account."""
    conn = database.get_db_connection(other_test_username)
    cursor = conn.cursor()
    owner = conn.user_uuid
    assert _rows(cursor, owner) == {"goals": [], "videos": [], "quizzes": [], "attempts": 0}, (
        "The second test account should hold nothing between runs."
    )
    cursor.execute(
        """INSERT INTO goals (user_uuid, title, description, order_index)
           VALUES (%s, 'Ownership test goal', 'Belongs to the second test account', 1) RETURNING id;""",
        (owner,),
    )
    goal_id = cursor.fetchone()["id"]
    cursor.execute(
        """INSERT INTO videos (user_uuid, title, category, importance_rating, learning_goal_id, status)
           VALUES (%s, 'Ownership test material', 'Test', 3, %s, 'ready') RETURNING id;""",
        (owner, goal_id),
    )
    video_id = cursor.fetchone()["id"]
    cursor.execute(
        """INSERT INTO quizzes (user_uuid, video_id, goal_id, importance_level, srs_stage, next_review_at,
                                quiz_type, concept_pool)
           VALUES (%s, %s, %s, 3, 1, NOW() + INTERVAL '1 day', 'video', %s::jsonb) RETURNING id;""",
        (owner, video_id, goal_id, json.dumps([CARD])),
    )
    quiz_id = cursor.fetchone()["id"]

    tester = database.get_db_connection(test_username)
    tester_cursor = tester.cursor()
    try:
        yield {
            "goal": goal_id, "video": video_id, "quiz": quiz_id, "card": card_id_of(CARD),
            "snapshot": lambda: _rows(cursor, owner),
            "tester_counts": lambda: _counts(tester_cursor, tester.user_uuid),
        }
    finally:
        cursor.execute("DELETE FROM quiz_attempts WHERE user_uuid = %s;", (owner,))
        cursor.execute("DELETE FROM quizzes WHERE user_uuid = %s;", (owner,))
        cursor.execute("DELETE FROM videos WHERE user_uuid = %s;", (owner,))
        cursor.execute("DELETE FROM goals WHERE user_uuid = %s;", (owner,))
        conn.close()
        tester.close()


@pytest.fixture
def as_tester(client_as, test_username, monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("reached a call that only follows a granted request")

    monkeypatch.setattr(ai, "get_gemini_client", refuse)
    monkeypatch.setattr(youtube, "search_youtube_recommendations", refuse)
    monkeypatch.setattr(ImportQueueManager, "enqueue_task", refuse)
    return client_as(test_username)


# (method, path, form data). {goal}, {video}, {quiz} and {card}, in the path or the data, are
# the second account's.
GOAL_ROUTES = [
    ("POST", "/api/goals/{goal}/edit", {"title": "Taken over", "description": ""}),
    ("POST", "/api/goals/{goal}/reorder", {"direction": "up"}),
    ("POST", "/api/goals/{goal}/archive", {}),
    ("GET", "/api/goals/{goal}/recommendations", None),
    ("POST", "/api/goals/{goal}/recommendations/replace_one", {"dismissed_yt_id": "abcDEF12345"}),
    ("POST", "/api/goals/{goal}/recommendations/reload_all", {}),
    ("POST", "/api/goals/{goal}/practice", {"question_count": "5"}),
    ("DELETE", "/api/goals/{goal}?delete_materials=true", None),
]
VIDEO_ROUTES = [
    ("GET", "/api/videos/{video}/document", None),
    ("GET", "/api/videos/{video}/pdf", None),
    ("GET", "/api/videos/{video}/factcheck", None),
    ("GET", "/api/videos/{video}/concept-pool", None),
    ("GET", "/api/videos/{video}/stats", None),
    ("POST", "/api/videos/{video}/retry", {}),
    ("POST", "/api/videos/{video}/archive", {}),
    ("POST", "/api/videos/{video}/pause", {}),
    ("POST", "/api/videos/{video}/goal", {"learning_goal_id": "{goal}"}),
    ("POST", "/api/videos/{video}/watchlist", {}),
    ("POST", "/api/videos/{video}/edit", {"title": "Taken over", "custom_notes": "Taken over"}),
    ("POST", "/api/videos/{video}/position", {"position": "42"}),
    ("POST", "/api/videos/{video}/confirm_import", {}),
    ("POST", "/api/videos/{video}/generate_quiz", {"level": "3"}),
    ("POST", "/api/videos/{video}/cards", {"stage": "1", "topic": "Nodes", "question": "Q?", "answer": "A."}),
    ("PATCH", "/api/videos/{video}/cards/{card}", {"question": "Taken over?"}),
    ("DELETE", "/api/videos/{video}/cards/{card}", None),
    ("POST", "/api/videos/{video}/topics/rename", {"old_topic": "Nodes", "new_topic": "Taken over"}),
    ("POST", "/api/videos/{video}/focus", {"focus_topics": "{{}}"}),
    ("DELETE", "/api/videos/{video}", None),
]
QUIZ_ROUTES = [
    ("GET", "/api/quiz/{quiz}", None),
    ("POST", "/api/quiz/{quiz}/grade", {"grade": "remembered", "question_index": "0", "question": "Q?",
                                        "correct_answer": "A.", "is_final_question": "true"}),
    ("POST", "/api/quiz/{quiz}/reschedule", {}),
]


def _request(client, others, method, path, data):
    url = path.format(**others)
    if data is None:
        return client.request(method, url)
    return client.request(method, url, data={k: v.format(**others) for k, v in data.items()})


@pytest.mark.parametrize("method, path, data", GOAL_ROUTES + VIDEO_ROUTES + QUIZ_ROUTES,
                         ids=[f"{m} {p}" for m, p, _ in GOAL_ROUTES + VIDEO_ROUTES + QUIZ_ROUTES])
def test_another_accounts_rows_are_out_of_reach(as_tester, others, method, path, data):
    before = others["snapshot"]()
    tester_before = others["tester_counts"]()

    response = _request(as_tester, others, method, path, data)

    assert response.status_code in (403, 404), f"{method} {path} -> {response.status_code}: {response.text[:200]}"
    assert others["snapshot"]() == before
    assert others["tester_counts"]() == tester_before


def test_lists_show_only_the_accounts_own_rows(as_tester, others):
    dashboard = as_tester.get("/api/dashboard").json()
    seen_goals = {g["id"] for g in dashboard.get("goals", []) + dashboard.get("archived_goals", [])}
    seen_videos = {v["id"] for v in dashboard.get("videos", []) + dashboard.get("archived", [])}
    seen_quizzes = {q["id"] for q in dashboard.get("quizzes", [])}
    assert others["goal"] not in seen_goals
    assert others["video"] not in seen_videos
    assert others["quiz"] not in seen_quizzes

    goals = as_tester.get("/api/goals").json() + as_tester.get("/api/goals?include_archived=true").json()
    assert others["goal"] not in {g["id"] for g in goals}
