import os
import re
import random
import uuid
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import quote

import httpx
import psycopg2
from fastapi import APIRouter, Request, Form, HTTPException, Depends, BackgroundTasks
from fastapi.responses import JSONResponse, RedirectResponse

from app import config, database, moderation
from app.dependencies import (
    limiter,
    _make_session_token,
    _decode_session_token,
    _sign_oauth_state,
    _decode_oauth_state,
    get_active_username,
    require_local_auth_enabled,
    hash_password,
    verify_password,
)

router = APIRouter(prefix="/api", tags=["Auth & Users"])

# Matches app.database.generate_referral_code()'s output (secrets.token_hex(6)).
_REF_CODE_PATTERN = re.compile(r"^[a-f0-9]{12}$")


@router.get("/waitlist-status")
@limiter.limit("30/minute")
async def get_waitlist_status(request: Request, ref: str = ""):
    """Public, unauthenticated: returns referral progress for a referral code.
    Powers /waitlist-confirmation, which has no session to read (waitlist
    accounts never get one, see google_callback). Deliberately returns only
    a referral count, never username/email/queue position."""
    ref_clean = (ref or "").strip()
    if not _REF_CODE_PATTERN.match(ref_clean):
        raise HTTPException(status_code=400, detail="Invalid referral code.")
    info = database.find_user_by_referral_code(ref_clean)
    if not info:
        raise HTTPException(status_code=404, detail="Referral code not found.")
    return {
        "referral_code": ref_clean,
        "referral_count": min(info["referral_count"], 5),
    }


@router.get("/auth/capacity")
async def get_auth_capacity():
    """Public: whether new signups are currently landing on the waitlist. Powers the login page banner."""
    return {"at_capacity": database.is_at_capacity()}


@router.get("/users")
@limiter.limit("20/minute")
async def get_users(
    request: Request,
    q: Optional[str] = None,
    _local_auth: None = Depends(require_local_auth_enabled),
):
    """Returns user profiles from Supabase database. If query `q` is provided, filters profiles by prefix match (max 3 results).
    Only reachable in self-hosted mode, where the login page's profile picker needs it before the user is authenticated, cloud mode has no local-login picker and blocks this to avoid leaking Google-SSO-derived usernames/emails."""
    matches = database.get_all_users()

    if q and q.strip():
        query = q.strip().lower()
        filtered = [m for m in matches if m.lower().startswith(query)]
        return {"users": filtered[:3]}

    return {"users": matches}




@router.post("/users")
@limiter.limit("5/minute")
async def create_user(
    request: Request,
    username: str = Form(...),
    gemini_api_key: str = Form(...),
    password: str = Form(...),
    _local_auth: None = Depends(require_local_auth_enabled),
):
    """Registers a new user context, requiring a valid Google AI Studio API key."""
    raw_sanitized = "".join(c for c in username if c.isalnum() or c in ("-", "_")).strip()
    sanitized = raw_sanitized.lower()
    
    is_valid_u, err_u = moderation.validate_username(sanitized)
    if not is_valid_u:
        raise HTTPException(status_code=400, detail=err_u)

    if config.IS_SELFHOSTED:
        all_users = database.get_all_users()
        if len(all_users) >= config.MAX_SELFHOSTED_USERS and sanitized not in all_users:
            raise HTTPException(
                status_code=403,
                detail=f"Self-hosted registration limit reached (maximum {config.MAX_SELFHOSTED_USERS} users allowed)."
            )

    key_clean = gemini_api_key.strip() if gemini_api_key else ""
    if not key_clean:
        raise HTTPException(status_code=400, detail="Google AI Studio API Key is required to create a profile.")

    # Validate Gemini API key probe
    try:
        async with httpx.AsyncClient(timeout=6.0) as client:
            probe = await client.get(
                f"https://generativelanguage.googleapis.com/v1beta/models?key={key_clean}"
            )
            if probe.status_code in (400, 403):
                raise HTTPException(status_code=400, detail="The provided Gemini API key is invalid. Please check it in Google AI Studio.")
            elif probe.status_code != 200:
                raise HTTPException(status_code=400, detail=f"Gemini API key verification failed (HTTP {probe.status_code}).")
    except HTTPException:
        raise
    except Exception as e_probe:
        raise HTTPException(status_code=503, detail=f"Could not reach Google AI Studio to verify key: {e_probe}")

    existing_users = database.get_all_users()
    if any(u.lower() == sanitized for u in existing_users):
        raise HTTPException(status_code=409, detail="A profile with that username already exists.")

    if not password or not password.strip():
        raise HTTPException(status_code=400, detail="A password is required to create a profile.")

    database.ensure_user_initialized(sanitized)

    # No UUID here: ensure_user_initialized() above created the profile row and
    # minted its user_uuid. write_user_config() only updates the columns it
    # names, so a "UUID" key passed here was silently dropped, not applied.
    user_data = {
        "CREATED_AT": datetime.now(timezone.utc).isoformat(),
        "DISPLAY_NAME": raw_sanitized,
        "GEMINI_API_KEY": key_clean,
        "PASSWORD_HASH": hash_password(password)
    }
    config.write_user_config(sanitized, user_data)
    config.sync_user_registry()

    token = _make_session_token(config.get_user_uuid_from_db(sanitized))
    response = JSONResponse({"status": "success", "username": sanitized})
    response.set_cookie(key="yb_session", value=token, httponly=True, samesite="lax", secure=config.IS_CLOUD, max_age=31536000, path="/")
    response.set_cookie(key="username", value=sanitized, httponly=False, samesite="lax", secure=config.IS_CLOUD, max_age=31536000, path="/")
    return response


