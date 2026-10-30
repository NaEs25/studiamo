"""
Folders inside a goal (app/routers/goals.py): create, rename, move a material in and out, delete,
and the ownership rules. Runs as the two test accounts and removes every row it creates.
"""
import pytest

from app import database

GOAL_TITLE = "Folder test goal zz"
YT = "zzFolder001"


def _purge(username):
    conn = database.get_db_connection(username)
    try:
        cursor = conn.cursor()
        uid = conn.user_uuid
        cursor.execute("DELETE FROM videos WHERE user_uuid = %s AND youtube_id = %s;", (uid, YT))
        cursor.execute("DELETE FROM goal_folders WHERE user_uuid = %s AND goal_id IN (SELECT id FROM goals WHERE user_uuid = %s AND title = %s);", (uid, uid, GOAL_TITLE))
        cursor.execute("DELETE FROM goals WHERE user_uuid = %s AND title = %s;", (uid, GOAL_TITLE))
        conn.commit()
    finally:
        conn.close()


@pytest.fixture
def world(client_as, test_username, other_test_username):
    _purge(test_username)
    owner, other = client_as(test_username), client_as(other_test_username)
    goal_id = owner.post("/api/goals", data={"title": GOAL_TITLE}).json()["goal_id"]
    conn = database.get_db_connection(test_username)
    try:
        cursor = conn.cursor()
        cursor.execute(
            """INSERT INTO videos (user_uuid, youtube_id, title, category, importance_rating, status, learning_goal_id, is_watchlist)
               VALUES (%s, %s, 'Folder test video', 'Test', 3, 'ready', %s, 0) RETURNING id;""",
            (conn.user_uuid, YT, goal_id))
        video_id = cursor.fetchone()["id"]
        conn.commit()
    finally:
        conn.close()
    try:
        yield owner, other, goal_id, video_id
    finally:
        _purge(test_username)


def _folder_of(owner, video_id):
    videos = owner.get("/api/dashboard").json()["videos"]
    return next(v for v in videos if v["id"] == video_id)["folder_id"]


def test_folder_lifecycle_and_moves(world):
    owner, _, goal_id, video_id = world
    created = owner.post(f"/api/goals/{goal_id}/folders", data={"name": "  Part   one "})
    assert created.status_code == 200 and created.json()["name"] == "Part one"
    folder_id = created.json()["folder_id"]

    assert owner.post(f"/api/goals/{goal_id}/folders", data={"name": "part ONE"}).status_code == 409
    assert owner.post(f"/api/goals/{goal_id}/folders", data={"name": "   "}).status_code == 400
    assert owner.post(f"/api/goals/{goal_id}/folders/{folder_id}/rename", data={"name": "Part 1"}).json()["name"] == "Part 1"
    folders = owner.get("/api/dashboard").json()["folders"]
    assert [f["name"] for f in folders if f["goal_id"] == goal_id] == ["Part 1"]

    assert owner.post(f"/api/goals/{goal_id}/materials/{video_id}/folder", data={"folder_id": folder_id}).status_code == 200
    assert _folder_of(owner, video_id) == folder_id
    # Moving it out (no folder_id) puts it back in the goal.
    assert owner.post(f"/api/goals/{goal_id}/materials/{video_id}/folder").status_code == 200
    assert _folder_of(owner, video_id) is None

    owner.post(f"/api/goals/{goal_id}/materials/{video_id}/folder", data={"folder_id": folder_id})
    assert owner.delete(f"/api/goals/{goal_id}/folders/{folder_id}").status_code == 200
    # Deleting a folder keeps its materials, outside any folder.
    assert _folder_of(owner, video_id) is None
    assert not [f for f in owner.get("/api/dashboard").json()["folders"] if f["goal_id"] == goal_id]


def test_another_account_cannot_reach_the_folder_or_goal(world):
    owner, other, goal_id, video_id = world
    folder_id = owner.post(f"/api/goals/{goal_id}/folders", data={"name": "Mine"}).json()["folder_id"]
    assert other.post(f"/api/goals/{goal_id}/folders", data={"name": "Theirs"}).status_code == 404
    assert other.post(f"/api/goals/{goal_id}/folders/{folder_id}/rename", data={"name": "X"}).status_code == 404
    assert other.delete(f"/api/goals/{goal_id}/folders/{folder_id}").status_code == 404
    assert other.post(f"/api/goals/{goal_id}/materials/{video_id}/folder", data={"folder_id": folder_id}).status_code == 404
    assert _folder_of(owner, video_id) is None


def test_a_folder_stops_counting_when_the_material_changes_goal(world):
    owner, _, goal_id, video_id = world
    folder_id = owner.post(f"/api/goals/{goal_id}/folders", data={"name": "Mine"}).json()["folder_id"]
    owner.post(f"/api/goals/{goal_id}/materials/{video_id}/folder", data={"folder_id": folder_id})
    other_goal = owner.post("/api/goals", data={"title": GOAL_TITLE}).status_code  # same title is rejected
    assert other_goal == 409
    # A folder of another goal is refused for this goal's material.
    conn = database.get_db_connection("e2e_test_bot")
    try:
        cursor = conn.cursor()
        cursor.execute("INSERT INTO goals (user_uuid, title, description) VALUES (%s, %s, '') RETURNING id;", (conn.user_uuid, GOAL_TITLE + " B"))
        second = cursor.fetchone()["id"]
        conn.commit()
        try:
            stray = owner.post(f"/api/goals/{second}/folders", data={"name": "Elsewhere"}).json()["folder_id"]
            assert owner.post(f"/api/goals/{goal_id}/materials/{video_id}/folder", data={"folder_id": stray}).status_code == 404
        finally:
            cursor.execute("DELETE FROM goal_folders WHERE goal_id = %s AND user_uuid = %s;", (second, conn.user_uuid))
            cursor.execute("DELETE FROM goals WHERE id = %s AND user_uuid = %s;", (second, conn.user_uuid))
            conn.commit()
    finally:
        conn.close()
