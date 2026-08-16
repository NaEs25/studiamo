"""
User-facing bug tracker: the "Bugs" pill in the app header links here.

Reports live in the `bugs` table (same Postgres database as everything else),
not in a JSON file. The file-backed version stored them in dev/bugs.json,
which the running server rewrote on every submission, a git-tracked file
being written at runtime meant a bug report filed on prod left the worktree
dirty and aborted the next `git merge` in scripts/deploy.sh.

Routes keep their historical /dev/bugs and /api/dev/bugs paths so existing
links and bookmarks stay valid, even though this is no longer dev-only code.
"""
import os
import uuid
import json
import hmac
import hashlib
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Request, Form, HTTPException, Depends
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from psycopg2.extras import RealDictCursor

from app import config, database
from app.dependencies import (
    limiter,
    get_authenticated_username,
    make_admin_token,
    is_bugs_admin,
    require_admin_auth,
    ADMIN_COOKIE_NAME,
)

router = APIRouter(tags=["Bugs"])

BUGS_TEMPLATE_PATH = Path(__file__).resolve().parent.parent / "templates" / "bugs.html"
templates = Jinja2Templates(directory=BUGS_TEMPLATE_PATH.parent)


def _row_to_bug(row, include_admin_fields: bool) -> dict:
    """Shapes a `bugs` row into the JSON the frontend expects (it reads bug.user).

    Username and captured diagnostic context are only exposed to admins, the
    public board shows area/description/status/date to everyone so people can
    check for duplicates before filing, nothing that identifies a reporter."""
    created = row["created_at"]
    bug = {
        "id": row["id"],
        "area": row["area"],
        "description": row["description"],
        "status": row["status"],
        "is_anonymous": bool(row["is_anonymous"]),
        "created_at": created.isoformat() if hasattr(created, "isoformat") else str(created),
    }
    if include_admin_fields:
        bug["user"] = row["username"]
        bug["context"] = row["context"] or {}
    return bug


@router.get("/dev/bugs", response_class=HTMLResponse)
async def serve_bugs_page(request: Request):
    """Serves the standalone Bug Tracker HTML page."""
    if not config.IS_CLOUD:
        raise HTTPException(status_code=404, detail="Bug tracker is only available in cloud mode.")
    if not BUGS_TEMPLATE_PATH.exists():
        raise HTTPException(status_code=404, detail="bugs.html template not found")
    entry_referer = request.headers.get("referer", "")
    return templates.TemplateResponse("bugs.html", {"request": request, "entry_referer": entry_referer})


@router.get("/api/dev/bugs/me")
async def get_current_user_status(request: Request):
    """Returns current user session info and auth capability status.

    Deliberately trusts only the signed yb_session cookie (get_authenticated_username),
    never the x-username header or username cookie: both are client-supplied and
    unverified (core.js's fetchAPI sends x-username on every request from a plain
    localStorage value), so honoring them here would let anyone attribute a bug report
    to any existing username just by setting that value in devtools."""
    active_user = get_authenticated_username(request)

    google_enabled = bool(os.getenv("GOOGLE_CLIENT_ID")) or config.IS_CLOUD

    return JSONResponse({
        "logged_in": bool(active_user),
        "username": active_user,
        "google_enabled": google_enabled
    })


@router.get("/api/dev/bugs")
async def get_bugs(request: Request):
    """Returns all reported bugs sorted by newest first.

    Public endpoint by design (the board is meant to be browsable by everyone
    so people can check for duplicates), but usernames and captured context
    are stripped out unless the request carries a valid admin cookie."""
    admin = is_bugs_admin(request)
    conn = None
    try:
        conn = database.get_pooled_raw_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT * FROM bugs ORDER BY created_at DESC;")
        bugs = [_row_to_bug(r, admin) for r in cursor.fetchall()]
        cursor.close()
        return JSONResponse(bugs)
    finally:
        if conn is not None:
            database.release_pooled_connection(conn)


@router.get("/api/dev/bugs/admin/status")
async def get_admin_status(request: Request):
    """Tells the frontend whether this browser is currently logged in as admin."""
    return JSONResponse({"is_admin": is_bugs_admin(request)})


@router.post("/api/dev/bugs/admin/login")
@limiter.limit("10/minute")  # Single shared password, no lockout -- cap guesses per IP per minute.
async def admin_login(request: Request, password: str = Form(...)):
    """Checks the shared admin password (set via scripts/set_admin_bug_password.py)
    and, on success, sets the signed bugs_admin cookie."""
    expected_hash = database.get_app_setting("admin_bug_password_hash")
    if not expected_hash:
        raise HTTPException(status_code=503, detail="Admin password has not been configured yet.")

    submitted_hash = hashlib.sha256(password.encode("utf-8")).hexdigest()
    if not hmac.compare_digest(submitted_hash, expected_hash):
        raise HTTPException(status_code=401, detail="Incorrect admin password.")

    response = JSONResponse({"status": "success"})
    response.set_cookie(
        key=ADMIN_COOKIE_NAME,
        value=make_admin_token(),
        httponly=True,
        samesite="lax",
        max_age=31536000,
        path="/",
    )
    return response


@router.post("/api/dev/bugs/admin/logout")
async def admin_logout():
    """Clears the bugs_admin cookie."""
    response = JSONResponse({"status": "success"})
    response.delete_cookie(key=ADMIN_COOKIE_NAME, path="/")
    return response