@router.post("/users/verify")
@limiter.limit("15/minute")
async def verify_user(
    request: Request,
    username: str = Form(...),
    password: Optional[str] = Form(None),
    _local_auth: None = Depends(require_local_auth_enabled),
):
    """Validates credentials and issues a signed session token cookie."""
    try:
        sanitized = "".join(c for c in username if c.isalnum() or c in ("-", "_")).strip().lower()
        user_config = config.load_user_config(sanitized)
        pwd_hash = user_config.get("PASSWORD_HASH")

        if pwd_hash:
            if not password:
                raise HTTPException(status_code=401, detail="Password required for this profile")
            is_valid, upgraded_hash = verify_password(password, pwd_hash)
            if not is_valid:
                raise HTTPException(status_code=401, detail="Incorrect password")
            if upgraded_hash:
                config.write_user_config(sanitized, {"PASSWORD_HASH": upgraded_hash})
        else:
            # Accounts with no PASSWORD_HASH (e.g. Google-SSO-created accounts)
            # have no local password to check against, never fall through to
            # granting a session here, or any username/password (or no password
            # at all) would log in as that account.
            raise HTTPException(status_code=401, detail="This account has no password set. Please sign in with Google.")

        token = _make_session_token(config.get_user_uuid_from_db(sanitized))
        response = JSONResponse({"status": "success", "username": sanitized})
        response.set_cookie(key="yb_session", value=token, httponly=True, samesite="lax", secure=config.IS_CLOUD, max_age=31536000, path="/")
        response.set_cookie(key="username", value=sanitized, httponly=False, samesite="lax", secure=config.IS_CLOUD, max_age=31536000, path="/")
        # No longer mirrors the password into its own cookie: yb_session is the only thing that authenticates a request now, so a
        # separate plaintext-password cookie was pure liability. delete_cookie() here
        # clears any leftover copy from a browser that logged in before this fix.
        response.delete_cookie("profile_password", path="/", secure=config.IS_CLOUD)
        return response
    except HTTPException:
        raise
    except Exception as e:
        import logging
        logging.getLogger("studiamo").error(f"Error in verify_user for '{username}': {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Authentication error: {e}")


@router.post("/users/logout")
async def logout_user(request: Request):
    """Logs out the active user and clears session tracking cookies."""
    response = JSONResponse(content={"status": "success", "message": "Logged out"})
    response.delete_cookie("yb_session", path="/", secure=config.IS_CLOUD)
    response.delete_cookie("username", path="/", secure=config.IS_CLOUD)
    response.delete_cookie("profile_password", path="/", secure=config.IS_CLOUD)
    return response


