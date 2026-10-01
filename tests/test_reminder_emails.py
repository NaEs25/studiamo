"""
Reminder emails: user content is escaped, the footer offers the settings and a one-click off
switch, and that switch's token cannot be swapped with the waitlist unsubscribe token.
Nothing is sent: the Resend call is replaced.
"""
from app import email_utils


def _capture(monkeypatch):
    sent = {}

    def fake_send(recipient, subject, html_content, text_content, log_tag, headers=None):
        sent.update(recipient=recipient, subject=subject, html=html_content, text=text_content, headers=headers)
        return True

    monkeypatch.setattr(email_utils, "_send_via_resend", fake_send)
    return sent


def test_video_titles_are_escaped(monkeypatch):
    sent = _capture(monkeypatch)
    email_utils.send_notification_email(
        "learner@example.com", "Chompy eats at midnight", "Chompy eats at midnight",
        "'<img src=x onerror=alert(1)>' is on his menu tonight.", "https://app.example/", "Open Studiamo",
    )
    assert "<img src=x" not in sent["html"]
    assert "&lt;img src=x onerror=alert(1)&gt;" in sent["html"]


def test_footer_and_one_click_headers(monkeypatch):
    sent = _capture(monkeypatch)
    email_utils.send_notification_email(
        "learner@example.com", "t", "t", "b", "https://app.example/", "Open Studiamo",
        settings_url="https://app.example/#notifications",
    )
    off_url = email_utils.reminder_emails_off_url("learner@example.com")
    assert "https://app.example/#notifications" in sent["html"]
    assert off_url.replace("&", "&") in sent["html"]
    assert sent["headers"]["List-Unsubscribe"] == f"<{off_url}>"
    assert sent["headers"]["List-Unsubscribe-Post"] == "List-Unsubscribe=One-Click"
    assert off_url in sent["text"]


def test_token_families_are_separate():
    email = "learner@example.com"
    waitlist = email_utils.generate_unsubscribe_token(email)
    reminders = email_utils.generate_unsubscribe_token(email, email_utils.REMINDER_EMAILS_PURPOSE)
    assert waitlist != reminders
    assert email_utils.verify_unsubscribe_token(email, reminders, email_utils.REMINDER_EMAILS_PURPOSE)
    assert not email_utils.verify_unsubscribe_token(email, waitlist, email_utils.REMINDER_EMAILS_PURPOSE)
    assert not email_utils.verify_unsubscribe_token(email, reminders)
    # The original waitlist token is unchanged, so links already sent keep working.
    assert email_utils.verify_unsubscribe_token(email, waitlist)


def test_invalid_off_link_changes_nothing(client):
    response = client.get("/api/notifications/email-off", params={"email": "nobody@example.com", "token": "forged"})
    assert response.status_code == 200
    assert "not valid" in response.text
    response = client.post("/api/notifications/email-off", params={"email": "nobody@example.com", "token": "forged"})
    assert response.status_code == 400
