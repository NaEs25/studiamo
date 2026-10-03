"""
The one-time tab tips' stored state (user_profile.tab_tips_seen, routers/settings.py). Reading it
is a pure function, and the route rejects an unknown tab before it opens a database connection,
so nothing here writes to the database.
"""
from app.routers.settings import TAB_TIP_TABS, pending_tab_tips


def test_tips_are_off_until_the_welcome_flow_turns_them_on():
    assert pending_tab_tips(None) == []


def test_turned_on_tips_start_with_every_tab():
    assert pending_tab_tips("") == list(TAB_TIP_TABS)


def test_seen_tabs_drop_out_and_the_rest_keep_their_order():
    assert pending_tab_tips("stats,goals") == ["import", "settings"]
    assert pending_tab_tips(",".join(TAB_TIP_TABS)) == []


def test_an_unknown_tab_is_rejected(client_as, test_username):
    response = client_as(test_username).post("/api/user/onboarding_status", data={"tab_tip_seen": "dashboard"})
    assert response.status_code == 400