@router.post("/api/dev/bugs")
@limiter.limit("10/minute")  # Prevent bot spam: cap reports per IP per minute.
async def create_bug(
    request: Request,
    area: Optional[str] = Form("General / Other"),
    description: str = Form(...),
    is_anonymous: Optional[bool] = Form(False),
    include_context: Optional[bool] = Form(True),
    viewport: Optional[str] = Form(None),
    online: Optional[bool] = Form(None),
    entry_referer: Optional[str] = Form(None),
    active_tab: Optional[str] = Form(None),
    connection_type: Optional[str] = Form(None),
):
    """Submits a new bug report. Requires an active session -- sign in with Google first
    (there is no username/password fallback: no cloud account has a password to check
    against, so that path used to let anyone attribute a report to any existing username)."""
    target_user = get_authenticated_username(request)
    if not target_user:
        raise HTTPException(status_code=400, detail="Please sign in with Google to submit a report.")

    sanitized_user = "".join(c for c in target_user if c.isalnum() or c in ("-", "_")).strip()
    if not sanitized_user:
        raise HTTPException(status_code=400, detail="Invalid username.")

    clean_desc = description.strip()
    if not clean_desc:
        raise HTTPException(status_code=400, detail="Bug description cannot be empty.")

    def _truthy(val) -> bool:
        return val if isinstance(val, bool) else str(val).lower() in ("true", "1", "on", "yes")

    anon_flag = _truthy(is_anonymous)

    # git_commit is the same for every report filed against this deployment -- it carries no
    # information about the reporter, so unlike everything below it isn't gated behind the
    # "Include diagnostic info" toggle.
    context = {"git_commit": config.GIT_COMMIT_HASH}

    # Ambient triage context only -- user-agent and referer come from headers the browser
    # sends on every request regardless; viewport/online/connection_type are read client-side
    # with no permission prompt. Never geolocation or IP-derived data. Skipped entirely (not
    # just hidden later) when the reporter opts out via the "Include diagnostic info" toggle.
    if _truthy(include_context):
        context.update({
            "user_agent": request.headers.get("user-agent", ""),
            # entry_referer is captured on the earlier GET /dev/bugs page load, when Referer
            # still named the page the Bugs button was pressed on; this POST's own Referer
            # would just say "/dev/bugs" every time, since that's where the browser already is.
            "referer": entry_referer or request.headers.get("referer", ""),
            # app.js's switchTab() writes this to localStorage on every top-level tab change
            # (dashboard/goals/stats/settings/etc) -- the closest thing to "what were they
            # doing" the SPA exposes, since it has no URL-based view routing to read instead.
            "active_tab": active_tab or "",
            "viewport": viewport or "",
            "online": _truthy(online) if online is not None else None,
            "connection_type": connection_type or "",
        })

    new_bug = {
        "id": f"bug_{int(datetime.now(timezone.utc).timestamp())}_{uuid.uuid4().hex[:6]}",
        "user": sanitized_user,
        "area": area or "General / Other",
        "description": clean_desc,
        "status": "open",
        "is_anonymous": anon_flag,
        "context": context,
        "created_at": datetime.now(timezone.utc).isoformat()
    }

    conn = None
    try:
        conn = database.get_pooled_raw_connection()
        cursor = conn.cursor()
        cursor.execute(
            """INSERT INTO bugs (id, username, area, description, status, is_anonymous, context, created_at)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s);""",
            (new_bug["id"], new_bug["user"], new_bug["area"], new_bug["description"],
             new_bug["status"], new_bug["is_anonymous"], json.dumps(new_bug["context"]), new_bug["created_at"])
        )
        conn.commit()
        cursor.close()
    finally:
        if conn is not None:
            database.release_pooled_connection(conn)

    res_content = {"status": "success", "bug": new_bug, "username": sanitized_user}
    return JSONResponse(res_content)


@router.patch("/api/dev/bugs/{bug_id}")
async def update_bug_status(bug_id: str, status: str = Form(...), _admin: None = Depends(require_admin_auth)):
    """Updates status ('open' or 'resolved') of a reported bug. Admin-only."""
    if status not in ("open", "resolved", "in_progress"):
        raise HTTPException(status_code=400, detail="Invalid status.")

    conn = None
    try:
        conn = database.get_pooled_raw_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE bugs SET status = %s WHERE id = %s;", (status, bug_id))
        updated = cursor.rowcount
        conn.commit()
        cursor.close()
    finally:
        if conn is not None:
            database.release_pooled_connection(conn)

    if not updated:
        raise HTTPException(status_code=404, detail="Bug report not found.")

    return JSONResponse({"status": "success", "bug_id": bug_id, "new_status": status})


@router.delete("/api/dev/bugs/{bug_id}")
async def delete_bug(bug_id: str, _admin: None = Depends(require_admin_auth)):
    """Deletes a bug report. Admin-only."""
    conn = None
    try:
        conn = database.get_pooled_raw_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM bugs WHERE id = %s;", (bug_id,))
        deleted = cursor.rowcount
        conn.commit()
        cursor.close()
    finally:
        if conn is not None:
            database.release_pooled_connection(conn)

    if not deleted:
        raise HTTPException(status_code=404, detail="Bug report not found.")

    return JSONResponse({"status": "success", "deleted_id": bug_id})
