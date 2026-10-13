"""
The starter set (app/starter.py): copying a ready-made example into a free account. Uses one
canned entry and a stand-in for the database connection, so no real account or table is touched.
"""
import json

from app import starter


class FakeCursor:
    def __init__(self, existing=None):
        self.queries, self.existing, self._last = [], existing or set(), None

    def execute(self, sql, params=None):
        self.queries.append((" ".join(sql.split()), params))
        self._last = sql

    def fetchone(self):
        sql = " ".join(self._last.split())
        if sql.startswith("SELECT 1 FROM videos"):
            return {"x": 1} if self.queries[-1][1][1] in self.existing else None
        if sql.startswith("INSERT INTO videos"):
            return {"id": 501}
        return None


ENTRY = {
    "youtube_id": "abc123XYZ_-", "title": "How spaced repetition works", "category": "Learning",
    "thumbnail_url": "https://img.youtube.com/vi/abc123XYZ_-/hqdefault.jpg", "duration_seconds": 300,
    "summary": ["point"], "outline": [],
    "concept_pool": [{"topic": "T", "question": f"q{n}", "answer": "a", "stage": 0, "ai_recommended": True} for n in range(8)],
}


def test_a_starter_entry_becomes_a_ready_material_and_a_due_quiz():
    cursor = FakeCursor()
    assert starter._copy_one(cursor, "user-1", ENTRY, 5) == 1
    video_sql, video_params = next(q for q in cursor.queries if q[0].startswith("INSERT INTO videos"))
    assert "'ready'" in video_sql and "TRUE" in video_sql and video_params[0] == "user-1"
    quiz_sql, quiz_params = next(q for q in cursor.queries if q[0].startswith("INSERT INTO quizzes"))
    assert quiz_params[0] == "user-1" and quiz_params[1] == 501
    assert len(json.loads(quiz_params[4])) == 8 and len(json.loads(quiz_params[5])) == 5


def test_a_video_the_account_already_has_is_not_copied_again():
    cursor = FakeCursor(existing={"abc123XYZ_-"})
    assert starter._copy_one(cursor, "user-1", ENTRY, 5) == 0
    assert not any(q[0].startswith("INSERT") for q in cursor.queries)


def test_nothing_is_added_outside_cloud_mode(monkeypatch):
    monkeypatch.setattr(starter, "IS_CLOUD", False)
    assert starter.add_starter_set_if_due("someone") == 0


def test_a_paying_account_is_not_given_the_starter_set(monkeypatch):
    monkeypatch.setattr(starter, "IS_CLOUD", True)
    monkeypatch.setattr(starter.plans, "get_plan", lambda username: starter.plans.PLAN_PAID)
    called = []
    monkeypatch.setattr(starter.database, "get_db_connection", lambda username: called.append(1))
    assert starter.add_starter_set_if_due("someone") == 0 and not called
