"""
End-to-end coverage for creating and deleting a Learning Goal through the real UI, the
one flow in this file that actually writes data. Runs only against E2E_TEST_USERNAME
(see conftest.py) and deletes what it creates in the same test, so it leaves no residue
in the shared staging database.
"""
import uuid


def test_create_and_delete_goal(logged_in_page):
    page = logged_in_page
    goal_title = f"E2E Test Goal {uuid.uuid4().hex[:8]}"

    page.goto("/app")
    page.click("#nav-goals")
    page.click("#btn-add-goal-modal")
    page.wait_for_selector("#goal-modal-title", state="visible", timeout=10000)
    page.fill("#goal-modal-title", goal_title)

    # The goal list re-renders from the create response, so wait for that round trip
    # (Supabase is a remote DB; a plain UI poll can be faster than the request itself)
    # before looking for the new card.
    with page.expect_response(lambda r: r.url.endswith("/api/goals") and r.request.method == "POST", timeout=30000):
        page.click("#goal-modal-form button[type=submit]")

    goal_heading = page.get_by_role("heading", name=goal_title)
    goal_heading.wait_for(timeout=15000)
    assert goal_heading.is_visible()

    goal_card = goal_heading.locator("xpath=ancestor::*[.//button[starts-with(@id, 'btn-goal-menu-')]][1]")
    goal_card.locator("[id^='btn-goal-menu-']").click()
    page.locator("#portal-goal-menu").get_by_text("Permanently Delete", exact=False).click()

    with page.expect_response(lambda r: "/api/goals/" in r.url and r.request.method == "DELETE", timeout=20000):
        page.get_by_text("Delete Goal & All Linked Materials", exact=False).click()

    goal_heading.wait_for(state="detached", timeout=15000)
