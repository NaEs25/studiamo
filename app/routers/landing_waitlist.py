"""
Pre-launch landing-page email waitlist (marketing email capture on /landing).

Not to be confused with the account-level waitlist status used to gate
Google-SSO signups once the registered-user cap is reached, see
app/routers/auth.py and the 'status' column on user_profile for that system.
This router only ever deals with bare email addresses collected before launch,
stored in the landing_waitlist table via app/landing_waitlist_db.py.

The public API path (/api/waitlist) and frontend-facing behavior are
unchanged, only the internal module names were renamed for clarity.
"""

import re
import uuid
import logging
from typing import Optional
from fastapi import APIRouter, HTTPException, BackgroundTasks, Request
from pydantic import BaseModel
from app.landing_waitlist_db import get_waitlist_db
from app import database
from app.email_utils import send_waitlist_confirmation_email, verify_unsubscribe_token

logger = logging.getLogger("studiamo")

from app.dependencies import limiter

router = APIRouter(prefix="/api/waitlist", tags=["landing-waitlist"])


class WaitlistRequest(BaseModel):
    email: str
    preference: Optional[str] = "cloud"
    website: Optional[str] = ""  # Honeypot: hidden field, real users never fill it in
    referrer: Optional[str] = None  # document.referrer captured client-side: the page that sent the visitor here


@router.post("")
@limiter.limit("8/minute")  # Prevent bot spam: max 8 signups per IP per minute
async def join_waitlist(req: WaitlistRequest, background_tasks: BackgroundTasks, request: Request):
    email = req.email.strip().lower()
    preference = (req.preference or "cloud").strip().lower()

    if (req.website or "").strip():
        # Bots that autofill every field trip the honeypot. Return a fake
        # success so they don't learn to skip this field next time.
        logger.info(f"Waitlist honeypot triggered, ignoring submission (email={email!r})")
        return {
            "success": True,
            "already_registered": False,
            "position": 0,
            "message": "You're on the list! A confirmation email is on its way.",
        }

    if not email or not re.match(r"[^@]+@[^@]+\.[^@]+", email):
        raise HTTPException(status_code=400, detail="Please enter a valid email address.")

    # Waitlist leads are stored in their own dedicated table (landing_waitlist), # kept separate from any user's personal account data.
    conn = get_waitlist_db()
    cursor = conn.cursor()

    try:
        # Check if this email is already on the waitlist
        cursor.execute("SELECT id, unsubscribed, created_at FROM landing_waitlist WHERE email = ?;", (email,))
        existing = cursor.fetchone()

        if existing:
            cursor.execute("SELECT COUNT(*) FROM landing_waitlist WHERE id <= ?;", (existing["id"],))
            position = database.first_val(cursor.fetchone())

            if existing["unsubscribed"]:
                # User is re-subscribing! Reset unsubscribed = FALSE and send confirmation email
                cursor.execute(
                    "UPDATE landing_waitlist SET unsubscribed = FALSE, preference = ? WHERE id = ?;",
                    (preference, existing["id"]),
                )
                conn.commit()

                waitlist_id = existing["id"]
                def _send_and_update_resub():
                    sent = send_waitlist_confirmation_email(email)
                    if sent:
                        try:
                            c = get_waitlist_db()
                            c.execute(
                                "UPDATE landing_waitlist SET email_sent = TRUE, confirmation_sent_at = NOW(), emails_sent_count = COALESCE(emails_sent_count, 0) + 1 WHERE id = ?;",
                                (waitlist_id,),
                            )
                            c.commit()
                            c.close()
                        except Exception as e:
                            logger.warning(f"Failed to mark email_sent for waitlist id={waitlist_id}: {e}")
                background_tasks.add_task(_send_and_update_resub)
                conn.close()

                return {
                    "success": True,
                    "already_registered": False,
                    "position": position,
                    "message": "Welcome back! Your waitlist subscription has been reactivated.",
                }
            else:
                # Deduplicate, already registered and active
                conn.close()
                return {
                    "success": True,
                    "already_registered": True,
                    "position": position,
                    "message": "You are already on the waitlist! Your spot has been reserved.",
                }

        # Register new email with a unique UUIDv4 identifier
        lead_uuid = str(uuid.uuid4())
        # The HTTP Referer header on this POST is always our own /landing page (that's
        # where the fetch() call originates), so it can't tell us where the visitor came
        # from. Prefer document.referrer sent by the client, which does. Fall back to the
        # header only for older cached frontends that don't send req.referrer at all.
        if req.referrer is not None:
            raw_ref = req.referrer.strip()
        else:
            raw_ref = request.headers.get("referer") or request.headers.get("referrer") or ""
        referrer = raw_ref[:500] if raw_ref else None
        country = (request.headers.get("cf-ipcountry") or request.headers.get("x-country") or "")[:10] or None
        user_agent = (request.headers.get("user-agent") or "")[:500] or None

        try:
            cursor.execute(
                "INSERT INTO landing_waitlist (uuid, email, preference, referrer, country, user_agent, email_sent) VALUES (?, ?, ?, ?, ?, ?, FALSE) RETURNING id;",
                (lead_uuid, email, preference, referrer, country, user_agent),
            )
            res = cursor.fetchone()
            waitlist_id = res["id"] if isinstance(res, dict) and "id" in res else (res[0] if res else cursor.lastrowid)
            conn.commit()
        except Exception:
            cursor.execute("SELECT id FROM landing_waitlist WHERE email = ?;", (email,))
            existing = cursor.fetchone()
            cursor.execute("SELECT COUNT(*) FROM landing_waitlist WHERE id <= ?;", (existing["id"],))
            position = database.first_val(cursor.fetchone())
            conn.close()
            return {
                "success": True,
                "already_registered": True,
                "position": position,
                "message": "You are already on the waitlist! Your spot has been reserved.",
            }

        cursor.execute("SELECT COUNT(*) FROM landing_waitlist;")
        position = database.first_val(cursor.fetchone())
        conn.close()

        # Fire-and-forget confirmation email (does not block the HTTP response)
        def _send_and_update():
            sent = send_waitlist_confirmation_email(email)
            if sent:
                try:
                    c = get_waitlist_db()
                    c.execute(
                        "UPDATE landing_waitlist SET email_sent = TRUE, confirmation_sent_at = NOW(), emails_sent_count = COALESCE(emails_sent_count, 0) + 1 WHERE id = ?;",
                        (waitlist_id,),
                    )
                    c.commit()
                    c.close()
                except Exception:
                    pass  # email_sent flag is best-effort; data is already saved

        background_tasks.add_task(_send_and_update)

        return {
            "success": True,
            "already_registered": False,
            "position": position,
            "message": "You're on the list! A confirmation email is on its way.",
        }

    except Exception as e:
        conn.close()
        raise HTTPException(status_code=500, detail=f"Could not save your registration: {str(e)}")


