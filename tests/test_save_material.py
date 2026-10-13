"""
Saving material without AI (POST /api/videos/save) and generating from it later.

Runs as the dedicated test account and removes every row it creates. Nothing reaches Gemini or
YouTube: only links and pasted notes are saved, and generating is checked on the cases that are
refused before an import would start.
"""
import pytest


@pytest.fixture
def client(client_as, test_username):
    return client_as(test_username)


@pytest.fixture
def cleanup(client):
    ids = []
    yield ids
    for video_id in ids:
        client.delete(f"/api/videos/{video_id}")


def test_link_is_saved_with_no_quiz_and_no_ai(client, cleanup):
    response = client.post("/api/videos/save", data={"link_url": "https://example.com/paper?id=1", "title": "A paper"})
    assert response.status_code == 200
    video_id = response.json()["video_id"]
    cleanup.append(video_id)
    card = next(v for v in client.get("/api/dashboard").json()["videos"] if v["id"] == video_id)
    assert card["status"] == "saved" and card["material_type"] == "link"
    assert card["source_url"] == "https://example.com/paper?id=1" and card["title"] == "A paper"
    assert not [q for q in client.get("/api/dashboard").json()["quizzes"] if q["video_id"] == video_id]


def test_saving_the_same_link_twice_returns_the_first(client, cleanup):
    first = client.post("/api/videos/save", data={"link_url": "https://example.com/same"}).json()
    cleanup.append(first["video_id"])
    again = client.post("/api/videos/save", data={"link_url": "https://example.com/same"}).json()
    assert again["video_id"] == first["video_id"] and again["already_existed"] is True


@pytest.mark.parametrize("bad", ["javascript:alert(1)", "data:text/html,x", "ftp://example.com/f", "http://", "not a url", "vbscript:x"])
def test_link_must_be_a_full_http_or_https_address(client, bad):
    assert client.post("/api/videos/save", data={"link_url": bad}).status_code == 400


def test_exactly_one_kind_of_material_is_required(client):
    assert client.post("/api/videos/save", data={}).status_code == 400
    both = {"link_url": "https://example.com/x", "text_content": "some notes"}
    assert client.post("/api/videos/save", data=both).status_code == 400


def test_material_cannot_be_saved_into_another_accounts_goal(client):
    response = client.post("/api/videos/save", data={"link_url": "https://example.com/g", "learning_goal_id": 2147483000})
    assert response.status_code == 404


def test_notes_are_saved_and_a_link_never_generates(client, cleanup):
    notes = client.post("/api/videos/save", data={"text_content": "Study notes about saving material.", "title": "My notes"})
    assert notes.status_code == 200
    cleanup.append(notes.json()["video_id"])
    link = client.post("/api/videos/save", data={"link_url": "https://example.com/nogen"}).json()
    cleanup.append(link["video_id"])
    refused = client.post(f"/api/videos/{link['video_id']}/generate")
    assert refused.status_code == 400
    assert client.post("/api/videos/2147483000/generate").status_code == 404


def test_material_order_is_stored_and_refuses_a_list_that_does_not_match(client, cleanup):
    goal = client.post("/api/goals", data={"title": "Order test goal"}).json()["goal_id"]
    try:
        ids = []
        for n in range(3):
            saved = client.post("/api/videos/save", data={"link_url": f"https://example.com/order{n}", "learning_goal_id": goal}).json()
            cleanup.append(saved["video_id"])
            ids.append(saved["video_id"])
        wanted = [ids[2], ids[0], ids[1]]
        assert client.post(f"/api/goals/{goal}/materials/order", data={"ids": ",".join(map(str, wanted))}).status_code == 200
        videos = [v["id"] for v in client.get("/api/dashboard").json()["videos"] if v["learning_goal_id"] == goal]
        assert videos == wanted
        # Missing one, repeating one, or naming a row that is not in the goal are all refused.
        assert client.post(f"/api/goals/{goal}/materials/order", data={"ids": f"{ids[0]},{ids[1]}"}).status_code == 409
        assert client.post(f"/api/goals/{goal}/materials/order", data={"ids": f"{ids[0]},{ids[0]},{ids[1]}"}).status_code == 400
        assert client.post(f"/api/goals/{goal}/materials/order", data={"ids": ",".join(map(str, ids)) + ",2147483000"}).status_code == 409
        assert client.post("/api/goals/2147483000/materials/order", data={"ids": "1"}).status_code == 404
    finally:
        client.delete(f"/api/goals/{goal}?delete_materials=true")


def test_a_bare_domain_gets_https(client, cleanup):
    saved = client.post("/api/videos/save", data={"link_url": "  www.example.com/page "}).json()
    cleanup.append(saved["video_id"])
    card = next(v for v in client.get("/api/dashboard").json()["videos"] if v["id"] == saved["video_id"])
    assert card["source_url"] == "https://www.example.com/page"
