

import html
import os
import smtplib
import logging
import hmac
import hashlib
import urllib.parse
from pathlib import Path
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# Load root .env into os.environ if python-dotenv is available
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=False)
except ImportError:
    pass  # python-dotenv not installed | rely on systemd/shell env vars

logger = logging.getLogger("studiamo")

RESEND_FROM = os.environ.get("SMTP_FROM", "Studiamo <hello@studiamo.cloud>")

from app import config
from app.config import require_env_for_cloud, BASE_DIR

_SECRET_KEY_FILE = BASE_DIR / ".waitlist_secret_key"


def _ensure_self_hosted_secret_key() -> str:
    """Persists a random key to disk on first run (mirrors webpush_utils.ensure_vapid_keys),
    so self-hosted unsubscribe/Telegram-link tokens survive restarts without shipping a
    fixed literal in source, which anyone reading this public repo would otherwise know."""
    if _SECRET_KEY_FILE.exists():
        try:
            existing = _SECRET_KEY_FILE.read_text(encoding="utf-8").strip()
            if existing:
                return existing
        except Exception as e:
            logger.warning(f"Failed to read {_SECRET_KEY_FILE}: {e}")
    import secrets
    new_key = secrets.token_hex(32)
    try:
        _SECRET_KEY_FILE.write_text(new_key, encoding="utf-8")
    except Exception as e:
        logger.warning(f"Failed to persist {_SECRET_KEY_FILE}, key will not survive restart: {e}")
    return new_key


# Cloud mode requires SECRET_KEY to be set explicitly (raises otherwise, see
# require_env_for_cloud). Self-hosted generates and persists a random per-install
# key on first run instead of using a fixed default.
SECRET_KEY = require_env_for_cloud("SECRET_KEY") or _ensure_self_hosted_secret_key()


def generate_unsubscribe_token(email: str, purpose: str = "") -> str:
    """Generates a secure HMAC-SHA256 token for an email to prevent unauthorized unsubscribes.

    `purpose` separates token families, so a waitlist unsubscribe link cannot be replayed
    against the reminder-email switch or the other way around. The empty purpose is the
    original waitlist token, unchanged so links already sent keep working."""
    message = email.lower().strip() if not purpose else f"{purpose}:{email.lower().strip()}"
    return hmac.new(SECRET_KEY.encode(), message.encode(), hashlib.sha256).hexdigest()[:32]


def verify_unsubscribe_token(email: str, token: str, purpose: str = "") -> bool:
    """Verifies that an unsubscribe token matches the given email address."""
    if not email or not token:
        return False
    expected = generate_unsubscribe_token(email, purpose)
    return hmac.compare_digest(expected, token.strip())


REMINDER_EMAILS_PURPOSE = "reminders"


def reminder_emails_off_url(recipient_email: str) -> str:
    """Returns the tokenized link that turns off reminder emails for this address, without
    signing in. Used in the footer and in the List-Unsubscribe header."""
    base = "https://www.studiamo.cloud" if config.IS_CLOUD else (os.getenv("BASE_URL") or "https://studiamo.cloud").rstrip("/")
    return (
        f"{base}/api/notifications/email-off"
        f"?email={urllib.parse.quote(recipient_email)}"
        f"&token={generate_unsubscribe_token(recipient_email, REMINDER_EMAILS_PURPOSE)}"
    )


def unsubscribe_url(recipient_email: str) -> str:
    """Returns the tokenized unsubscribe URL for one address.

    Every email that goes to the waitlist has to carry this. The address is the only thing
    identifying the row to opt out, and the token is what stops anyone from unsubscribing
    someone else by editing the query string."""
    return (
        "https://studiamo.cloud/api/waitlist/unsubscribe"
        f"?email={urllib.parse.quote(recipient_email)}"
        f"&token={generate_unsubscribe_token(recipient_email)}"
    )