from fastapi.responses import HTMLResponse

@router.get("/count")
async def get_waitlist_count():
    """Returns the total number of waitlist signups (public, safe to expose)."""
    conn = get_waitlist_db()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM landing_waitlist;")
    count = database.first_val(cursor.fetchone())

    conn.close()
    return {"count": count}


@router.get("/unsubscribe", response_class=HTMLResponse)
async def unsubscribe_waitlist(email: str = "", token: str = ""):
    """Handles waitlist email unsubscribe requests securely using HMAC tokens."""
    clean_email = (email or "").strip().lower()
    is_valid = verify_unsubscribe_token(clean_email, token)

    if not is_valid and " " in clean_email:
        clean_email = clean_email.replace(" ", "+")
        is_valid = verify_unsubscribe_token(clean_email, token)

    if is_valid:
        try:
            conn = get_waitlist_db()
            conn.execute("UPDATE landing_waitlist SET unsubscribed = TRUE WHERE email = ?;", (clean_email,))
            conn.commit()
            conn.close()
            title = "You have been unsubscribed"
            message = f"Your email <strong>{clean_email}</strong> has been removed from our active waitlist notifications. You will not receive any further emails."
            icon = "✨"
        except Exception as e:
            logger.error(f"Failed to mark unsubscribed for email={clean_email}: {e}")
            title = "Something Went Wrong"
            message = f"We encountered an issue updating your preferences for <strong>{clean_email}</strong>. Please reply directly to any email from us and we will remove you manually."
            icon = "⚠️"
    else:
        title = "Invalid Unsubscribe Link"
        message = "This unsubscribe link is invalid or expired. If you need help, please reply directly to any email from us."
        icon = "🔒"

    return HTMLResponse(content=f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title} | Studiamo</title>
    <style>
        body {{ font-family: system-ui, -apple-system, sans-serif; background-color: #f6f1e7; color: #1c1917; margin: 0; padding: 60px 20px; text-align: center; }}
        .card {{ max-width: 480px; margin: 0 auto; background: #ffffff; border: 1px solid #e7dfd3; border-radius: 24px; padding: 40px 28px; box-shadow: 0 10px 25px -5px rgba(0,0,0,0.05); }}
        .icon {{ width: 56px; height: 56px; background: #fef3c7; color: #d97706; border-radius: 16px; display: inline-flex; align-items: center; justify-content: center; font-size: 28px; margin-bottom: 20px; }}
        h1 {{ font-size: 24px; font-weight: 800; margin: 0 0 12px; color: #1c1917; }}
        p {{ font-size: 15px; color: #57534e; line-height: 1.6; margin: 0 0 24px; }}
        a {{ display: inline-block; background: #d97706; color: #ffffff; text-decoration: none; font-weight: 700; font-size: 14px; padding: 12px 24px; border-radius: 12px; }}
    </style>
</head>
<body>
    <div class="card">
        <div class="icon">{icon}</div>
        <h1>{title}</h1>
        <p>{message}</p>
        <a href="/">Return to Studiamo</a>
    </div>
</body>
</html>""")
