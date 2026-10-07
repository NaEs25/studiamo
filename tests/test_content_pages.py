"""Guide pages: every file under app/content_pages/ parses, is routed, and the renderer
escapes markup and refuses non-site, non-https link targets."""
from fastapi.testclient import TestClient

from app import content_pages
from app.main import app


def test_every_page_is_served():
    # The staging host shows pages ahead of their release date.
    client = TestClient(app, base_url="https://staging.studiamo.cloud")
    assert content_pages.PAGES
    for slug, page in content_pages.PAGES.items():
        res = client.get(f"/{slug}")
        assert res.status_code == 200, slug
        assert page["title"] in res.text


def test_pages_stay_hidden_until_their_release_date():
    from datetime import date, timedelta
    future = {"slug": "x", "published": date.today() + timedelta(days=2)}
    assert not content_pages.is_live(future)
    assert content_pages.is_live(future, preview=True)
    assert content_pages.is_live({"slug": "y", "published": date.today()})


def test_articles_index_lists_every_page():
    res = TestClient(app, base_url="https://staging.studiamo.cloud").get("/articles")
    assert res.status_code == 200
    for slug in content_pages.PAGES:
        assert f'href="/{slug}"' in res.text


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
