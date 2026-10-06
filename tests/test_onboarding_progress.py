"""
The welcome flow resumes where it was left: the step reached and the goal it created are saved
server-side and come back from the status route, but only while they are still the account's own
and the flow is unfinished.

Runs as the first test account with a goal of its own and a goal of the second account's. The
goals are written straight to the database and removed afterwards, and the first account's
onboarding columns are put back as they were.
"""
import pytest

from app import database


@pytest.fixture
def setup(test_username, other_test_username, client_as):
    mine = database.get_db_connection(test_username)
    theirs = database.get_db_connection(other_test_username)
    cur = mine.cursor()
    cur.execute(
        """SELECT has_seen_onboarding, onboarding_step, onboarding_goal_id, onboarding_video_id
           FROM user_profile WHERE user_uuid = %s;""",
        (mine.user_uuid,),
    )
    before = dict(cur.fetchone())
    ids = []
    for conn in (mine, theirs):
        c = conn.cursor()
        c.execute(
            "INSERT INTO goals (user_uuid, title, order_index) VALUES (%s, 'Onboarding resume test', 1) RETURNING id;",
            (conn.user_uuid,),
        )
        ids.append(c.fetchone()["id"])
        conn.commit()
    cur.execute("UPDATE user_profile SET has_seen_onboarding = 0 WHERE user_uuid = %s;", (mine.user_uuid,))
    mine.commit()
    try:
        yield client_as(test_username), ids[0], ids[1]
    finally:
        cur = mine.cursor()
        cur.execute(
            """UPDATE user_profile SET has_seen_onboarding = %s, onboarding_step = %s,
                      onboarding_goal_id = %s, onboarding_video_id = %s WHERE user_uuid = %s;""",
            (before["has_seen_onboarding"], before["onboarding_step"], before["onboarding_goal_id"],
             before["onboarding_video_id"], mine.user_uuid),
        )
        for conn, goal_id in ((mine, ids[0]), (theirs, ids[1])):
            conn.cursor().execute("DELETE FROM goals WHERE id = %s AND user_uuid = %s;", (goal_id, conn.user_uuid))
            conn.commit()
        mine.close()
        theirs.close()


def _progress(client):
    return client.get("/api/user/onboarding_status").json()["onboarding_progress"]


def test_own_goal_and_step_come_back(setup):
    client, own_goal, _ = setup
    assert client.post("/api/user/onboarding_progress", data={"step": "video", "goal_id": own_goal}).status_code == 200
    progress = _progress(client)
    assert progress["step"] == "video"
    assert progress["goal"] == {"id": own_goal, "title": "Onboarding resume test"}
    assert progress["video"] is None


def test_another_accounts_goal_is_dropped(setup):
    client, _, foreign_goal = setup
    assert client.post("/api/user/onboarding_progress", data={"step": "video", "goal_id": foreign_goal}).status_code == 200
    progress = _progress(client)
    assert progress["step"] == "video"
    assert progress["goal"] is None


def test_unknown_step_is_refused(setup):
    client, _, _ = setup
    assert client.post("/api/user/onboarding_progress", data={"step": "nope"}).status_code == 400


def test_finished_flow_keeps_no_position_and_ignores_late_saves(setup):
    client, own_goal, _ = setup
    client.post("/api/user/onboarding_progress", data={"step": "goal", "goal_id": own_goal})
    assert client.post("/api/user/onboarding_status", data={"has_seen_onboarding": "true"}).status_code == 200
    assert _progress(client) is None
    client.post("/api/user/onboarding_progress", data={"step": "chompy"})
    assert _progress(client) is None
