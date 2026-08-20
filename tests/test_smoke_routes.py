"""
Crawls every registered route once and asserts it never 500s.

This is a smoke-test net, not a correctness suite: it proves each route can
be reached without crashing, not that its business logic is right. That's a
deliberately cheap bar, chosen because it's exactly the bar today's real
bugs failed to clear : a missing `import os` in the bug tracker, and a
`SELECT` against a column that doesn't exist, both 500'd on every single
call and neither was caught by anything before a human happened to look at
the logs. One test per route that just checks "did it crash" would have
caught both immediately.

This suite runs against the live shared Supabase database (see conftest.py)
and is written under that constraint, not despite it:

  - GET routes are just fetched. None of them mutate state by design (if one
    does, that's a separate bug).
  - Routes gated by get_active_username/get_authenticated_username are called
    with NO session cookie. FastAPI resolves that dependency, sees no valid
    session, and raises 401 before the endpoint body ever runs , so these
    calls never reach a DB write, no matter what the route does once
    authenticated.
  - Public (unauthenticated) mutating routes are only called where the
    handler's own required Form/JSON fields make an empty body 422 at
    FastAPI's validation layer, before the function body runs. Verified by
    reading each one (see PUBLIC_MUTATING_SAFE below) , not assumed.
  - DELETE /api/dev/bugs/{bug_id} is the one public mutating route actually
    exercised end-to-end: called with an id that cannot exist, so it performs
    a real but no-op DELETE (0 rows affected) and returns 404. Chosen
    deliberately, the same way the bug-tracker migration was manually
    verified earlier tonight.
  - POST /webhooks/lemonsqueezy is excluded outright : untested billing/
    payment code, out of scope for a smoke pass tonight.

When a dedicated test database is configured, real authenticated end-to-end tests
(create a goal, import a video, delete it) can be added on top of this file.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

# path param name -> a value satisfying its route converter (int routes need a
# number; str/default routes accept anything). Not a real id in either case.
DUMMY_PATH_VALUES = {
    "int": "999999999",
    "str": "smoketest-nonexistent",
    "path": "smoketest-nonexistent",
}

# Public POST/PATCH/DELETE routes and why an empty/dummy call is safe.
# Verified by reading each handler, not assumed : see the module docstring.
PUBLIC_MUTATING_SAFE = {
    ("POST", "/api/dev/bugs"): "description: str = Form(...) -> 422 on empty body, handler never runs",
    ("PATCH", "/api/dev/bugs/{bug_id}"): "status: str = Form(...) -> 422 on empty body, handler never runs",
    ("DELETE", "/api/dev/bugs/{bug_id}"): "no required body; called with a nonexistent id -> real but no-op DELETE, 404",
    ("POST", "/api/dev/bugs/admin/login"): "token: str = Form(...) -> 422 on empty body",
    ("POST", "/api/dev/bugs/admin/logout"): "clears admin cookie, no DB mutation",
    ("POST", "/api/users"): "username/gemini_api_key/password all Form(...) -> 422 on empty body",
    ("POST", "/api/users/verify"): "username: str = Form(...) -> 422 on empty body",
    ("POST", "/api/users/logout"): "clears a cookie, no DB access",
    ("POST", "/api/waitlist"): "body is a required pydantic model -> 422 on empty/missing JSON body",
}

# Routes deliberately not exercised via HTTP tonight. Each still gets
# imported (its router module loads at app startup either way), so an
# import-time bug like today's missing `import os` is still caught , this
# list only opts out of the HTTP call itself.
EXCLUDED = {
    ("POST", "/webhooks/lemonsqueezy"),  # untested payment webhook, out of scope tonight
}


# The internal admin panel lives in karl-privat/, which is gitignored, and main.py mounts it
# only when that directory is present. Its routes therefore exist on a maintainer's machine and
# nowhere else: not in a clean checkout, not in CI, not in any deployment built from this
# repository. This suite cannot vouch for code it cannot see, and failing on a machine where
# the panel happens to be checked out would make the whole file environment-dependent, so those
# routes are skipped rather than declared safe.
ADMIN_PREFIX = "/admin"


def _iter_routes():
    from app.main import app
    for route in app.routes:
        if getattr(route, "path", "").startswith(ADMIN_PREFIX):
            continue
        methods = getattr(route, "methods", None)
        if not methods:
            continue
        param_convertors = getattr(route, "param_convertors", {}) or {}
        for method in sorted(methods - {"HEAD", "OPTIONS"}):
            yield route, method, param_convertors


def _concrete_path(route, param_convertors) -> str:
    path = route.path
    for name, convertor in param_convertors.items():
        kind = type(convertor).__name__.replace("Convertor", "").lower()
        value = DUMMY_PATH_VALUES.get(kind, DUMMY_PATH_VALUES["str"])
        path = path.replace("{" + name + "}", value)
    return path


def _requires_auth(route) -> bool:
    dependant = getattr(route, "dependant", None)
    if not dependant:
        return False
    for dep in dependant.dependencies:
        name = getattr(dep.call, "__name__", "")
        # require_app_access (the paid-access gate) calls get_active_username as its
        # own first step, so an unauthenticated request still 401s before it ever
        # reaches the payment check , safe to treat the same as the other two.
        if "active_username" in name or "authenticated_username" in name or name == "require_app_access":
            return True
    return False


def _collect_cases():
    cases = []
    for route, method, param_convertors in _iter_routes():
        path = _concrete_path(route, param_convertors)
        key = (method, route.path)
        if key in EXCLUDED:
            continue
        needs_auth = _requires_auth(route)
        if method == "GET" or needs_auth or key in PUBLIC_MUTATING_SAFE:
            cases.append(pytest.param(method, path, needs_auth, id=f"{method} {route.path}"))
        # else: a public mutating route we haven't reasoned about , fails loudly below
        # rather than being silently skipped, so new routes can't slip past this suite.
    return cases


CASES = _collect_cases()


def test_smoke_suite_found_routes():
    """Guards against the crawl itself silently finding nothing (e.g. app failed to import)."""
    assert len(CASES) > 50, f"expected 50+ routes, found {len(CASES)} : did app.main fail to build routes?"


def test_every_public_mutating_route_is_accounted_for():
    """Any POST/PATCH/DELETE route that is neither auth-gated nor in
    PUBLIC_MUTATING_SAFE nor EXCLUDED must fail here, not be silently skipped, a new public mutating route needs a human to decide how it's safe to test."""
    from app.main import app
    unaccounted = []
    for route, method, _ in _iter_routes():
        if method == "GET":
            continue
        key = (method, route.path)
        if key in EXCLUDED or key in PUBLIC_MUTATING_SAFE:
            continue
        if _requires_auth(route):
            continue
        unaccounted.append(key)
    assert not unaccounted, (
        f"new public mutating route(s) not covered by PUBLIC_MUTATING_SAFE or EXCLUDED: {unaccounted} "
        ": add it to one with a comment justifying why calling it is safe, or to EXCLUDED with why it isn't tested yet."
    )


@pytest.mark.parametrize("method, path, needs_auth", CASES)
def test_route_does_not_500(client, method, path, needs_auth):
    response = client.request(method, path)
    assert response.status_code < 500, (
        f"{method} {path} -> {response.status_code}: {response.text[:300]}"
    )
    if needs_auth:
        assert response.status_code in (401, 403), (
            f"{method} {path} requires auth but returned {response.status_code} unauthenticated, "
            f"expected 401/403: {response.text[:300]}"
        )
