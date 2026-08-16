#!/usr/bin/env python3
"""
Studiamo Notification Test Utility Script.
Allows testing Web Push and Telegram notifications directly from CLI for any user.
"""
import sys
import os
import json
import asyncio
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import load_user_config, get_user_dir, get_user_uuid_from_db
from app.webpush_utils import send_user_web_push
from app.telegram_bot import send_telegram_message


async def main():
    username = sys.argv[1] if len(sys.argv) > 1 else "demo_user"
    action = sys.argv[2] if len(sys.argv) > 2 else "test"

    print(f"=== Studiamo Notification Status & Test for User: {username} ===")

    user_cfg = load_user_config(username)
    user_uuid = get_user_uuid_from_db(username)
    print(f"User UUID: {user_uuid}")

    subs = user_cfg.get("push_subscriptions", [])
    print(f"Registered PWA Push Subscriptions: {len(subs)}")

    if action == "reset":
        from datetime import datetime, timezone, timedelta
        from app import database
        conn = database.get_db_connection(username)
        try:
            cursor = conn.cursor()
            future_time = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
            cursor.execute("UPDATE quizzes SET next_review_at = %s, notified = 0 WHERE user_uuid = %s;", (future_time, user_uuid))
            conn.commit()
            print("✅ All test due items successfully reset to tomorrow!")
        finally:
            conn.close()
        return

    # Send Test Messages
    print("\n1. Triggering Web Push notification...")
    payload = {
        "title": "🧪 Studiamo Web Push Test",
        "body": f"Hallo {username}, dies ist eine Test-Push-Nachricht von Studiamo! 🚀",
        "url": "/#review-section"
    }

    sent_count = 0
    if not subs:
        print("⚠️ Warning: No push subscriptions found in config.json yet.")
        print("   -> Make sure to open the PWA on your device at least once while logged in!")
    else:
        sent_count = send_user_web_push(username, payload)
        print(f"✅ Web Push dispatched to {sent_count} active device(s).")

    print("\n2. Checking Telegram Fallback logic...")
    channel = user_cfg.get("notification_channel", "both")
    should_send_telegram = (channel == "telegram") or (channel == "both" and sent_count == 0)

    if should_send_telegram:
        tel_success = await send_telegram_message(f"🧪 <b>Studiamo Test</b>: Hallo {username}, Telegram-Testnachricht (Fallback/Primary)!", username)
        if tel_success:
            print("✅ Telegram fallback notification sent successfully!")
        else:
            print("⚠️ Telegram notification failed (check bot token / chat id).")
    else:
        print("ℹ️ Telegram notification skipped because Web Push succeeded (Both mode with Fallback active).")



if __name__ == "__main__":
    asyncio.run(main())