@router.get("/status")
async def get_status(username: str = Depends(get_active_username)):
    """Returns application configuration status for active profile."""
    configured = config.is_configured(username)
    user_config = config.load_user_config(username)
    return {
        "is_configured": configured,
        "gemini_api_key_set": bool(user_config.get("GEMINI_API_KEY")),
        "telegram_bot_token_set": bool(user_config.get("TELEGRAM_BOT_TOKEN")),
        "telegram_chat_id_set": bool(user_config.get("TELEGRAM_CHAT_ID")),
        "base_url": user_config.get("BASE_URL", "")
    }


@router.post("/setup")
async def setup_app(
    gemini_api_key: str = Form(...),
    telegram_bot_token: Optional[str] = Form(None),
    base_url: str = Form(...),
    username: str = Depends(get_active_username)
):
    """Saves user API keys and setup configuration."""
    updates = {
        "GEMINI_API_KEY": gemini_api_key.strip(),
        "BASE_URL": base_url.strip().rstrip("/")
    }
    if telegram_bot_token and telegram_bot_token.strip():
        updates["TELEGRAM_BOT_TOKEN"] = telegram_bot_token.strip()

    config.write_user_config(username, updates)
    database.ensure_user_initialized(username)
    return {"status": "success", "message": "Configuration saved successfully"}


def get_oauth_redirect_uri(request: Request) -> str:
    host = request.headers.get("x-forwarded-host") or request.headers.get("host", "")
    if host in ("studiamo.cloud", "www.studiamo.cloud"):
        base_url = "https://studiamo.cloud"
    elif host == "staging.studiamo.cloud":
        base_url = "https://staging.studiamo.cloud"
    else:
        env_base = os.getenv("BASE_URL")
        if env_base and env_base.strip() and not ("127.0.0.1" in env_base or "localhost" in env_base):
            base_url = env_base.strip().rstrip("/")
        elif config.IS_CLOUD:
            base_url = "https://studiamo.cloud"
        else:
            proto = request.headers.get("x-forwarded-proto", "http")
            base_url = f"{proto}://{host or 'localhost:5004'}"
            
    return f"{base_url}/auth/google/callback"


@router.get("/auth/google")
async def google_login(request: Request, redirect: Optional[str] = None, require_existing: bool = False,
                       link: bool = False):
    """Redirects user to Google OAuth 2.0 consent screen.

    `link=true` is set only by the "Link Google Account" button in Settings. It is the one
    thing that lets the callback rebind an existing account's Google identity, so it travels
    in the signed state and cannot be inferred from the request itself."""
    client_id = os.getenv("GOOGLE_CLIENT_ID")
    if not client_id:
        raise HTTPException(status_code=400, detail="Google SSO is disabled or GOOGLE_CLIENT_ID is not configured.")

    redirect_uri = get_oauth_redirect_uri(request)

    target_redirect = redirect.strip() if redirect and redirect.strip().startswith("/") else "/"

    # A referral code from /join?ref=<code> travels here via a short-lived
    # cookie (set by /join) rather than a query param, so it survives even if
    # the user browses a bit before clicking "Continue with Google". It's
    # folded into `state` so it comes back on the callback round-trip.
    ref_code = (request.cookies.get("ref_code") or "").strip()
    if not _REF_CODE_PATTERN.match(ref_code):
        ref_code = ""
    # Captured here, not in google_callback: this is the last hop where the browser's Referer
    # header still points at our own site (e.g. /landing). Once we redirect to Google and it
    # redirects back, the callback's Referer is always accounts.google.com, so the real
    # originating page has to travel through the signed state instead.
    referrer = (request.headers.get("referer") or request.headers.get("referrer") or "").strip()
    # require_existing=true (used by the bug tracker's Google button) tells the callback to
    # refuse to sign up a Google identity it's never seen before, instead of silently creating
    # an empty account for whichever Gmail the person happened to click -- see google_callback.
    # The state is cryptographically signed to prevent OAuth CSRF / fixation attacks.
    signed_state = _sign_oauth_state(target_redirect, ref_code, require_existing, referrer, link)

    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "access_type": "online",
        "prompt": "select_account",
        "state": quote(signed_state, safe="")
    }
    url_params = "&".join(f"{k}={v}" for k, v in params.items())
    return RedirectResponse(f"https://accounts.google.com/o/oauth2/v2/auth?{url_params}")


