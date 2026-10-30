"""
The Import tab's save actions (videos.js initImportTab) and how saved materials and links look
on a goal card (videos.js renderVideoCard). Runs on the goals_page fixture's dashboard with the
write routes answered by mocks, so nothing reaches the database.
"""
import json

import pytest

from tests.e2e.conftest import GOALS_DASHBOARD


@pytest.fixture
def import_page(logged_in_page):
    page = logged_in_page
    dashboard = json.loads(json.dumps(GOALS_DASHBOARD))
    dashboard["videos"] += [
        {"id": 8200, "title": "Saved lecture", "learning_goal_id": 9001, "status": "saved", "material_type": None,
         "youtube_id": "abc123XYZ_-", "is_watchlist": 0, "importance_rating": 3, "importance_level": 3,
         "url": "", "summary": "", "custom_notes": ""},
        {"id": 8201, "title": "A paper", "learning_goal_id": 9001, "status": "saved", "material_type": "link",
         "source_url": "https://example.com/paper", "youtube_id": None, "is_watchlist": 0, "importance_rating": 3,
         "importance_level": 3, "url": "", "summary": "", "custom_notes": ""},
    ]
    page.route("**/api/dashboard", lambda route: route.fulfill(
        status=200, content_type="application/json", body=json.dumps(dashboard)))
    page.goto("/app")
    page.click("#nav-import")
    return page


def test_link_tab_hides_generate_and_stars_and_saves_the_link(import_page):
    page = import_page
    sent = []
    page.route("**/api/videos/save", lambda route: (
        sent.append(route.request.post_data),
        route.fulfill(status=200, content_type="application/json", body='{"status":"success","video_id":8300}')))
    assert page.locator("#btn-import-generate").is_visible()
    page.click("#import-btn-link")
    assert page.locator("#panel-link").is_visible()
    assert page.locator("#btn-import-generate").is_hidden()
    assert page.locator("#import-importance-block").is_hidden()
    page.fill("#input-link-url", "https://example.com/reading")
    page.fill("#input-link-title", "Reading")
    page.click("[data-import-action='save']")
    page.wait_for_timeout(500)
    assert sent and 'name="link_url"' in sent[0] and "https://example.com/reading" in sent[0]
    assert 'name="is_watchlist"' not in sent[0]


def test_add_to_queue_sends_the_queue_flag(import_page):
    page = import_page
    sent = []
    page.route("**/api/videos/save", lambda route: (
        sent.append(route.request.post_data),
        route.fulfill(status=200, content_type="application/json", body='{"status":"success","video_id":8301}')))
    page.fill("#input-youtube-url", "https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    page.click("[data-import-action='queue']")
    page.wait_for_timeout(500)
    assert sent and 'name="is_watchlist"' in sent[0] and 'name="url"' in sent[0]


def test_saved_material_offers_generate_and_a_link_offers_open(import_page):
    page = import_page
    page.click("#nav-goals")
    # Materials are listed on the goal page, not on the card.
    page.wait_for_selector("[data-goal-card='9001']", state="attached")
    page.click("[data-goal-card='9001'] [data-goal-action='open-goal']")
    page.wait_for_selector("#goal-page #video-card-8200", state="attached")
    saved = page.locator("#video-card-8200")
    assert "Saved" in saved.text_content()
    assert saved.locator("[data-video-action='generate-saved']").is_visible()
    link = page.locator("#video-card-8201")
    assert "Link" in link.text_content() and "example.com" in link.text_content()
    assert link.locator("[data-video-action='open-link']").count() >= 1
    assert link.locator("[data-video-action='generate-saved']").count() == 0
    generated = []
    page.route("**/api/videos/8200/generate", lambda route: (
        generated.append(1),
        route.fulfill(status=200, content_type="application/json", body='{"status":"processing","video_id":8200}')))
    saved.locator("[data-video-action='generate-saved']").click()
    page.wait_for_timeout(400)
    assert generated


def test_link_card_opens_the_studio_with_a_preview_frame_and_notes(import_page):
    page = import_page
    page.route("https://example.com/**", lambda route: route.fulfill(status=200, content_type="text/html", body="<p>page</p>"))
    page.click("#nav-goals")
    page.wait_for_selector("[data-goal-card='9001']", state="attached")
    page.click("[data-goal-card='9001'] [data-goal-action='open-goal']")
    link = page.locator("#goal-page #video-card-8201")
    link.wait_for()
    assert link.locator("[data-video-action='watch-notes']").is_visible()
    link.locator("[data-video-action='watch-notes']").click()
    page.wait_for_selector("#overlay-study-studio:not(.hidden)")
    assert page.locator("#studio-link-wrapper").is_visible()
    assert page.locator("#studio-link-open-btn").get_attribute("href") == "https://example.com/paper"
    assert page.locator("#studio-link-viewer").get_attribute("src") == "https://example.com/paper"
    assert page.locator("#studio-notes-editor").is_visible()
    assert page.locator("#studio-yt-wrapper").is_hidden()


def test_link_field_adds_https_and_the_studio_hides_the_timestamp_button_for_non_video(import_page):
    page = import_page
    page.click("#import-btn-link")
    page.fill("#input-link-url", "example.com/reading")
    page.locator("#input-link-title").click()
    assert page.input_value("#input-link-url") == "https://example.com/reading"
    page.click("#nav-goals")
    page.wait_for_selector("[data-goal-card='9001']", state="attached")
    page.click("[data-goal-card='9001'] [data-goal-action='open-goal']")
    page.locator("#goal-page #video-card-8201 [data-video-action='watch-notes']").click()
    page.wait_for_selector("#overlay-study-studio:not(.hidden)")
    assert page.locator("#btn-studio-timestamp").is_hidden()
    page.evaluate("closeStudyStudio()")
    page.locator("#goal-page #video-card-8200 [data-video-action='watch-notes']").click()
    page.wait_for_selector("#overlay-study-studio:not(.hidden)")
    assert page.locator("#btn-studio-timestamp").is_visible()
