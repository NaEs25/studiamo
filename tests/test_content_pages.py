"""Guide pages: every file under app/content_pages/ parses, is routed, and the renderer
escapes markup and refuses non-site, non-https link targets."""
from fastapi.testclient import TestClient

from app import content_pages
from app.main import app


def test_every_page_is_served():
    client = TestClient(app)
    assert content_pages.PAGES
    for slug, page in content_pages.PAGES.items():
        res = client.get(f"/{slug}")
        assert res.status_code == 200, slug
        assert page["title"] in res.text


def test_renderer_escapes_and_limits_links():
    out = content_pages.render_body("<script>x</script> [a](javascript:alert(1)) [b](/science)")
    assert "<script>" not in out
    assert 'href="javascript' not in out
    assert '<a href="/science">b</a>' in out


def test_root_redirects_signed_in_users_but_landing_does_not(client_as, test_username, make_client):
    """/ sends a signed-in user to /app, keeping the query string; /landing stays the landing
    page for them. Guests see the landing page on both."""
    me = client_as(test_username)
    res = me.get("/?google_linked=true")
    assert res.status_code == 303
    assert res.headers["location"] == "/app?google_linked=true"
    assert me.get("/landing").status_code == 200

    guest = make_client(follow_redirects=False)
    assert guest.get("/").status_code == 200
    assert guest.get("/landing").status_code == 200