@router.get("/auth/google/callback")
async def google_callback(
    request: Request,
    background_tasks: BackgroundTasks,
    code: Optional[str] = None,
    error: Optional[str] = None,
    state: Optional[str] = None
):
    """Handles Google OAuth callback code exchange and session creation.

    Thin wrapper so a database blip cannot surface as a raw 500. It matters more here than
    on other routes: Google's authorization code is single-use and is already spent by the
    time any query runs, so the 500 page the person reloads re-sends a code Google now
    rejects, and the browser reports 'token_exchange_failed' for what was really a dropped
    connection. Sending them back to /login makes the retry start a fresh flow that can
    actually succeed."""
    try:
        return await _google_callback(request, background_tasks, code, error, state)
    except psycopg2.OperationalError as e:
        import logging
        logging.getLogger("studiamo").error(f"[google_oauth] Database unavailable during callback: {e}")
        return RedirectResponse("/login?error=temporary_error")


async def _google_callback(
    request: Request,
    background_tasks: BackgroundTasks,
    code: Optional[str] = None,
    error: Optional[str] = None,
    state: Optional[str] = None
):
    if config.IS_SELFHOSTED:
        raise HTTPException(status_code=400, detail="Google SSO is disabled in self-hosted mode.")

    if error or not code:
        return RedirectResponse(f"/login?error={error or 'missing_code'}")

    client_id = os.getenv("GOOGLE_CLIENT_ID")
    client_secret = os.getenv("GOOGLE_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise HTTPException(status_code=500, detail="Google OAuth client credentials not set in environment.")

    redirect_uri = get_oauth_redirect_uri(request)

    # Decode and verify the cryptographically signed OAuth state parameter
    dest_path, ref_code, require_existing, origin_referrer, link_intent = _decode_oauth_state(state)

    async with httpx.AsyncClient(timeout=10.0) as client:
        token_res = await client.post(
            "https://oauth2.googleapis.com/token",
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": redirect_uri
            }
        )

        if token_res.status_code != 200:
            import logging
            logging.getLogger("studiamo").error(f"[google_oauth] Token exchange failed ({token_res.status_code}): {token_res.text} | redirect_uri={redirect_uri}")
            return RedirectResponse("/login?error=token_exchange_failed")

        tokens = token_res.json()
        access_token = tokens.get("access_token")

        user_res = await client.get(
            "https://www.googleapis.com/oauth2/v2/userinfo",
            headers={"Authorization": f"Bearer {access_token}"}
        )
        if user_res.status_code != 200:
            return RedirectResponse("/login?error=userinfo_failed")

        user_info = user_res.json()
        email = user_info.get("email", "")
        name = user_info.get("name") or email.split("@")[0]
        google_id = user_info.get("id")

        if not email:
            return RedirectResponse("/login?error=no_email")

        # Check if an active user is currently logged in via session cookie. This only ever
        # matters for the deliberate link flow below: a session cookie on its own says
        # nothing about what the person meant to do, and treating it as consent to rebind
        # is how a live account loses its Google identity to whichever account Google
        # happened to return.
        active_user_uuid = None
        raw_token = request.cookies.get("yb_session")
        if raw_token:
            decoded = _decode_session_token(raw_token)
            if decoded and config.looks_like_uuid(decoded):
                active_user_uuid = decoded

        target_username = None
        target_user_uuid = None

        if link_intent and active_user_uuid:
            # Case 1: User is logged in (e.g. 'Alice') and clicked "Link Google Account" in Settings.
            #
            # Gated on link_intent from the signed state, not on the cookie alone. Without that
            # gate every ordinary login carrying a session cookie landed here, so a second
            # callback firing against a still-valid state (a replayed authorize request returns
            # a different authuser under prompt=none) silently overwrote the signed-in account's
            # GOOGLE_ID/GOOGLE_EMAIL/EMAIL with an unrelated Google account. The original owner
            # then no longer matched their own account on the next login and got a brand new
            # empty one instead, while whoever held that second Google account owned their data.
            resolved_username = config.get_username_from_uuid(active_user_uuid)
            if resolved_username:
                # Refuse to attach an identity that already belongs to somebody else. Two rows
                # sharing a google_id/google_email would make the Case 2 lookup below ambiguous,
                # and the account that resolved first would answer for both people's logins.
                owner = database.find_user_by_google_identity(str(google_id), email)
                if owner and owner["user_uuid"] != active_user_uuid:
                    return RedirectResponse(f"{dest_path}?google_error=already_linked", status_code=303)

                target_username = resolved_username
                target_user_uuid = active_user_uuid
                config.write_user_config(target_username, {
                    "GOOGLE_ID": str(google_id),
                    "GOOGLE_EMAIL": email,
                    "EMAIL": email
                })
                token = _make_session_token(target_user_uuid)
                redirect_url = dest_path if dest_path != "/" else "/?google_linked=true"
                response = RedirectResponse(redirect_url, status_code=303)
                response.set_cookie(key="yb_session", value=token, httponly=True, samesite="lax", secure=config.IS_CLOUD, max_age=31536000, path="/")
                response.set_cookie(key="username", value=target_username, httponly=False, samesite="lax", secure=config.IS_CLOUD, max_age=31536000, path="/")
                return response
            # else: cookie decoded to a uuid with no matching row (deleted account), # fall through to Case 2 and treat this as a fresh login.

        # Case 2: Logging in via Google SSO on /login
        conn = database.get_db_connection("system")
        cursor = conn.cursor()
        uname_base = email.split("@")[0].replace(".", "_").strip().lower()

        # Same resolution the link flow above checks against, so "which account owns this
        # Google identity" has exactly one answer in the codebase.
        row = database.find_user_by_google_identity(str(google_id), email)

        if row:
            target_username = row["username"]
            target_user_uuid = row["user_uuid"]
            conn.close()

            if row["status"] == "waitlist":
                # Returning waitlist user: never issue a session for a
                # non-active account, see the capacity-gating note above
                # get_active_username() in dependencies.py for why the app
                # doesn't need a second check anywhere else.
                own_ref_code = row["referral_code"] or database.ensure_referral_code(target_username)
                return RedirectResponse(f"/waitlist-confirmation?ref={own_ref_code}", status_code=303)

            config.write_user_config(target_username, {
                "GOOGLE_ID": str(google_id),
                "GOOGLE_EMAIL": email,
                "EMAIL": email
            })
        else:
            # No account has this Google identity linked yet.
            if require_existing:
                # The bug tracker's Google button sets this: refuse to sign up a Google
                # identity it's never seen before, rather than silently creating an empty
                # account for whichever Gmail the person happened to click. Sending them
                # back to pick a different account (or go create one properly via /login)
                # avoids leaving behind an orphaned account nobody meant to make.
                conn.close()
                return RedirectResponse(f"{dest_path}?google_error=no_account", status_code=303)

            # Usernames can be renamed (see routers/settings.py's username-change path), so a
            # candidate colliding with an existing *different* account doesn't mean it's the
            # same person -- it just means someone else already has that name. Generate a
            # distinct one instead of blocking signup. config.write_user_config() updates by
            # username alone, so we must never proceed with a colliding name: that would
            # overwrite the existing account's Google identity fields instead of creating a
            # new one.
            base_username = uname_base or f"user_{str(uuid.uuid4())[:6]}"
            candidate_username = base_username
            for _ in range(20):
                cursor.execute(
                    "SELECT 1 FROM user_profile WHERE LOWER(username) = LOWER(%s) LIMIT 1;",
                    (candidate_username,)
                )
                if not cursor.fetchone():
                    break
                candidate_username = f"{base_username}{random.randint(100, 999999)}"
            else:
                candidate_username = f"user_{str(uuid.uuid4())[:8]}"
            conn.close()

            target_username = candidate_username

            # Referral attribution is recorded whenever a valid referrer code
            # was passed in, independent of the reward below. The reward
            # (referrer's referral_count, which moves them up the computed
            # waitlist ordering) is capped at 5 and credited atomically so
            # concurrent referrals can't push a referrer past the cap.
            referrer = database.find_user_by_referral_code(ref_code) if ref_code else None
            referred_by_uuid = referrer["user_uuid"] if referrer else None
            if referrer:
                database.credit_referral(ref_code)

            new_referral_code = database.generate_referral_code()
            new_status = "waitlist" if database.is_at_capacity() else "active"

            database.ensure_user_initialized(
                target_username,
                status=new_status,
                referral_code=new_referral_code,
                referred_by_uuid=referred_by_uuid,
            )
            safe_display_name = name if (name and moderation.validate_display_name(name)[0]) else "Learner"
            config.write_user_config(target_username, {
                "DISPLAY_NAME": safe_display_name,
                "GOOGLE_ID": str(google_id),
                "GOOGLE_EMAIL": email,
                "EMAIL": email
            })
            target_user_uuid = config.get_user_uuid_from_db(target_username)

            if new_status == "waitlist":
                import logging
                from app import landing_waitlist_db

                # Record the lead synchronously so it's saved even if the
                # confirmation email below fails. This is supplementary
                # tracking only, never let it block the waitlist redirect.
                # origin_referrer (from the signed OAuth state) is the page that started the
                # flow; the request's own Referer header at this point is always Google's
                # consent screen, so it's only used as a fallback for old/legacy state tokens.
                referrer = (origin_referrer or request.headers.get("referer") or request.headers.get("referrer") or "")[:500] or None
                country = (request.headers.get("cf-ipcountry") or request.headers.get("x-country") or "")[:10] or None
                user_agent = (request.headers.get("user-agent") or "")[:500] or None
                try:
                    landing_waitlist_db.record_waitlist_lead(email, target_user_uuid, referrer, country, user_agent, preference="google_oauth")
                except Exception as e:
                    logging.getLogger("studiamo").warning(f"Failed to record landing_waitlist lead for {email!r}: {e}")

                def _send_and_mark_waitlist_confirmation():
                    from app.email_utils import send_waitlist_status_email
                    sent = send_waitlist_status_email(email, new_referral_code)
                    if sent:
                        try:
                            landing_waitlist_db.mark_waitlist_email_sent(email, "confirmation")
                        except Exception as e:
                            logging.getLogger("studiamo").warning(f"Failed to mark confirmation sent for {email!r}: {e}")

                background_tasks.add_task(_send_and_mark_waitlist_confirmation)
                return RedirectResponse(f"/waitlist-confirmation?ref={new_referral_code}", status_code=303)

            # A new account that never had to wait, because a spot was free. If this address
            # is already on the lead list (they signed up on /landing before the app opened),
            # it stops being a prospect the moment the account works, the same as a promotion
            # does. Without this they stay on the list as someone still waiting for a spot
            # they are already using. Backgrounded so a marketing-table write never delays
            # the login redirect, and swallowed on failure for the same reason recording the
            # lead above is: it is supplementary tracking, never a reason to fail a signup.
            def _mark_lead_converted():
                import logging
                from app import landing_waitlist_db as _lw
                try:
                    _lw.mark_waitlist_converted(email)
                except Exception as e:
                    logging.getLogger("studiamo").warning(
                        f"Failed to stamp landing_waitlist conversion for {email!r}: {e}"
                    )

            background_tasks.add_task(_mark_lead_converted)

        token = _make_session_token(target_user_uuid)

        response = RedirectResponse(dest_path, status_code=303)
        response.set_cookie(key="yb_session", value=token, httponly=True, samesite="lax", secure=config.IS_CLOUD, max_age=31536000, path="/")
        response.set_cookie(key="username", value=target_username, httponly=False, samesite="lax", secure=config.IS_CLOUD, max_age=31536000, path="/")
        return response