def send_waitlist_confirmation_email(recipient_email: str) -> bool:
    """
    Sends a branded confirmation email after a user joins the Studiamo waitlist.

    Reads SMTP credentials from environment variables (or the root .env file).
    These are server-level settings (NOT stored in any user's config.json).
    If SMTP is not configured, logs the intent and returns False without failing:
    the signup data is always saved to the database regardless.

    Returns True if the email was sent successfully, False otherwise.
    """
    smtp_host     = os.environ.get("SMTP_HOST", "")
    smtp_port     = int(os.environ.get("SMTP_PORT", "587"))
    smtp_user     = os.environ.get("SMTP_USER", "")
    smtp_password = os.environ.get("SMTP_PASSWORD", "")
    smtp_from     = os.environ.get("SMTP_FROM", "Studiamo <hello@studiamo.cloud>")

    unsub_token = generate_unsubscribe_token(recipient_email)
    encoded_email = urllib.parse.quote(recipient_email)

    subject = "You're on the Studiamo waitlist 🎉"

    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <style>
            body {{
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                background-color: #f6f1e7;
                color: #1c1917;
                margin: 0;
                padding: 40px 20px;
            }}
            .container {{
                max-width: 540px;
                margin: 0 auto;
                background: #ffffff;
                border: 1px solid #e7dfd3;
                border-radius: 20px;
                padding: 36px 32px;
            }}
            .logo-wrap {{
                display: inline-flex;
                align-items: center;
                gap: 10px;
                margin-bottom: 28px;
            }}
            .logo-icon {{
                background: #d97706;
                border-radius: 10px;
                width: 38px;
                height: 38px;
                display: inline-flex;
                align-items: center;
                justify-content: center;
                font-size: 20px;
            }}
            .logo-text {{
                font-size: 20px;
                font-weight: 800;
                color: #1c1917;
                letter-spacing: -0.5px;
            }}
            h1 {{
                color: #1c1917;
                font-size: 26px;
                font-weight: 800;
                margin: 0 0 12px;
                letter-spacing: -0.5px;
            }}
            p {{
                color: #57534e;
                font-size: 15px;
                line-height: 1.65;
                margin: 0 0 16px;
            }}
            .highlight {{ color: #d97706; font-weight: 600; }}
            .card {{
                background: #fbf8f2;
                border: 1px solid #e7dfd3;
                border-radius: 12px;
                padding: 18px 20px;
                margin: 24px 0;
            }}
            .card p {{ margin: 0; font-size: 14px; color: #44403c; }}
            .footer {{
                font-size: 12px;
                color: #a8a29e;
                margin-top: 28px;
                text-align: center;
                border-top: 1px solid #e7dfd3;
                padding-top: 20px;
                line-height: 1.6;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="logo-wrap">
                <img src="/static/images/logo-icon.png" width="32" height="32" style="border-radius: 8px; vertical-align: middle;" alt="Studiamo Logo" />
                <span class="logo-text">Studiamo</span>
            </div>

            <h1>You're on the list! 🎉</h1>

            <p>
                Thank you for signing up for <strong>Studiamo</strong>: The AI-powered
                spaced repetition system that turns your lectures, videos, and PDFs into
                active-recall flashcards, automatically.
            </p>

            <p>
                We've reserved a spot for <span class="highlight">{recipient_email}</span>
                on our early access waitlist.
            </p>

            <div class="card">
                <p>
                    ✨ <strong>What happens next?</strong><br><br>
                    The moment Studiamo launches, whether for Managed Cloud or Open
                    Source self-hosting, you'll be among the first to know.
                    No spam, ever. Just one email when it's ready.
                </p>
            </div>

            <p>
                Have a question or want to share feedback? Just reply to this email,
                we read everything.
            </p>

            <div class="footer">
                © 2026 Studiamo Learning System · Made in Basel 🇨🇭<br>
                You're receiving this because you signed up at studiamo.app.<br>
                <a href="https://studiamo.cloud/api/waitlist/unsubscribe?email={encoded_email}&token={unsub_token}" style="color: #a8a29e; text-decoration: underline;">Unsubscribe</a>
            </div>
        </div>
    </body>
    </html>
    """

    text_content = (
        f"You're on the Studiamo waitlist!\n\n"
        f"Thank you for signing up. We've reserved a spot for {recipient_email}.\n\n"
        f"The moment Studiamo launches you'll be among the first to know. "
        f"No spam, just one email when it's ready.\n\n"
        f"The Studiamo Team, Basel 🇨🇭"
    )

    if not smtp_host or not smtp_user:
        logger.info(
            f"[WAITLIST EMAIL] SMTP not configured: skipping live send for {recipient_email}. "
            f"Data is saved in DB. See email_utils.py header for setup instructions."
        )
        return False

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = smtp_from
        msg["To"] = recipient_email

        msg.attach(MIMEText(text_content, "plain", "utf-8"))
        msg.attach(MIMEText(html_content, "html", "utf-8"))

        with smtplib.SMTP(smtp_host, smtp_port, timeout=10) as server:
            server.starttls()
            if smtp_password:
                server.login(smtp_user, smtp_password)
            server.sendmail(smtp_from, [recipient_email], msg.as_string())

        logger.info(f"[WAITLIST EMAIL] Confirmation sent to {recipient_email}")
        return True

    except Exception as e:
        logger.error(f"[WAITLIST EMAIL] Failed to send to {recipient_email}: {e}")
        return False


def _send_via_resend(recipient_email: str, subject: str, html_content: str, text_content: str, log_tag: str,
                     headers: dict | None = None) -> bool:
    """Shared Resend send path for the account-waitlist/promotion emails
    (separate from the SMTP path above, which the pre-launch landing-page
    waitlist emails still use). Returns False without raising if RESEND_API_KEY
    isn't set, the caller's DB write already happened, so a missing/failed
    email should never block the actual account action."""
    api_key = os.environ.get("RESEND_API_KEY", "").strip()
    if not api_key:
        logger.info(f"[{log_tag}] RESEND_API_KEY not configured: skipping live send for {recipient_email}.")
        return False
    try:
        import resend
        resend.api_key = api_key
        params = {
            "from": RESEND_FROM,
            "to": [recipient_email],
            "subject": subject,
            "html": html_content,
            "text": text_content,
        }
        if headers:
            params["headers"] = headers
        resend.Emails.send(params)
        logger.info(f"[{log_tag}] Sent to {recipient_email}")
        return True
    except Exception as e:
        logger.error(f"[{log_tag}] Failed to send to {recipient_email}: {e}")
        return False


def send_waitlist_status_email(recipient_email: str, referral_code: str) -> bool:
    """Sends the immediate confirmation email when a Google-SSO signup lands
    on the account waitlist (registration-cap reached). Not to be confused
    with send_waitlist_confirmation_email above, which is for the separate
    pre-launch landing-page email list."""
    # src=email splits clicks on this link from clicks on the link the person
    # copied off the confirmation page, see serve_join() in app/main.py.
    referral_link = f"https://studiamo.cloud/join?ref={referral_code}&src=email"
    subject = "You're on the Studiamo waitlist"

    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"></head>
    <body style="font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background-color: #f6f1e7; color: #1c1917; margin: 0; padding: 40px 20px;">
        <div style="max-width: 540px; margin: 0 auto; background: #ffffff; border: 1px solid #e7dfd3; border-radius: 20px; padding: 36px 32px;">
            <div style="display: inline-flex; align-items: center; gap: 10px; margin-bottom: 28px;">
                <img src="https://studiamo.cloud/static/images/logo-icon.png" width="32" height="32" style="border-radius: 8px; vertical-align: middle;" alt="Studiamo Logo" />
                <span style="font-size: 20px; font-weight: 800; color: #1c1917; letter-spacing: -0.5px;">Studiamo</span>
            </div>
            <h1 style="color: #1c1917; font-size: 26px; font-weight: 800; margin: 0 0 12px; letter-spacing: -0.5px;">You're on the waitlist</h1>
            <p style="color: #57534e; font-size: 15px; line-height: 1.65; margin: 0 0 16px;">
                Studiamo is at capacity right now, so we've placed your account on the waitlist.
                No pressure to do anything , spots open up regularly as we grow, and we'll email you
                the moment yours is ready.
            </p>
            <p style="color: #57534e; font-size: 15px; line-height: 1.65; margin: 0 0 16px;">
                Want to move up a little faster? Share your referral link, each friend who joins
                through it moves you up the list (up to 5 referrals count):
            </p>
            <div style="background: #fbf8f2; border: 1px solid #e7dfd3; border-radius: 12px; padding: 18px 20px; margin: 24px 0;">
                <p style="margin: 0; font-size: 14px; color: #44403c; word-break: break-all;">{referral_link}</p>
            </div>
            <p style="color: #57534e; font-size: 15px; line-height: 1.65; margin: 0 0 16px;">
                By joining the waitlist, you agreed to receive one email when your spot is ready, that's this one,
                plus a single follow-up when you're promoted. See our
                <a href="https://studiamo.cloud/privacy" style="color: #d97706;">Privacy Policy</a>.
            </p>
            <div style="font-size: 12px; color: #a8a29e; margin-top: 28px; text-align: center; border-top: 1px solid #e7dfd3; padding-top: 20px; line-height: 1.6;">
                © 2026 Studiamo Learning System<br>
                <a href="{unsubscribe_url(recipient_email)}" style="color: #a8a29e; text-decoration: underline;">Unsubscribe</a>
            </div>
        </div>
    </body>
    </html>
    """
    text_content = (
        "You're on the Studiamo waitlist.\n\n"
        "Studiamo is at capacity right now, so we've placed your account on the waitlist. "
        "We'll email you the moment a spot opens up.\n\n"
        f"Want to move up faster? Share your referral link (up to 5 referrals count): {referral_link}\n\n"
        f"Unsubscribe: {unsubscribe_url(recipient_email)}\n"
    )
    return _send_via_resend(recipient_email, subject, html_content, text_content, "ACCOUNT WAITLIST EMAIL")


def send_notification_email(recipient_email: str, subject: str, heading: str, body_text: str, cta_url: str,
                            cta_label: str = "Open Studiamo", settings_url: str | None = None) -> bool:
    """Sends a branded reminder email (app/notifications.py) via Resend. Cloud-only in
    practice: self-hosted has no guaranteed email delivery configured.

    heading and body_text are plain text and escaped here: reminder texts carry video titles,
    which are user content. The footer links to the notification settings and carries a
    one-click switch that turns reminder emails off without signing in, mirrored in the
    List-Unsubscribe headers so mail clients can offer the same."""
    heading_html = html.escape(heading)
    body_html = html.escape(body_text)
    off_url = reminder_emails_off_url(recipient_email)
    settings_link = settings_url or cta_url
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"></head>
    <body style="font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background-color: #f6f1e7; color: #1c1917; margin: 0; padding: 40px 20px;">
        <div style="max-width: 540px; margin: 0 auto; background: #ffffff; border: 1px solid #e7dfd3; border-radius: 20px; padding: 36px 32px;">
            <div style="display: inline-flex; align-items: center; gap: 10px; margin-bottom: 28px;">
                <img src="https://studiamo.cloud/static/images/logo-icon.png" width="32" height="32" style="border-radius: 8px; vertical-align: middle;" alt="Studiamo Logo" />
                <span style="font-size: 20px; font-weight: 800; color: #1c1917; letter-spacing: -0.5px;">Studiamo</span>
            </div>
            <h1 style="color: #1c1917; font-size: 26px; font-weight: 800; margin: 0 0 12px; letter-spacing: -0.5px;">{heading_html}</h1>
            <p style="color: #57534e; font-size: 15px; line-height: 1.65; margin: 0 0 16px;">{body_html}</p>
            <a href="{cta_url}" style="display: inline-block; background: #d97706; color: #ffffff; text-decoration: none; font-weight: 700; font-size: 14px; padding: 12px 24px; border-radius: 12px; margin: 8px 0 20px;">{html.escape(cta_label)}</a>
            <div style="font-size: 13px; color: #57534e; background: #fbf8f2; border: 1px solid #e7dfd3; border-radius: 12px; padding: 14px 16px; margin-top: 12px; line-height: 1.6;">
                Rather get these as push notifications or on Telegram?
                <a href="{settings_link}" style="color: #b45309; font-weight: 700;">Change it in your notification settings</a>.
            </div>
            <div style="font-size: 12px; color: #a8a29e; margin-top: 28px; text-align: center; border-top: 1px solid #e7dfd3; padding-top: 20px; line-height: 1.6;">
                © 2026 Studiamo Learning System<br>
                Reminders tell you when a review is due, which is what makes spaced repetition work.<br>
                <a href="{off_url}" style="color: #a8a29e; text-decoration: underline;">Turn off reminder emails</a>
            </div>
        </div>
    </body>
    </html>
    """
    text_content = (
        f"{heading}\n\n{body_text}\n\n{cta_label}: {cta_url}\n\n"
        f"Rather get these as push notifications or on Telegram? {settings_link}\n"
        f"Turn off reminder emails: {off_url}\n"
    )
    headers = {
        "List-Unsubscribe": f"<{off_url}>",
        "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
    }
    return _send_via_resend(recipient_email, subject, html_content, text_content, "NOTIFICATION EMAIL", headers=headers)


def send_promotion_email(recipient_email: str) -> bool:
    """Sends the "you're in" email when an admin promotes a waitlist account to active."""
    subject = "Your spot is ready, sign in at Studiamo"

    # f-string because of the unsubscribe URL in the footer. This body carries no CSS blocks,
    # so there are no literal braces that would need doubling.
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"></head>
    <body style="font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background-color: #f6f1e7; color: #1c1917; margin: 0; padding: 40px 20px;">
        <div style="max-width: 540px; margin: 0 auto; background: #ffffff; border: 1px solid #e7dfd3; border-radius: 20px; padding: 36px 32px;">
            <div style="display: inline-flex; align-items: center; gap: 10px; margin-bottom: 28px;">
                <img src="https://studiamo.cloud/static/images/logo-icon.png" width="32" height="32" style="border-radius: 8px; vertical-align: middle;" alt="Studiamo Logo" />
                <span style="font-size: 20px; font-weight: 800; color: #1c1917; letter-spacing: -0.5px;">Studiamo</span>
            </div>
            <h1 style="color: #1c1917; font-size: 26px; font-weight: 800; margin: 0 0 12px; letter-spacing: -0.5px;">Your spot is ready 🎉</h1>
            <p style="color: #57534e; font-size: 15px; line-height: 1.65; margin: 0 0 16px;">
                Good news, a spot just opened up and your Studiamo account is now active.
                Sign in with Google whenever you're ready.
            </p>
            <a href="https://studiamo.cloud/login?src=waitlist_promotion" style="display: inline-block; background: #d97706; color: #ffffff; text-decoration: none; font-weight: 700; font-size: 14px; padding: 12px 24px; border-radius: 12px; margin: 8px 0 20px;">Sign in to Studiamo</a>
            <div style="font-size: 12px; color: #a8a29e; margin-top: 28px; text-align: center; border-top: 1px solid #e7dfd3; padding-top: 20px; line-height: 1.6;">
                © 2026 Studiamo Learning System<br>
                <a href="{unsubscribe_url(recipient_email)}" style="color: #a8a29e; text-decoration: underline;">Unsubscribe</a>
            </div>
        </div>
    </body>
    </html>
    """
    text_content = (
        "Your spot is ready!\n\n"
        "A spot just opened up and your Studiamo account is now active. "
        "Sign in at https://studiamo.cloud/login?src=waitlist_promotion whenever you're ready.\n\n"
        f"Unsubscribe: {unsubscribe_url(recipient_email)}\n"
    )
    return _send_via_resend(recipient_email, subject, html_content, text_content, "PROMOTION EMAIL")


def send_tester_access_email(recipient_email: str, expires_at=None) -> bool:
    """Sends the "you're in the test group" email when an admin grants tester access.

    `expires_at` is the end of the period, or None for a grant with no end date. The date is
    the substance of this email, not decoration: the in-app welcome (tester_access.
    welcome_seen_at) already greets a tester who opens the app, so what an email adds is
    reaching someone who does not yet know there is anything to open, and telling them how
    long they have. A version that only said "you have access" would carry less than the
    dialog it was sent from."""
    if expires_at is not None:
        # Not %-d/%B directly in one format string: %-d is a GNU extension, and this same
        # module already has to run wherever the app is self-hosted.
        until = f"{expires_at:%B} {expires_at.day}, {expires_at.year}"
        window_html = (f"Your tester access runs until <strong>{until}</strong>. "
                       "We'll remind you inside the app before it ends.")
        window_text = f"Your tester access runs until {until}."
    else:
        window_html = "Your tester access has no end date."
        window_text = "Your tester access has no end date."

    subject = "Your Studiamo tester access is live"

    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"></head>
    <body style="font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background-color: #f6f1e7; color: #1c1917; margin: 0; padding: 40px 20px;">
        <div style="max-width: 540px; margin: 0 auto; background: #ffffff; border: 1px solid #e7dfd3; border-radius: 20px; padding: 36px 32px;">
            <div style="display: inline-flex; align-items: center; gap: 10px; margin-bottom: 28px;">
                <img src="https://studiamo.cloud/static/images/logo-icon.png" width="32" height="32" style="border-radius: 8px; vertical-align: middle;" alt="Studiamo Logo" />
                <span style="font-size: 20px; font-weight: 800; color: #1c1917; letter-spacing: -0.5px;">Studiamo</span>
            </div>
            <h1 style="color: #1c1917; font-size: 26px; font-weight: 800; margin: 0 0 12px; letter-spacing: -0.5px;">You're in the test group 🎉</h1>
            <p style="color: #57534e; font-size: 15px; line-height: 1.65; margin: 0 0 16px;">
                Your Studiamo account now has tester access, which means the full app with no
                subscription needed. {window_html}
            </p>
            <p style="color: #57534e; font-size: 15px; line-height: 1.65; margin: 0 0 16px;">
                Use it the way you would actually use it, and tell us what gets in your way.
                That's the whole point of a test phase.
            </p>
            <a href="https://studiamo.cloud/login?src=tester_access" style="display: inline-block; background: #d97706; color: #ffffff; text-decoration: none; font-weight: 700; font-size: 14px; padding: 12px 24px; border-radius: 12px; margin: 8px 0 20px;">Open Studiamo</a>
            <div style="font-size: 12px; color: #a8a29e; margin-top: 28px; text-align: center; border-top: 1px solid #e7dfd3; padding-top: 20px; line-height: 1.6;">
                © 2026 Studiamo Learning System<br>
                You're receiving this one-off email because your account was given tester access.
            </div>
        </div>
    </body>
    </html>
    """
    text_content = (
        "You're in the test group.\n\n"
        "Your Studiamo account now has tester access, which means the full app with no "
        f"subscription needed. {window_text}\n\n"
        "Open Studiamo: https://studiamo.cloud/login?src=tester_access\n\n"
        "You're receiving this one-off email because your account was given tester access.\n"
    )
    return _send_via_resend(recipient_email, subject, html_content, text_content, "TESTER ACCESS EMAIL")
