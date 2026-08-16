

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

from app.config import require_env_for_cloud

# In cloud mode, an unset SECRET_KEY would silently fall back to a fixed
# string that's now public (quoted in an internal audit), anyone who knows
# it can forge waitlist-unsubscribe tokens for arbitrary emails. Self-hosted
# keeps the fallback since it's single-tenant and lower stakes.
SECRET_KEY = require_env_for_cloud("SECRET_KEY", default="studiamo-waitlist-secret-key-2026")


def generate_unsubscribe_token(email: str) -> str:
    """Generates a secure HMAC-SHA256 token for an email to prevent unauthorized unsubscribes."""
    return hmac.new(SECRET_KEY.encode(), email.lower().strip().encode(), hashlib.sha256).hexdigest()[:32]


def verify_unsubscribe_token(email: str, token: str) -> bool:
    """Verifies that an unsubscribe token matches the given email address."""
    if not email or not token:
        return False
    expected = generate_unsubscribe_token(email)
    return hmac.compare_digest(expected, token.strip())


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


def _send_via_resend(recipient_email: str, subject: str, html_content: str, text_content: str, log_tag: str) -> bool:
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
        resend.Emails.send({
            "from": RESEND_FROM,
            "to": [recipient_email],
            "subject": subject,
            "html": html_content,
            "text": text_content,
        })
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
    referral_link = f"https://studiamo.cloud/join?ref={referral_code}"
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
                © 2026 Studiamo Learning System
            </div>
        </div>
    </body>
    </html>
    """
    text_content = (
        "You're on the Studiamo waitlist.\n\n"
        "Studiamo is at capacity right now, so we've placed your account on the waitlist. "
        "We'll email you the moment a spot opens up.\n\n"
        f"Want to move up faster? Share your referral link (up to 5 referrals count): {referral_link}\n"
    )
    return _send_via_resend(recipient_email, subject, html_content, text_content, "ACCOUNT WAITLIST EMAIL")


def send_notification_email(recipient_email: str, subject: str, heading: str, body_text: str, cta_url: str, cta_label: str = "Open Studiamo") -> bool:
    """Sends a branded transactional notification email (quiz due, streak
    warning, inactivity reminder) via Resend. Cloud-only, self-hosted has
    no guaranteed email delivery configured, see send_notification_email
    callers in telegram_bot.py which gate on notify_email + google_email."""
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
            <h1 style="color: #1c1917; font-size: 26px; font-weight: 800; margin: 0 0 12px; letter-spacing: -0.5px;">{heading}</h1>
            <p style="color: #57534e; font-size: 15px; line-height: 1.65; margin: 0 0 16px;">{body_text}</p>
            <a href="{cta_url}" style="display: inline-block; background: #d97706; color: #ffffff; text-decoration: none; font-weight: 700; font-size: 14px; padding: 12px 24px; border-radius: 12px; margin: 8px 0 20px;">{cta_label}</a>
            <div style="font-size: 12px; color: #a8a29e; margin-top: 28px; text-align: center; border-top: 1px solid #e7dfd3; padding-top: 20px; line-height: 1.6;">
                © 2026 Studiamo Learning System · You can turn these off anytime in Settings → Notifications.
            </div>
        </div>
    </body>
    </html>
    """
    text_content = f"{heading}\n\n{body_text}\n\n{cta_label}: {cta_url}\n"
    return _send_via_resend(recipient_email, subject, html_content, text_content, "NOTIFICATION EMAIL")


def send_promotion_email(recipient_email: str) -> bool:
    """Sends the "you're in" email when an admin promotes a waitlist account to active."""
    subject = "Your spot is ready, sign in at Studiamo"

    html_content = """
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
            <a href="https://studiamo.cloud/login" style="display: inline-block; background: #d97706; color: #ffffff; text-decoration: none; font-weight: 700; font-size: 14px; padding: 12px 24px; border-radius: 12px; margin: 8px 0 20px;">Sign in to Studiamo</a>
            <div style="font-size: 12px; color: #a8a29e; margin-top: 28px; text-align: center; border-top: 1px solid #e7dfd3; padding-top: 20px; line-height: 1.6;">
                © 2026 Studiamo Learning System
            </div>
        </div>
    </body>
    </html>
    """
    text_content = (
        "Your spot is ready!\n\n"
        "A spot just opened up and your Studiamo account is now active. "
        "Sign in at https://studiamo.cloud/login whenever you're ready.\n"
    )
    return _send_via_resend(recipient_email, subject, html_content, text_content, "PROMOTION EMAIL")
