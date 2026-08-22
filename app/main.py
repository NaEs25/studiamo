import asyncio
import os
import re
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Request, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse, Response, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app import database, storage, config, schema
from app.dependencies import limiter, get_authenticated_username
from app.telegram_bot import telegram_long_polling, managed_telegram_long_polling, run_scheduler_daemon

# Import Router Modules
from app.routers import auth, dashboard, goals, videos, quizzes, settings, landing_waitlist, bugs, billing

logging.basicConfig(level=logging.INFO)

# httpx logs every request URL at INFO. The Telegram API puts the bot token in the path,
# and the notification loops poll getUpdates continuously, so INFO writes a live credential
# into the system journal a few times a minute, forever. WARNING keeps the failures, which
# are the part worth reading, and drops the successful calls that carry the secret.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

logger = logging.getLogger("studiamo")




@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager: initializes Supabase database and manages background daemons."""
    # Schema sync runs first and is allowed to be loud: every statement in app.schema is
    # additive/idempotent (CREATE TABLE IF NOT EXISTS, ADD COLUMN IF NOT EXISTS), so this
    # should never fail against a database this app is meant to run against. If it does,
    # that's a real problem worth seeing in the logs immediately, not a step to keep
    # swallowing exceptions past like the DB-cleanup and icon-generation steps below, # those are best-effort by nature, this one isn't.
    try:
        schema_conn = database.get_pooled_raw_connection()
        try:
            applied = schema.ensure_schema_up_to_date(schema_conn)
            logger.info(f"[startup] Schema verified up to date ({applied} statements).")
        finally:
            database.release_pooled_connection(schema_conn)
    except Exception as e:
        logger.error(f"[startup] Schema sync FAILED, the app may be running against a stale schema: {e}")

    try:
        raw_conn = database.get_pooled_raw_connection()
        try:
            cursor = raw_conn.cursor()
            cursor.execute("SET LOCAL statement_timeout = 3000;")
            cursor.execute("DELETE FROM videos WHERE is_temporary = 1 AND expires_at IS NOT NULL AND expires_at != '' AND expires_at::timestamptz < NOW();")
            if not getattr(raw_conn, "autocommit", False):
                raw_conn.commit()
            cursor.close()
        finally:
            database.release_pooled_connection(raw_conn)
    except Exception as e:
        print(f"[startup] DB cleanup note: {e}")



    try:
        from app.import_manager import ImportQueueManager
        for username in database.get_all_users():
            database.ensure_user_initialized(username)
            ImportQueueManager.get_instance().recover_pending_tasks(username)
    except Exception as e_recovery:
        print(f"[startup] Task recovery error: {e_recovery}")


    polling_task = asyncio.create_task(telegram_long_polling())
    managed_polling_task = asyncio.create_task(managed_telegram_long_polling())
    scheduler_task = asyncio.create_task(run_scheduler_daemon())
    yield
    polling_task.cancel()
    managed_polling_task.cancel()
    scheduler_task.cancel()
    try:
        from app.import_manager import ImportQueueManager
        ImportQueueManager.get_instance().reset_inflight_tasks_on_shutdown()
    except Exception as e_shutdown:
        logger.warning(f"[shutdown] In-flight task reset error: {e_shutdown}")


app = FastAPI(title="studiamo", lifespan=lifespan)

# Rate limiter setup
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS Middleware Setup
# In cloud mode, a missing YB_ALLOWED_ORIGINS should fail loudly at startup
# rather than silently locking CORS to localhost, that's fail-safe but turns
# a real prod misconfiguration into confusing, hard-to-diagnose browser errors.
_raw_origins = config.require_env_for_cloud("YB_ALLOWED_ORIGINS", default="http://localhost:5004")
ALLOWED_ORIGINS = [o.strip() for o in _raw_origins.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["*"],
)


class NoCacheStaticFiles(StaticFiles):
    """Static file handler ensuring fresh JS/CSS payloads on every client load."""
    async def get_response(self, path: str, scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        return response


# Mount static files folder
STATIC_DIR = Path(__file__).resolve().parent / "static"
STATIC_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/static", NoCacheStaticFiles(directory=STATIC_DIR), name="static")

# Jinja2 environment for the view routes below. Every HTML page renders through here:
# serving a template with read_text() instead meant any {% include %} or {{ ... }} added
# to it later would be emitted verbatim rather than rendered, which is how the focus
# overlay came to never render at all.
TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
templates = Jinja2Templates(directory=TEMPLATES_DIR)
# Global rather than per-render context: every TemplateResponse call gets these without
# each route handler having to remember to pass them.
templates.env.globals["umami_website_id"] = config.UMAMI_WEBSITE_ID
templates.env.globals["umami_script_url"] = config.UMAMI_SCRIPT_URL


# Register Feature Routers
app.include_router(auth.router)
app.include_router(dashboard.router)
app.include_router(goals.router)
app.include_router(videos.router)
app.include_router(quizzes.router)
app.include_router(settings.router)
app.include_router(bugs.router)
app.include_router(billing.router)
app.include_router(landing_waitlist.router)

# Mount internal admin panel if available in karl-privat
_admin_panel_dir = Path(__file__).resolve().parent.parent / "karl-privat" / "admin-panel"
if (_admin_panel_dir / "router.py").exists():
    try:
        import sys
        _admin_dir_str = str(_admin_panel_dir)
        if _admin_dir_str not in sys.path:
            sys.path.insert(0, _admin_dir_str)
        import router as _admin_router_mod
        app.include_router(_admin_router_mod.router)
        _admin_static = _admin_panel_dir / "static"
        if _admin_static.exists():
            app.mount("/admin/static", NoCacheStaticFiles(directory=_admin_static), name="admin_static")
    except Exception as _e_admin:
        logger.warning(f"Could not load internal admin panel: {_e_admin}")




@app.get("/api/config")
async def get_system_config():
    """Returns application runtime mode and configuration settings."""
    return {
        "app_mode": config.APP_MODE,
        "is_cloud": config.IS_CLOUD,
        "is_selfhosted": config.IS_SELFHOSTED,
        "max_selfhosted_users": config.MAX_SELFHOSTED_USERS,
    }


@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    fav_ico = STATIC_DIR / "images" / "favicon.ico"
    if fav_ico.exists():
        return FileResponse(fav_ico)
    svg_icon = STATIC_DIR / "images" / "notes-icon.svg"
    if svg_icon.exists():
        return FileResponse(svg_icon, media_type="image/svg+xml")
    return Response(status_code=204)


@app.get("/manifest.json", include_in_schema=False)
async def serve_manifest():
    manifest_path = STATIC_DIR / "manifest.json"
    if manifest_path.exists():
        return FileResponse(manifest_path, media_type="application/manifest+json")
    raise HTTPException(status_code=404, detail="Manifest not found")


@app.get("/sw.js", include_in_schema=False)
async def serve_sw():
    sw_path = STATIC_DIR / "sw.js"
    if sw_path.exists():
        return FileResponse(
            sw_path,
            media_type="application/javascript",
            headers={"Service-Worker-Allowed": "/", "Cache-Control": "no-cache"}
        )
    raise HTTPException(status_code=404, detail="Service worker not found")


@app.get("/robots.txt", include_in_schema=False)
async def serve_robots():
    robots_path = STATIC_DIR / "robots.txt"
    if robots_path.exists():
        return FileResponse(robots_path, media_type="text/plain")
    raise HTTPException(status_code=404, detail="robots.txt not found")


@app.get("/sitemap.xml", include_in_schema=False)
async def serve_sitemap():
    sitemap_path = STATIC_DIR / "sitemap.xml"
    if sitemap_path.exists():
        return FileResponse(sitemap_path, media_type="application/xml")
    raise HTTPException(status_code=404, detail="sitemap.xml not found")


@app.get("/llms.txt", include_in_schema=False)
async def serve_llms_txt():
    llms_path = STATIC_DIR / "llms.txt"
    if llms_path.exists():
        return FileResponse(llms_path, media_type="text/plain; charset=utf-8")
    raise HTTPException(status_code=404, detail="llms.txt not found")


@app.get("/llms-full.txt", include_in_schema=False)
async def serve_llms_full_txt():
    llms_full_path = STATIC_DIR / "llms-full.txt"
    if llms_full_path.exists():
        return FileResponse(llms_full_path, media_type="text/plain; charset=utf-8")
    raise HTTPException(status_code=404, detail="llms-full.txt not found")





# --- HTML Template View Routes ---

@app.get("/", response_class=HTMLResponse)
async def serve_root(request: Request):
    """Serves index dashboard for authenticated users, landing page for guests in cloud mode, or redirects to /login in selfhosted mode."""
    auth_user = get_authenticated_username(request)
    if not auth_user and config.IS_SELFHOSTED:
        return RedirectResponse(url="/login", status_code=303)
    template_name = "index.html" if auth_user else "landing.html"
    template_path = Path(__file__).resolve().parent / "templates" / template_name
    if not template_path.exists():
        raise HTTPException(status_code=404, detail="HTML template not found")
    return templates.TemplateResponse(template_name, {"request": request})


@app.get("/landing")
async def serve_landing():
    return RedirectResponse(url="/", status_code=301)


@app.get("/login", response_class=HTMLResponse)
async def serve_login(request: Request):
    if config.IS_CLOUD:
        template_name = "login_cloud.html"
    else:
        template_name = "login_selfhosted.html"

    template_path = Path(__file__).resolve().parent / "templates" / template_name
    if not template_path.exists():
        template_name = "login.html"
        template_path = Path(__file__).resolve().parent / "templates" / template_name
    if not template_path.exists():
        raise HTTPException(status_code=404, detail="Login HTML template not found")
    return templates.TemplateResponse(template_name, {"request": request})


@app.get("/waitlist-confirmation", response_class=HTMLResponse)
async def serve_waitlist_confirmation(request: Request):
    template_path = Path(__file__).resolve().parent / "templates" / "waitlist_confirmation.html"
    if not template_path.exists():
        raise HTTPException(status_code=404, detail="Waitlist confirmation template not found")
    return templates.TemplateResponse("waitlist_confirmation.html", {"request": request})


@app.get("/join")
async def serve_join(ref: Optional[str] = None, src: Optional[str] = None):
    """Referral entry point (/join?ref=<code>): stashes the referral code in a
    short-lived cookie, then hands off to the normal login page. google_login
    reads this cookie and folds the code into the OAuth state so it survives
    the redirect round-trip to Google and back.

    The redirect target carries utm_* parameters because this route renders no
    HTML of its own: without them a click on a shared referral link leaves no
    trace in analytics, only the signups that completed. static/js/referral_click.js
    turns the tag into an event on the login page. 'src' marks where the link
    was shared from (the confirmation email sets src=email, a link the person
    copied and pasted themselves carries nothing)."""
    ref_clean = (ref or "").strip()
    valid_ref = bool(re.fullmatch(r"[a-f0-9]{12}", ref_clean))
    shared_via = "email" if (src or "").strip().lower() == "email" else ("link" if valid_ref else "broken-link")

    response = RedirectResponse(
        url=f"/login?utm_source=referral&utm_medium=waitlist&utm_content={shared_via}",
        status_code=303,
    )
    if valid_ref:
        response.set_cookie(key="ref_code", value=ref_clean, httponly=True, samesite="lax", secure=config.IS_CLOUD, max_age=86400, path="/")
    return response


@app.get("/app", response_class=HTMLResponse)
async def serve_app(request: Request):
    auth_user = get_authenticated_username(request)
    if auth_user:
        template_path = Path(__file__).resolve().parent / "templates" / "index.html"
        if template_path.exists():
            return templates.TemplateResponse("index.html", {"request": request})
    return RedirectResponse(url="/login", status_code=307)


@app.get("/impressum", response_class=HTMLResponse)
async def serve_impressum(request: Request):
    template_path = Path(__file__).resolve().parent / "templates" / "impressum.html"
    if not template_path.exists():
        raise HTTPException(status_code=404, detail="Impressum HTML template not found")
    return templates.TemplateResponse("impressum.html", {"request": request, "current_page": "impressum"})


@app.get("/imprint")
@app.get("/legal")
async def redirect_impressum():
    return RedirectResponse(url="/impressum", status_code=301)


@app.get("/privacy", response_class=HTMLResponse)
async def serve_privacy(request: Request):
    template_path = Path(__file__).resolve().parent / "templates" / "privacy.html"
    if not template_path.exists():
        raise HTTPException(status_code=404, detail="Privacy HTML template not found")
    return templates.TemplateResponse("privacy.html", {"request": request, "current_page": "privacy"})


@app.get("/privacy-policy")
async def redirect_privacy():
    return RedirectResponse(url="/privacy", status_code=301)


@app.get("/terms", response_class=HTMLResponse)
async def serve_terms(request: Request):
    template_path = Path(__file__).resolve().parent / "templates" / "terms.html"
    if not template_path.exists():
        raise HTTPException(status_code=404, detail="Terms HTML template not found")
    return templates.TemplateResponse("terms.html", {"request": request, "current_page": "terms"})


@app.get("/tos")
@app.get("/terms-of-service")
async def redirect_terms():
    return RedirectResponse(url="/terms", status_code=301)


@app.get("/science", response_class=HTMLResponse)
async def serve_science(request: Request):
    template_path = Path(__file__).resolve().parent / "templates" / "science.html"
    if not template_path.exists():
        raise HTTPException(status_code=404, detail="Science HTML template not found")
    return templates.TemplateResponse("science.html", {"request": request, "current_page": "science"})


@app.get("/research")
async def redirect_science():
    return RedirectResponse(url="/science", status_code=301)






@app.get("/auth/google")
async def root_google_login(request: Request, redirect: Optional[str] = None,
                            require_existing: bool = False, link: bool = False):
    """Unprefixed alias for the router's /api/auth/google.

    The query parameters have to be declared and forwarded explicitly: this is a separate
    FastAPI endpoint, so anything it does not name is dropped before google_login ever sees
    it. `link` in particular decides whether the callback may rebind an account's Google
    identity, and silently losing it here would make the Settings button a no-op."""
    from app.routers.auth import google_login
    return await google_login(request, redirect=redirect, require_existing=require_existing, link=link)


@app.get("/auth/google/callback")
async def root_google_callback(request: Request, background_tasks: BackgroundTasks, code: Optional[str] = None, error: Optional[str] = None, state: Optional[str] = None):
    from app.routers.auth import google_callback
    return await google_callback(request, background_tasks, code, error, state)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=5004, reload=True)
