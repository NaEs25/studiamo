import json
import os
import re
import shutil
import tempfile
import uuid
import zipfile
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional
from urllib.parse import quote as _urlquote

import psycopg2.errors
from fastapi import APIRouter, Form, File, UploadFile, HTTPException, Depends, Request
from fastapi.responses import FileResponse, JSONResponse
from jinja2 import Environment, FileSystemLoader
from starlette.background import BackgroundTask

from app import config, database, storage, ai, gamification, moderation
from app.dependencies import (
    get_active_username,
    get_srs_intervals,
    limiter,
    hash_password,
    verify_password,
    require_dev_tools_enabled,
)

router = APIRouter(prefix="/api", tags=["Settings & Backup"])
logger = logging.getLogger("studiamo")

# Standalone from the app's own Jinja2Templates (app/main.py): the export report is a static
# file opened from disk, not served by the app, so it never uses url_for or a request context,
# and autoescape must stay on since it renders free-text the user wrote (custom_notes, quiz
# question text) that a stored-XSS payload could otherwise ride into the user's own browser.
_EXPORT_TEMPLATES = Environment(
    loader=FileSystemLoader(Path(__file__).resolve().parent.parent / "templates"),
    autoescape=True,
)


def _parse_bool(val) -> bool:
    """Reliably parse booleans from config JSON or HTML form strings."""
    if isinstance(val, bool):
        return val
    if isinstance(val, str):
        return val.strip().lower() in ("true", "1", "yes")
    return bool(val)


def _safe_float(val, default: float) -> float:
    try:
        if val is None:
            return default
        s = str(val).strip()
        return float(s) if s != "" else default
    except (ValueError, TypeError):
        return default


def _safe_int(val, default: int) -> int:
    try:
        if val is None:
            return default
        s = str(val).strip()
        return int(s) if s != "" else default
    except (ValueError, TypeError):
        return default


@router.get("/settings")
async def get_app_settings(username: str = Depends(get_active_username)):
    """Returns application configuration settings for active user."""
    try:
        user_cfg = config.load_user_config(username)
        conn = database.get_db_connection(username)
        user_uuid = conn.user_uuid
        try:
            cursor = conn.cursor()
            intervals = get_srs_intervals(cursor, user_uuid=user_uuid)
            # Read all dedicated settings columns from user_profile in one query
            cursor.execute(
                """
                SELECT preferred_hour, notification_channel, notifications_enabled,
                       notify_telegram, notify_push, notify_email,
                       notify_cat_quizzes, notify_cat_streak, notify_cat_inactivity,
                       leaderboard_hidden, review_mode, voice_engine, voice_speed,
                       subscription_status, is_tester, ls_ends_at, ls_renews_at
                FROM user_profile WHERE user_uuid = %s LIMIT 1;
                """,
                (user_uuid,)
            )
            settings_row = cursor.fetchone() or {}

            cursor.execute(
                """
                SELECT enable_stage_5_repetition, stage_5_repeat_interval,
                       cap_stages_by_importance, srs_cap_1, srs_cap_2, srs_cap_3, srs_cap_4, srs_cap_5,
                       srs_multiplier_1, srs_multiplier_2, srs_multiplier_3, srs_multiplier_4, srs_multiplier_5,
                       question_count_1, question_count_2, question_count_3, question_count_4, question_count_5
                FROM srs_settings WHERE user_uuid = %s LIMIT 1;
                """,
                (user_uuid,)
            )
            srs_row = cursor.fetchone() or {}
        finally:
            conn.close()

        cap_by_imp = srs_row.get("cap_stages_by_importance", False)

        def _mask_key(k):
            if not k or not isinstance(k, str) or not k.strip():
                return ""
            if len(k) > 8:
                return k[:4] + "****" + k[-4:]
            return "****"

        gemini_key_raw = user_cfg.get("GEMINI_API_KEY") or user_cfg.get("gemini_api_key", "") or ""
        telegram_token_raw = user_cfg.get("TELEGRAM_BOT_TOKEN") or user_cfg.get("telegram_bot_token", "") or ""

        has_custom_srs = bool(srs_row)
        has_custom_question_counts = bool(srs_row)
        has_custom_multipliers = bool(srs_row)
        has_custom_caps = bool(srs_row)

        return {
            "username": username,
            "display_name": user_cfg.get("DISPLAY_NAME") or user_cfg.get("display_name", username),
            "google_email": user_cfg.get("GOOGLE_EMAIL") or user_cfg.get("EMAIL") if user_cfg.get("GOOGLE_ID") else None,
            "google_linked": bool(user_cfg.get("GOOGLE_ID")),
            "app_mode": config.APP_MODE,
            "gemini_api_key_set": bool(gemini_key_raw),
            "gemini_api_key_masked": _mask_key(gemini_key_raw),
            "telegram_bot_token_set": bool(telegram_token_raw),
            "telegram_bot_token_masked": _mask_key(telegram_token_raw),
            "telegram_chat_id": user_cfg.get("TELEGRAM_CHAT_ID") or user_cfg.get("telegram_chat_id", ""),
            "base_url": user_cfg.get("BASE_URL") or user_cfg.get("base_url") or ("https://studiamo.cloud" if config.IS_CLOUD else ""),
            "has_custom_srs": has_custom_srs,
            "has_custom_question_counts": has_custom_question_counts,
            "has_custom_multipliers": has_custom_multipliers,
            "has_custom_caps": has_custom_caps,
            "defaults": {
                "srs_stage_1": config.DEFAULT_SRS_INTERVALS[0],
                "srs_stage_2": config.DEFAULT_SRS_INTERVALS[1],
                "srs_stage_3": config.DEFAULT_SRS_INTERVALS[2],
                "srs_stage_4": config.DEFAULT_SRS_INTERVALS[3],
                "srs_stage_5": config.DEFAULT_SRS_INTERVALS[4],
                "star_count_1": config.DEFAULT_QUESTION_COUNTS[0],
                "star_count_2": config.DEFAULT_QUESTION_COUNTS[1],
                "star_count_3": config.DEFAULT_QUESTION_COUNTS[2],
                "star_count_4": config.DEFAULT_QUESTION_COUNTS[3],
                "star_count_5": config.DEFAULT_QUESTION_COUNTS[4],
            },
            "srs_stage_1": intervals[0],
            "srs_stage_2": intervals[1],
            "srs_stage_3": intervals[2],
            "srs_stage_4": intervals[3],
            "srs_stage_5": intervals[4],
            "srs_intervals": {
                "stage_1_days": intervals[0],
                "stage_2_days": intervals[1],
                "stage_3_days": intervals[2],
                "stage_4_days": intervals[3],
                "stage_5_days": intervals[4],
            },
            "cap_stages_by_importance": _parse_bool(cap_by_imp),
            "srs_multipliers": {
                "multiplier_1": _safe_float(srs_row.get("srs_multiplier_1"), config.DEFAULT_SRS_MULTIPLIERS[0]),
                "multiplier_2": _safe_float(srs_row.get("srs_multiplier_2"), config.DEFAULT_SRS_MULTIPLIERS[1]),
                "multiplier_3": _safe_float(srs_row.get("srs_multiplier_3"), config.DEFAULT_SRS_MULTIPLIERS[2]),
                "multiplier_4": _safe_float(srs_row.get("srs_multiplier_4"), config.DEFAULT_SRS_MULTIPLIERS[3]),
                "multiplier_5": _safe_float(srs_row.get("srs_multiplier_5"), config.DEFAULT_SRS_MULTIPLIERS[4]),
            },
            "srs_caps": {
                "cap_1": _safe_int(srs_row.get("srs_cap_1"), config.DEFAULT_SRS_CAPS[0]),
                "cap_2": _safe_int(srs_row.get("srs_cap_2"), config.DEFAULT_SRS_CAPS[1]),
                "cap_3": _safe_int(srs_row.get("srs_cap_3"), config.DEFAULT_SRS_CAPS[2]),
                "cap_4": _safe_int(srs_row.get("srs_cap_4"), config.DEFAULT_SRS_CAPS[3]),
                "cap_5": _safe_int(srs_row.get("srs_cap_5"), config.DEFAULT_SRS_CAPS[4]),
            },
            "question_counts": {
                "count_1": _safe_int(srs_row.get("question_count_1"), config.DEFAULT_QUESTION_COUNTS[0]),
                "count_2": _safe_int(srs_row.get("question_count_2"), config.DEFAULT_QUESTION_COUNTS[1]),
                "count_3": _safe_int(srs_row.get("question_count_3"), config.DEFAULT_QUESTION_COUNTS[2]),
                "count_4": _safe_int(srs_row.get("question_count_4"), config.DEFAULT_QUESTION_COUNTS[3]),
                "count_5": _safe_int(srs_row.get("question_count_5"), config.DEFAULT_QUESTION_COUNTS[4]),
            },
            # Read directly from dedicated user_profile columns
            "preferred_hour": _safe_int(settings_row.get("preferred_hour"), -1),
            "notification_channel": settings_row.get("notification_channel") or "both",
            "notifications_enabled": _parse_bool(settings_row.get("notifications_enabled", 1)),
            "notify_telegram": _parse_bool(settings_row.get("notify_telegram", 0)),
            "notify_push": _parse_bool(settings_row.get("notify_push", 0)),
            "notify_email": _parse_bool(settings_row.get("notify_email", 0)),
            "notify_cat_quizzes": _parse_bool(settings_row.get("notify_cat_quizzes", 1)),
            "notify_cat_streak": _parse_bool(settings_row.get("notify_cat_streak", 1)),
            "notify_cat_inactivity": _parse_bool(settings_row.get("notify_cat_inactivity", 1)),
            "telegram_managed_bot_username": config.TELEGRAM_MANAGED_BOT_USERNAME if config.IS_CLOUD else "",
            "notification_email": user_cfg.get("GOOGLE_EMAIL") or user_cfg.get("EMAIL") or "",
            "leaderboard_hidden": _parse_bool(settings_row.get("leaderboard_hidden", 0)),
            "review_mode": settings_row.get("review_mode") or "mixed",
            "voice_engine": settings_row.get("voice_engine") or "browser",
            "voice_speed": _safe_float(settings_row.get("voice_speed"), 1.0),
            "enable_stage_5_repetition": _parse_bool(srs_row.get("enable_stage_5_repetition") if srs_row.get("enable_stage_5_repetition") is not None else user_cfg.get("ENABLE_STAGE_5_REPETITION", config.DEFAULT_ENABLE_STAGE_5_REPETITION)),
            "stage_5_repeat_interval": _safe_int(srs_row.get("stage_5_repeat_interval") if srs_row.get("stage_5_repeat_interval") is not None else user_cfg.get("STAGE_5_REPEAT_INTERVAL"), config.DEFAULT_STAGE_5_REPEAT_INTERVAL),
            "subscription_status": settings_row.get("subscription_status") or "inactive",
            # Kept for backward compatibility; `tester` below is the one with the end date.
            "is_tester": _parse_bool(settings_row.get("is_tester", 0)),
            "tester": database.tester_state_payload(database.get_tester_state(username)),
            # So the card can name the date a cancelled subscription actually runs out, and
            # the date an active one renews. 'cancelled' in Lemon Squeezy means "will not
            # renew", not "access ends now", so that date is the one the customer cares
            # about and the one they otherwise have no way to look up in the app.
            "subscription_ends_at": (settings_row.get("ls_ends_at").isoformat()
                                     if settings_row.get("ls_ends_at") else None),
            "subscription_renews_at": (settings_row.get("ls_renews_at").isoformat()
                                       if settings_row.get("ls_renews_at") else None),
            # For the subscribe CTA on this card to name the code, same as the paywall does.
            # Not pre-applied to the checkout URL; see billing.build_checkout_url.
            "beta_discount_code": (config.LEMONSQUEEZY_BETA_DISCOUNT_CODE or "") if config.IS_CLOUD else "",
        }
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"Error fetching settings for {username}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to load settings: {e}")


@router.post("/settings")
async def save_app_settings(
    gemini_api_key: Optional[str] = Form(None),
    telegram_bot_token: Optional[str] = Form(None),
    telegram_chat_id: Optional[str] = Form(None),
    base_url: Optional[str] = Form(None),
    stage_1: Optional[str] = Form(None),
    stage_2: Optional[str] = Form(None),
    stage_3: Optional[str] = Form(None),
    stage_4: Optional[str] = Form(None),
    stage_5: Optional[str] = Form(None),
    cap_stages: Optional[str] = Form(None),
    notifications_enabled: Optional[str] = Form(None),
    notification_channel: Optional[str] = Form(None),
    notify_telegram: Optional[str] = Form(None),
    notify_push: Optional[str] = Form(None),
    notify_email: Optional[str] = Form(None),
    notify_cat_quizzes: Optional[str] = Form(None),
    notify_cat_streak: Optional[str] = Form(None),
    notify_cat_inactivity: Optional[str] = Form(None),
    multiplier_1: Optional[str] = Form(None),
    multiplier_2: Optional[str] = Form(None),
    multiplier_3: Optional[str] = Form(None),
    multiplier_4: Optional[str] = Form(None),
    multiplier_5: Optional[str] = Form(None),
    cap_1: Optional[str] = Form(None),
    cap_2: Optional[str] = Form(None),
    cap_3: Optional[str] = Form(None),
    cap_4: Optional[str] = Form(None),
    cap_5: Optional[str] = Form(None),
    question_count_1: Optional[str] = Form(None),
    question_count_2: Optional[str] = Form(None),
    question_count_3: Optional[str] = Form(None),
    question_count_4: Optional[str] = Form(None),
    question_count_5: Optional[str] = Form(None),
    preferred_hour: Optional[str] = Form(None),
    leaderboard_hidden: Optional[str] = Form(None),
    review_mode: Optional[str] = Form(None),
    voice_engine: Optional[str] = Form(None),
    voice_speed: Optional[str] = Form(None),
    display_name: Optional[str] = Form(None),
    enable_stage_5_repetition: Optional[str] = Form(None),
    stage_5_repeat_interval: Optional[str] = Form(None),
    username: str = Depends(get_active_username)
):
    """Saves user-scoped application settings."""
    try:
        user_cfg = config.load_user_config(username)
        if display_name is not None and display_name.strip():
            clean_name = display_name.strip()
            is_valid, err_msg = moderation.validate_display_name(clean_name)
            if not is_valid:
                raise HTTPException(status_code=400, detail=err_msg)
            user_cfg["display_name"] = clean_name
            user_cfg["DISPLAY_NAME"] = clean_name
        if gemini_api_key:
            user_cfg["gemini_api_key"] = gemini_api_key
            user_cfg["GEMINI_API_KEY"] = gemini_api_key
        if telegram_bot_token:
            user_cfg["telegram_bot_token"] = telegram_bot_token
            user_cfg["TELEGRAM_BOT_TOKEN"] = telegram_bot_token
        if telegram_chat_id is not None:
            user_cfg["telegram_chat_id"] = telegram_chat_id
            user_cfg["TELEGRAM_CHAT_ID"] = telegram_chat_id
        if base_url:
            user_cfg["base_url"] = base_url
            user_cfg["BASE_URL"] = base_url

        conn = database.get_db_connection(username)
        user_uuid = conn.user_uuid
        try:
            cursor = conn.cursor()
            if display_name is not None and display_name.strip():
                cursor.execute("UPDATE user_profile SET display_name = %s WHERE user_uuid = %s;", (display_name.strip(), user_uuid))

            # Handle SRS stage intervals, importance-based stage caps, per-importance interval
            # multipliers, and per-importance quiz question counts. All four groups live in the
            # same srs_settings row, so they're written together in one upsert -- writing them
            # in separate INSERT-if-absent blocks would race (a later insert would hit the row
            # an earlier one just created and fail the UNIQUE constraint on user_uuid).
            has_srs_input = any(s is not None and str(s).strip() != "" for s in [stage_1, stage_2, stage_3, stage_4, stage_5])
            has_cap_input = cap_stages is not None or any(c is not None and str(c).strip() != "" for c in [cap_1, cap_2, cap_3, cap_4, cap_5])
            has_mult_input = any(m is not None and str(m).strip() != "" for m in [multiplier_1, multiplier_2, multiplier_3, multiplier_4, multiplier_5])
            has_qc_input = any(q is not None and str(q).strip() != "" for q in [question_count_1, question_count_2, question_count_3, question_count_4, question_count_5])
            if has_srs_input or has_cap_input or has_mult_input or has_qc_input:
                s1 = int(stage_1) if stage_1 and str(stage_1).isdigit() else config.DEFAULT_SRS_INTERVALS[0]
                s2 = int(stage_2) if stage_2 and str(stage_2).isdigit() else config.DEFAULT_SRS_INTERVALS[1]
                s3 = int(stage_3) if stage_3 and str(stage_3).isdigit() else config.DEFAULT_SRS_INTERVALS[2]
                s4 = int(stage_4) if stage_4 and str(stage_4).isdigit() else config.DEFAULT_SRS_INTERVALS[3]
                s5 = int(stage_5) if stage_5 and str(stage_5).isdigit() else config.DEFAULT_SRS_INTERVALS[4]

                rep_bool = _parse_bool(enable_stage_5_repetition) if enable_stage_5_repetition is not None else config.DEFAULT_ENABLE_STAGE_5_REPETITION
                rep_int = max(1, min(365, int(stage_5_repeat_interval))) if stage_5_repeat_interval is not None and str(stage_5_repeat_interval).strip().isdigit() else config.DEFAULT_STAGE_5_REPEAT_INTERVAL

                cap_bool = _parse_bool(cap_stages) if cap_stages is not None else False
                c1 = int(cap_1) if cap_1 and str(cap_1).isdigit() else config.DEFAULT_SRS_CAPS[0]
                c2 = int(cap_2) if cap_2 and str(cap_2).isdigit() else config.DEFAULT_SRS_CAPS[1]
                c3 = int(cap_3) if cap_3 and str(cap_3).isdigit() else config.DEFAULT_SRS_CAPS[2]
                c4 = int(cap_4) if cap_4 and str(cap_4).isdigit() else config.DEFAULT_SRS_CAPS[3]
                c5 = int(cap_5) if cap_5 and str(cap_5).isdigit() else config.DEFAULT_SRS_CAPS[4]

                m1 = _safe_float(multiplier_1, config.DEFAULT_SRS_MULTIPLIERS[0])
                m2 = _safe_float(multiplier_2, config.DEFAULT_SRS_MULTIPLIERS[1])
                m3 = _safe_float(multiplier_3, config.DEFAULT_SRS_MULTIPLIERS[2])
                m4 = _safe_float(multiplier_4, config.DEFAULT_SRS_MULTIPLIERS[3])
                m5 = _safe_float(multiplier_5, config.DEFAULT_SRS_MULTIPLIERS[4])

                qc1 = int(question_count_1) if question_count_1 and str(question_count_1).isdigit() else config.DEFAULT_QUESTION_COUNTS[0]
                qc2 = int(question_count_2) if question_count_2 and str(question_count_2).isdigit() else config.DEFAULT_QUESTION_COUNTS[1]
                qc3 = int(question_count_3) if question_count_3 and str(question_count_3).isdigit() else config.DEFAULT_QUESTION_COUNTS[2]
                qc4 = int(question_count_4) if question_count_4 and str(question_count_4).isdigit() else config.DEFAULT_QUESTION_COUNTS[3]
                qc5 = int(question_count_5) if question_count_5 and str(question_count_5).isdigit() else config.DEFAULT_QUESTION_COUNTS[4]

                cursor.execute("SELECT COUNT(*) FROM srs_settings WHERE user_uuid = %s;", (user_uuid,))
                if database.first_val(cursor.fetchone()) == 0:
                    cursor.execute(
                        """INSERT INTO srs_settings
                           (user_uuid, stage_1_days, stage_2_days, stage_3_days, stage_4_days, stage_5_days,
                            enable_stage_5_repetition, stage_5_repeat_interval,
                            cap_stages_by_importance, srs_cap_1, srs_cap_2, srs_cap_3, srs_cap_4, srs_cap_5,
                            srs_multiplier_1, srs_multiplier_2, srs_multiplier_3, srs_multiplier_4, srs_multiplier_5,
                            question_count_1, question_count_2, question_count_3, question_count_4, question_count_5)
                           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s);""",
                        (user_uuid, s1, s2, s3, s4, s5, rep_bool, rep_int, cap_bool, c1, c2, c3, c4, c5,
                         m1, m2, m3, m4, m5, qc1, qc2, qc3, qc4, qc5)
                    )
                else:
                    cursor.execute(
                        """UPDATE srs_settings SET
                               stage_1_days=%s, stage_2_days=%s, stage_3_days=%s, stage_4_days=%s, stage_5_days=%s,
                               enable_stage_5_repetition=%s, stage_5_repeat_interval=%s,
                               cap_stages_by_importance=%s, srs_cap_1=%s, srs_cap_2=%s, srs_cap_3=%s, srs_cap_4=%s, srs_cap_5=%s,
                               srs_multiplier_1=%s, srs_multiplier_2=%s, srs_multiplier_3=%s, srs_multiplier_4=%s, srs_multiplier_5=%s,
                               question_count_1=%s, question_count_2=%s, question_count_3=%s, question_count_4=%s, question_count_5=%s
                           WHERE user_uuid=%s;""",
                        (s1, s2, s3, s4, s5, rep_bool, rep_int, cap_bool, c1, c2, c3, c4, c5,
                         m1, m2, m3, m4, m5, qc1, qc2, qc3, qc4, qc5, user_uuid)
                    )
            elif all(s == "" for s in [stage_1, stage_2, stage_3, stage_4, stage_5] if s is not None):
                # User cleared all SRS inputs to revert to global defaults
                cursor.execute("DELETE FROM srs_settings WHERE user_uuid = %s;", (user_uuid,))

            conn.commit()
        finally:
            conn.close()

        # Write all dedicated settings columns directly to user_profile
        conn2 = database.get_db_connection(username)
        user_uuid2 = conn2.user_uuid
        try:
            cur2 = conn2.cursor()
            settings_updates = []
            settings_params = []

            if preferred_hour is not None:
                settings_updates.append("preferred_hour = %s")
                settings_params.append(_safe_int(preferred_hour, -1))

            if leaderboard_hidden is not None:
                settings_updates.append("leaderboard_hidden = %s")
                settings_params.append(1 if _parse_bool(leaderboard_hidden) else 0)

            if review_mode in ["video", "topic", "mixed"]:
                settings_updates.append("review_mode = %s")
                settings_params.append(review_mode)

            if voice_engine in ["browser", "gemini"]:
                user_cfg["voice_engine"] = voice_engine
                user_cfg["VOICE_ENGINE"] = voice_engine
                settings_updates.append("voice_engine = %s")
                settings_params.append(voice_engine)

            if voice_speed is not None:
                sp_val = _safe_float(voice_speed, 1.0)
                user_cfg["voice_speed"] = sp_val
                user_cfg["VOICE_SPEED"] = sp_val
                settings_updates.append("voice_speed = %s")
                settings_params.append(sp_val)

            if notifications_enabled is not None:
                settings_updates.append("notifications_enabled = %s")
                settings_params.append(1 if _parse_bool(notifications_enabled) else 0)

            if notification_channel is not None and notification_channel in ["telegram", "app", "both"]:
                settings_updates.append("notification_channel = %s")
                settings_params.append(notification_channel)

            if notify_telegram is not None:
                settings_updates.append("notify_telegram = %s")
                settings_params.append(_parse_bool(notify_telegram))

            if notify_push is not None:
                settings_updates.append("notify_push = %s")
                settings_params.append(_parse_bool(notify_push))

            if notify_email is not None:
                settings_updates.append("notify_email = %s")
                settings_params.append(_parse_bool(notify_email))

            if notify_cat_quizzes is not None:
                settings_updates.append("notify_cat_quizzes = %s")
                settings_params.append(_parse_bool(notify_cat_quizzes))

            if notify_cat_streak is not None:
                settings_updates.append("notify_cat_streak = %s")
                settings_params.append(_parse_bool(notify_cat_streak))

            if notify_cat_inactivity is not None:
                settings_updates.append("notify_cat_inactivity = %s")
                settings_params.append(_parse_bool(notify_cat_inactivity))

            if settings_updates:
                settings_params.append(user_uuid2)
                cur2.execute(
                    f"UPDATE user_profile SET {', '.join(settings_updates)} WHERE user_uuid = %s;",
                    settings_params
                )
            conn2.commit()
        finally:
            conn2.close()

        config.write_user_config(username, user_cfg)
        return {"status": "success", "message": "Settings saved successfully"}
    except Exception as e:
        logger.error(f"Error saving settings for {username}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to save settings: {e}")


@router.get("/leaderboard")
async def get_leaderboard(username: str = Depends(get_active_username)):
    """Returns gamification leaderboard directly across Supabase user profiles."""
    now = datetime.now(timezone.utc)
    start_of_week = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    # Computed once so every row on the board is judged against the same instant.
    now_naive = now.replace(tzinfo=None)
    
    conn = database.get_db_connection(username)
    cursor = conn.cursor()
    
    try:
        # One query for the whole board. This used to run a weekly-XP SELECT per profile
        # inside the loop below, so ranking N accounts cost N + 1 round trips.
        #
        # Weekly XP comes from xp_events, not quiz_attempts: attempt rows are deleted with
        # their video (routers/videos.py), which silently pushed a user down the weekly board
        # for tidying up their library, and left lifetime XP and weekly XP disagreeing.
        cursor.execute(
            """
            SELECT p.user_uuid, p.username, p.display_name, p.xp, p.level, p.streak,
                   p.last_quiz_at,
                   COALESCE(p.leaderboard_hidden, 0) AS leaderboard_hidden,
                   COALESCE(w.weekly_xp, 0) AS weekly_xp
              FROM user_profile p
              LEFT JOIN (
                    SELECT user_uuid, SUM(xp) AS weekly_xp
                      FROM xp_events
                     WHERE created_at >= %s
                     GROUP BY user_uuid
              ) w ON w.user_uuid = p.user_uuid
             ORDER BY p.xp DESC;
            """,
            (start_of_week,)
        )

        profiles = cursor.fetchall()
        
        all_rankings = []
        for p in profiles:
            u_name = p["username"]
            is_anonymous = bool(p.get("leaderboard_hidden"))

            total_xp = p["xp"] if p.get("xp") is not None else 0
            stored_level = p["level"] if p.get("level") is not None else 1

            # Derived, never the raw column: a streak whose last quiz predates yesterday has
            # lapsed, and only grading writes the stored value. See app/gamification.py.
            streak = gamification.effective_streak(p.get("streak"), p.get("last_quiz_at"), now=now_naive)

            level = max(stored_level, gamification.level_for_xp(total_xp))

            weekly_xp = int(p["weekly_xp"]) if p.get("weekly_xp") is not None else 0
            
            # Hide inactive 0 XP test profiles unless it's the logged-in user
            if total_xp == 0 and weekly_xp == 0 and u_name.lower() != username.lower():
                continue

            # Real username is deliberately not included in the response below:
            # only display_name (already user-editable and already preferred by
            # the frontend). u_name is still used here for internal comparisons
            # (is_self, the inactive-profile filter above) but never sent to the
            # client. When leaderboard_hidden is set, the user stays ranked but
            # their display_name is replaced with "Anonymous" below.
            raw_dn = p.get("display_name") or ""
            safe_dn = moderation.sanitize_leaderboard_name(raw_dn, len(all_rankings) + 1)
            all_rankings.append({
                "display_name": "Anonymous" if is_anonymous else safe_dn,
                "xp": total_xp,
                "weekly_xp": weekly_xp,
                "level": level,
                "streak": streak,
                "is_self": (u_name.lower() == username.lower())
            })

        all_rankings.sort(key=lambda x: (x["weekly_xp"], x["xp"]), reverse=True)

        for idx, r in enumerate(all_rankings, 1):
            r["rank"] = idx
            # Renumbers placeholder names to the final rank. The "Anonymous" guard is
            # belt-and-braces: a hidden user's display_name is set to exactly "Anonymous"
            # above, which satisfies neither arm of the outer condition. This used to also
            # test r.get("is_anonymous"), a key nothing ever puts on these dicts, so that
            # term was always None and contributed nothing.
            if not r["display_name"] or r["display_name"].startswith("Learner "):
                if r["display_name"] != "Anonymous":
                    r["display_name"] = f"Learner {idx}"

        # Top 5 are always visible
        visible_indices = set(range(0, min(5, len(all_rankings))))

        # Find self index
        self_idx = None
        for idx, r in enumerate(all_rankings):
            if r["is_self"]:
                self_idx = idx
                break

        # If self is further down than Top 5, include neighbor above, self, and neighbor below
        if self_idx is not None and self_idx >= 5:
            if self_idx - 1 >= 0:
                visible_indices.add(self_idx - 1)
            visible_indices.add(self_idx)
            if self_idx + 1 < len(all_rankings):
                visible_indices.add(self_idx + 1)

        top_rankings = [all_rankings[i] for i in sorted(visible_indices)]

        return {
            "rankings": top_rankings,
            "period": f"Week of {start_of_week.strftime('%b %d, %Y')}"
        }
    finally:
        conn.close()


@router.post("/settings/review_mode")
async def update_review_mode(
    mode: Optional[str] = Form(None),
    username: str = Depends(get_active_username)
):
    """Updates the review mode (video/topic/mixed) directly in user_profile.

    NOTE: nothing consumes review_mode. It is written here, returned by GET /api/settings and
    bound to a <select>, but no code branches on the value: quizzes.py selects it and then reads
    only xp and level. Its UI control is disabled and labelled "Coming soon" (see index.html)
    until the grouping is actually implemented.

    Three vocabularies disagree and need reconciling first. This endpoint and the bulk settings
    save accept video/topic/mixed, the dropdown offers video/goal, and schema.py defaults to
    'video' while GET /api/settings falls back to 'mixed'. One production row already holds
    'goal', which the check below would now reject.
    """
    if mode not in ["video", "topic", "mixed"]:
        raise HTTPException(status_code=400, detail=f"Invalid review mode '{mode}'. Must be video, topic, or mixed.")
    conn = database.get_db_connection(username)
    user_uuid = conn.user_uuid
    try:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE user_profile SET review_mode = %s WHERE user_uuid = %s;",
            (mode, user_uuid)
        )
        conn.commit()
        return {"status": "ok", "review_mode": mode}
    finally:
        conn.close()


@router.get("/notifications/due")
async def get_due_notifications(username: str = Depends(get_active_username)):
    """Returns due Active Recall quizzes for PWA / Web Push notifications."""
    user_uuid = config.get_user_uuid_from_db(username)
    if not user_uuid:
        return {"due_count": 0, "items": []}
        
    conn = database.get_db_connection(username)
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT q.id, q.video_id, q.next_review_at, v.title AS video_title
            FROM quizzes q
            JOIN videos v ON q.video_id = v.id AND q.user_uuid = v.user_uuid
            WHERE q.user_uuid = %s 
              AND v.is_paused = 0 
              AND v.is_archived = 0 
              AND v.is_watchlist = 0
              AND q.importance_level = v.importance_rating;
        """, (user_uuid,))
        rows = [dict(r) for r in cursor.fetchall()]
        
        now_utc = datetime.now(timezone.utc)
        due_items = []
        for r in rows:
            next_rev = r.get("next_review_at")
            if next_rev:
                try:
                    dt = next_rev if isinstance(next_rev, datetime) else datetime.fromisoformat(str(next_rev))
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    if dt <= now_utc:
                        due_items.append({
                            "id": r["id"],
                            "title": r.get("video_title") or "Lerneinheit"
                        })
                except Exception as e:
                    logger.warning(f"Failed to parse next_review_at={next_rev!r} for quiz id={r.get('id')}: {e}")
        return {
            "due_count": len(due_items),
            "items": due_items
        }
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"Error checking due notifications for {username}: {e}")
        return {"due_count": 0, "items": []}
    finally:
        conn.close()


@router.get("/user/onboarding_status")
async def get_onboarding_status(username: str = Depends(get_active_username)):
    """Returns onboarding status for current user.

    has_seen_updates in the DB is an integer version, not a boolean (see
    config.CURRENT_UPDATE_VERSION): a user has seen the current What's New
    content only if their stored value has caught up to it."""
    conn = database.get_db_connection(username)
    user_uuid = conn.user_uuid
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT has_seen_onboarding, has_seen_updates FROM user_profile WHERE user_uuid = %s;", (user_uuid,))
        row = cursor.fetchone()
        if row:
            return {
                "has_seen_onboarding": bool(row.get("has_seen_onboarding")),
                "has_seen_updates": (row.get("has_seen_updates") or 0) >= config.CURRENT_UPDATE_VERSION
            }
        return {"has_seen_onboarding": False, "has_seen_updates": False}
    finally:
        conn.close()


@router.post("/user/onboarding_status")
async def update_onboarding_status(
    has_seen_onboarding: Optional[str] = Form(None),
    has_seen_updates: Optional[str] = Form(None),
    username: str = Depends(get_active_username)
):
    """Updates onboarding status for current user."""
    conn = database.get_db_connection(username)
    user_uuid = conn.user_uuid
    try:
        cursor = conn.cursor()
        if has_seen_onboarding is not None:
            val = 1 if _parse_bool(has_seen_onboarding) else 0
            cursor.execute("UPDATE user_profile SET has_seen_onboarding = %s WHERE user_uuid = %s;", (val, user_uuid))
        if has_seen_updates is not None:
            val = config.CURRENT_UPDATE_VERSION if _parse_bool(has_seen_updates) else 0
            cursor.execute("UPDATE user_profile SET has_seen_updates = %s WHERE user_uuid = %s;", (val, user_uuid))
        conn.commit()
        return {"status": "ok"}
    finally:
        conn.close()


@router.post("/settings/test-notification")
async def send_test_notification_route(username: str = Depends(get_active_username)):
    """Triggers a test Telegram notification for the active user."""
    from app.telegram_bot import send_telegram_message
    success = await send_telegram_message("🧪 <b>Studiamo Test Notification</b>: Telegram connection test successful!", username)
    if not success:
        raise HTTPException(status_code=400, detail="Telegram notification failed. Please check your Bot Token and Chat ID.")
    return {"status": "success", "message": "Test notification sent successfully! 🔔"}


@router.get("/settings/telegram/connect-link")
async def get_telegram_connect_link(username: str = Depends(get_active_username)):
    """Returns a signed /start deep link for the shared cloud managed Telegram bot."""
    if not config.IS_CLOUD:
        raise HTTPException(status_code=400, detail="Managed Telegram connect is only available in cloud mode.")
    if not config.TELEGRAM_MANAGED_BOT_USERNAME:
        raise HTTPException(status_code=503, detail="Telegram bot is not configured on this server yet.")
    from app.telegram_bot import generate_telegram_link_payload
    payload = generate_telegram_link_payload(username)
    return {"url": f"https://t.me/{config.TELEGRAM_MANAGED_BOT_USERNAME}?start={payload}"}


@router.post("/settings/test-push")
async def send_test_push_route(username: str = Depends(get_active_username)):
    """Triggers a test browser push notification for the active user."""
    from app.webpush_utils import send_user_web_push
    sent = send_user_web_push(username, {
        "title": "🧪 Studiamo Test",
        "body": "Browser push connection test successful!",
        "url": "/#review-section"
    })
    if not sent:
        raise HTTPException(status_code=400, detail="No active browser subscription found. Enable browser notifications first.")
    return {"status": "success", "message": "Test push sent successfully! 🔔"}


@router.post("/settings/test-email")
async def send_test_email_route(username: str = Depends(get_active_username)):
    """Triggers a test notification email for the active user (cloud only, uses account's Google email)."""
    if not config.IS_CLOUD:
        raise HTTPException(status_code=400, detail="Email notifications are only available in cloud mode.")
    user_cfg = config.load_user_config(username)
    email = user_cfg.get("GOOGLE_EMAIL") or user_cfg.get("EMAIL")
    if not email:
        raise HTTPException(status_code=400, detail="No email address on file for this account.")
    from app.email_utils import send_notification_email
    base_url = user_cfg.get("BASE_URL") or ("https://studiamo.cloud" if config.IS_CLOUD else "")
    ok = send_notification_email(
        email,
        "🧪 Studiamo Test Notification",
        "Test successful",
        "This is a test email notification from Studiamo. Your email notifications are working correctly.",
        f"{base_url.rstrip('/')}/app",
        "Open Studiamo"
    )
    if not ok:
        raise HTTPException(status_code=400, detail="Email delivery failed. Please check server email configuration.")
    return {"status": "success", "message": "Test email sent successfully! 📧"}


@router.post("/test/schedule_due_now")
async def test_schedule_due_now(
    _dev_only: None = Depends(require_dev_tools_enabled),
    username: str = Depends(get_active_username),
):
    """Test helper: Marks at least 1 quiz for the active user as due right now and triggers test Telegram message."""
    target_user = username
    user_uuid = config.get_user_uuid_from_db(target_user)
    if not user_uuid:
        raise HTTPException(status_code=400, detail=f"User UUID for '{target_user}' not found")
        
    conn = database.get_db_connection(target_user)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM quizzes WHERE user_uuid = %s LIMIT 1;", (user_uuid,))
        row = cursor.fetchone()
        if not row:
            return {"status": "error", "message": f"Keine Lerneinheiten für User '{target_user}' in der Datenbank gefunden."}
            
        quiz_id = row["id"]
        past_time = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        cursor.execute("UPDATE quizzes SET next_review_at = %s, notified = 0 WHERE id = %s AND user_uuid = %s;", (past_time, quiz_id, user_uuid))
        conn.commit()
        
        from app.telegram_bot import send_telegram_message
        from app.webpush_utils import send_user_web_push
        telegram_sent = await send_telegram_message("🧪 <b>Studiamo Test Notification</b>: 1 review is now due!", target_user)
        web_push_sent = send_user_web_push(target_user, {
            "title": "🧠 1 review due now!",
            "body": f"Reminder for {target_user}: Your review is ready.",
            "url": "/#review-section"
        })
        
        return {
            "status": "success",
            "message": f"Quiz '{quiz_id}' for '{target_user}' is now set to due NOW!",
            "telegram_sent": telegram_sent,
            "web_push_sent": web_push_sent
        }
    finally:
        conn.close()


@router.get("/push/vapid_public_key")
async def get_vapid_key():
    """Returns the VAPID Public Key for client push subscriptions."""
    from app.webpush_utils import get_vapid_public_key
    return {"public_key": get_vapid_public_key()}


@router.post("/push/subscribe")
async def subscribe_push(request: Request, username: str = Depends(get_active_username)):
    """Saves a browser PushSubscription object for the active user."""
    from app.webpush_utils import save_user_push_subscription
    try:
        data = await request.json()
        saved = save_user_push_subscription(username, data)
        return {"status": "ok", "saved": saved, "username": username}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid subscription payload: {e}")


@router.post("/push/unsubscribe")
async def unsubscribe_push(request: Request, username: str = Depends(get_active_username)):
    """Removes a push subscription by endpoint for the active user."""
    from app.webpush_utils import remove_user_push_subscription
    try:
        data = await request.json()
        endpoint = data.get("endpoint") if isinstance(data, dict) else None
        if endpoint:
            remove_user_push_subscription(username, endpoint)
        return {"status": "ok"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid unsubscribe request: {e}")


@router.post("/test/reset_due")
async def test_reset_due(
    _dev_only: None = Depends(require_dev_tools_enabled),
    username: str = Depends(get_active_username),
):
    """Resets all quizzes for the active user back to future dates so nothing is due."""
    target_user = username
    user_uuid = config.get_user_uuid_from_db(target_user)
    if not user_uuid:
        raise HTTPException(status_code=400, detail="User not found")
        
    conn = database.get_db_connection(target_user)
    try:
        cursor = conn.cursor()
        future_time = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
        cursor.execute("UPDATE quizzes SET next_review_at = %s, notified = 0 WHERE user_uuid = %s;", (future_time, user_uuid))
        conn.commit()
        return {"status": "success", "message": f"All due test entries for '{target_user}' have been reset (postponed to tomorrow)."}
    finally:
        conn.close()


@router.post("/settings/profile")
async def update_selfhosted_profile(
    new_username: Optional[str] = Form(None),
    display_name: Optional[str] = Form(None),
    new_password: Optional[str] = Form(None),
    old_password: Optional[str] = Form(None),
    gemini_api_key: Optional[str] = Form(None),
    username: str = Depends(get_active_username)
):
    """Updates self-hosted profile settings: username, display name, password (with old password prompt), anonymous toggle, and BYOK Gemini key."""
    user_cfg = config.load_user_config(username)
    pwd_hash = user_cfg.get("PASSWORD_HASH")

    clean_new_username = None
    if new_username and new_username.strip():
        # Lowercase to match signup (auth.py's create_user and google_callback both
        # lowercase at creation), username is a login handle, not a display label
        # (that's display_name), so there's no reason to let a rename introduce case
        # that new-account creation never allowed in the first place.
        clean_new_username = "".join(c for c in new_username if c.isalnum() or c in ("-", "_")).strip().lower()

    is_changing_username = clean_new_username and clean_new_username != username
    is_changing_password = new_password and new_password.strip()

    if is_changing_password and config.IS_CLOUD:
        # Cloud accounts are Google-SSO-only, don't let a local password
        # credential get attached to one, even by an already-authenticated user.
        raise HTTPException(status_code=403, detail="Password changes are disabled for this deployment. Accounts use Google Sign-In.")

    # Cloud accounts are Google-SSO-only and have no way to know or reset a local
    # password (is_changing_password is already blocked above), so a leftover/stale
    # password_hash on the row must never gate a username or display-name change there.
    upgraded_old_hash = None
    if (is_changing_username or is_changing_password) and not config.IS_CLOUD:
        if pwd_hash:
            if not old_password or not old_password.strip():
                raise HTTPException(status_code=400, detail="Current password is required to verify changes.")
            is_valid_old, upgraded_old_hash = verify_password(old_password, pwd_hash)
            if not is_valid_old:
                raise HTTPException(status_code=400, detail="Current password incorrect.")
        else:
            # No password set yet on this account (e.g. still Google-SSO-only in
            # self-hosted mode), nothing to verify against, so setting an initial
            # password here is intentionally allowed with no old-password check.
            # This is a different case from the login-flow bug: it requires an
            # already-authenticated session, not an anonymous login attempt.
            pass

    updates = {}
    if upgraded_old_hash:
        updates["PASSWORD_HASH"] = upgraded_old_hash
    final_username = username

    if is_changing_username:
        is_valid_u, err_u = moderation.validate_username(clean_new_username)
        if not is_valid_u:
            raise HTTPException(status_code=400, detail=err_u)

        # Case-insensitive: the DB's uniqueness constraint is on lower(username),
        # so "alice" and "Alice" are the same username as far as the app is concerned.
        if clean_new_username.lower() in (u.lower() for u in database.get_all_users()):
            raise HTTPException(status_code=409, detail=f"Username '{clean_new_username}' is already taken.")

        conn = database.get_db_connection(username)
        user_uuid = conn.user_uuid
        try:
            cursor = conn.cursor()
            try:
                cursor.execute("UPDATE user_profile SET username = %s WHERE user_uuid = %s;", (clean_new_username, user_uuid))
                conn.commit()
            except psycopg2.errors.UniqueViolation:
                conn.rollback()
                raise HTTPException(status_code=409, detail=f"Username '{clean_new_username}' is already taken.")
        finally:
            conn.close()
        
        config._username_uuid_cache.pop(username.lower(), None)
        config._username_uuid_cache[clean_new_username.lower()] = user_uuid
        config._uuid_username_cache[user_uuid] = clean_new_username
        final_username = clean_new_username

    if display_name is not None:
        clean_display = display_name.strip()
        if clean_display:
            is_valid_d, err_d = moderation.validate_display_name(clean_display)
            if not is_valid_d:
                raise HTTPException(status_code=400, detail=err_d)
        updates["DISPLAY_NAME"] = clean_display
        conn = database.get_db_connection(final_username)
        user_uuid = conn.user_uuid
        try:
            cursor = conn.cursor()
            cursor.execute("UPDATE user_profile SET display_name = %s WHERE user_uuid = %s;", (clean_display, user_uuid))
            conn.commit()
        finally:
            conn.close()

    if is_changing_password:
        updates["PASSWORD_HASH"] = hash_password(new_password)

    if gemini_api_key is not None:
        clean_key = gemini_api_key.strip()
        if clean_key:
            updates["GEMINI_API_KEY"] = clean_key

    if updates:
        config.write_user_config(final_username, updates)
        config.sync_user_registry()

    # No session cookie to reissue here: yb_session names this account's immutable
    # user_uuid (see dependencies.py), which a username change never touches.
    return {
        "status": "success",
        "message": "Profile updated successfully",
        "username": final_username
    }









# --- Account Data Export & Deletion -----------------------------------------

# Columns never written into an export: secrets and credentials, which are not
# "the user's data" in any useful sense and would turn a downloaded file into a
# way to take over the account it came from.
# This set is matched by column name across every exported table, so a name added here is
# redacted everywhere it appears. Check for collisions before adding a generic one.
_EXPORT_REDACTED_COLUMNS = {
    "password_hash",
    "gemini_api_key",
    "telegram_bot_token",
    "youtube_api_key",
    "subscription_json",
    # tester_access: written by an admin *about* the account, not by the user. The rest of
    # the grant (dates, length, whether it was revoked) is the user's own record and stays
    # in the export; free-text internal notes are not theirs to receive.
    "granted_by",
    "note",
    "revoked_reason",
    # Set by the app, not the user, same as the admin-set tester_access fields above.
    "monthly_budget_usd",
    # Identifies a different account (whoever referred this user), not this user's own record.
    "referred_by",
    # App-recorded UI-state timestamps, not something the user entered or produced.
    "welcome_seen_at",
    "reminder_7d_seen_at",
    "reminder_1d_seen_at",
    "expiry_seen_at",
}


def _json_safe(value):
    """Makes psycopg2 row values JSON-serializable (datetimes, Decimals, memoryviews)."""
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, (bytes, bytearray, memoryview)):
        return bytes(value).decode("utf-8", errors="replace")
    return str(value)


# Vocabulary mirrors the app's own labels (videos.js, settings.js) so the export doesn't
# introduce a second wording for the same states.
_IMPORTANCE_LABELS = {
    1: "Reference Material (1 Star)",
    2: "Basic Concepts (2 Stars)",
    3: "Standard Study (3 Stars)",
    4: "High Detail (4 Stars)",
    5: "Crucial Retention (5 Stars)",
}
_VIDEO_STATUS_LABELS = {"ready": "Ready", "processing": "Importing", "failed": "Import Failed"}


def _fmt_seconds(seconds):
    """Formats a video-offset in seconds as h:mm:ss / m:ss, or None if unavailable."""
    try:
        total = int(seconds)
    except (TypeError, ValueError):
        return None
    m, s = divmod(max(total, 0), 60)
    h, m = divmod(m, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


_STUDIO_TIMESTAMP_RE = re.compile(r"\{\{ts=(\d+)\}\}")


def _render_export_notes(text: str) -> str:
    """custom_notes is Markdown (see videos.js htmlToMarkdown/renderMarkdownSafe) with one
    non-standard extension: a {{ts=N}} chip inserted by the "add timestamp" button, which
    the app's own renderer turns into a clickable [m:ss]. Markdown itself reads fine as
    plain text, but that marker means nothing outside the app, so it's swapped for the same
    label the app displays rather than being exported as-is."""
    return _STUDIO_TIMESTAMP_RE.sub(lambda m: f"[{_fmt_seconds(m.group(1))}]", text)


def _prepare_export_video(row: dict) -> dict:
    video = dict(row)
    video["status_label"] = _VIDEO_STATUS_LABELS.get(
        video.get("status"), (video.get("status") or "Unknown").capitalize()
    )
    video["importance_label"] = _IMPORTANCE_LABELS.get(
        video.get("importance_rating"), f"{video.get('importance_rating')} Star(s)"
    )
    video["outline"] = [
        {**o, "time_label": _fmt_seconds(o.get("timestamp_seconds"))}
        for o in (video.get("outline") or []) if isinstance(o, dict)
    ]
    fact_check = video.get("fact_check") or {}
    if isinstance(fact_check, dict):
        fact_check = dict(fact_check)
        for key in ("disputed_claims", "verified_claims"):
            fact_check[key] = [
                {**c, "time_label": _fmt_seconds(c.get("timestamp_seconds"))}
                for c in (fact_check.get(key) or []) if isinstance(c, dict)
            ]
    video["fact_check"] = fact_check
    video["summary"] = video.get("summary") or []
    return video


def _prepare_export_question(item: dict) -> dict:
    q = dict(item)
    q["time_label"] = _fmt_seconds(q.get("timestamp_seconds"))
    options = q.get("options")
    correct_index = q.get("correct_index")
    if isinstance(options, list) and isinstance(correct_index, int) and 0 <= correct_index < len(options):
        q["correct_option_text"] = options[correct_index]
    return q


def _prepare_export_quiz(row: dict) -> dict:
    """questions_json holds only the questions active for the quiz's *current* SRS stage;
    concept_pool (when present) is the complete set the AI generated across every stage, each
    item carrying its own `stage`. Older quizzes predate concept_pool and have it empty, so
    they fall back to questions_json as their only stage."""
    quiz = dict(row)
    current_stage = quiz.get("srs_stage") or 0
    quiz["stage_label"] = f"Stage {current_stage}"

    pool = [item for item in (quiz.get("concept_pool") or []) if isinstance(item, dict)]
    if pool:
        by_stage: dict = {}
        for item in pool:
            by_stage.setdefault(item.get("stage") or 0, []).append(_prepare_export_question(item))
        stages = [
            {"stage": stage, "stage_label": f"Stage {stage}", "is_current": stage == current_stage, "questions": qs}
            for stage, qs in sorted(by_stage.items(), key=lambda kv: kv[0])
        ]
    else:
        current_questions = [
            _prepare_export_question(item) for item in (quiz.get("questions_json") or []) if isinstance(item, dict)
        ]
        stages = (
            [{"stage": current_stage, "stage_label": quiz["stage_label"], "is_current": True, "questions": current_questions}]
            if current_questions else []
        )

    quiz["stages"] = stages
    quiz["questions"] = [q for stage in stages for q in stage["questions"]]
    return quiz


def _build_export_report_context(export: dict) -> dict:
    """Reshapes the already-redacted export["tables"] dict (see export_user_data) into
    goals -> videos -> quiz nesting for the human-readable report. Never re-queries the
    database, so a column added to _EXPORT_REDACTED_COLUMNS stays redacted here too.

    Deliberately narrower than the full export: this report is the readable layer for the
    goals/videos/quizzes someone actually wants to revisit, not a rendering of every table.
    Telemetry (ai_usage_logs, xp_events), quiz attempt history, recommendations, import
    history, and tester access stay out of the HTML; they're still complete in data.json.
    """
    tables = export["tables"]

    goals_by_id = {g["id"]: dict(g, videos=[], review_quizzes=[]) for g in tables.get("goals", [])}

    quizzes_by_video_id = {}
    for row in tables.get("quizzes", []):
        quiz = _prepare_export_quiz(row)
        if quiz.get("quiz_type") == "goal":
            goal = goals_by_id.get(quiz.get("goal_id"))
            if goal is not None:
                goal["review_quizzes"].append(quiz)
        elif quiz.get("video_id") is not None:
            quizzes_by_video_id[quiz["video_id"]] = quiz

    uncategorized_videos = []
    for row in tables.get("videos", []):
        video = _prepare_export_video(row)
        video["quiz"] = quizzes_by_video_id.get(video["id"])
        goal = goals_by_id.get(video.get("learning_goal_id"))
        (goal["videos"] if goal is not None else uncategorized_videos).append(video)

    goals = sorted(
        goals_by_id.values(),
        key=lambda g: (bool(g.get("is_archived")), g.get("order_index") or 0, g.get("id") or 0),
    )

    profile = dict((tables.get("user_profile") or [{}])[0])
    try:
        profile["badges"] = json.loads(profile.get("badges") or "[]")
    except (TypeError, ValueError):
        profile["badges"] = []

    return {
        "exported_at": export["exported_at"],
        "username": export["username"],
        "profile": profile,
        "goals": goals,
        "uncategorized_videos": uncategorized_videos,
    }


_EXPORT_NAME_STRIP_RE = re.compile(r'[\\/:*?"<>|\x00-\x1f]')


def _safe_export_name(name: Optional[str], fallback: str) -> str:
    """Turns a free-text title into a filesystem-safe name for use as a zip folder/file
    name. Titles are user-authored and unbounded, so this must never let a title escape
    its intended directory (stripped path separators) or collide with reserved names."""
    name = _EXPORT_NAME_STRIP_RE.sub(" ", name or "")
    name = re.sub(r"\s+", " ", name).strip(" .")
    return name[:80].strip(" .,;:-([{") or fallback


def _dedupe_export_name(base: str, seen: dict) -> str:
    count = seen.get(base, 0)
    seen[base] = count + 1
    return base if count == 0 else f"{base} ({count})"


def _export_href(*parts: str) -> str:
    """Zip-relative href for an <a> tag: each path segment percent-encoded on its own so a
    literal '/' inside a title can't be mistaken for a path separator."""
    return "/".join(_urlquote(p, safe="") for p in parts)


def _assign_video_export_paths(video: dict, parent_dir_parts: list, seen: dict) -> None:
    video["dir_name"] = _dedupe_export_name(_safe_export_name(video.get("title"), f"video-{video['id']}"), seen)
    dir_parts = parent_dir_parts + [video["dir_name"]]
    video["export_dir"] = "/".join(dir_parts)
    video["yt_data_href"] = _export_href(*dir_parts, "YT data.html")
    video["back_href"] = "../" * len(dir_parts) + "index.html"

    quiz = video.get("quiz")
    if quiz and quiz.get("questions"):
        video["quiz_href"] = _export_href(*dir_parts, "quizzes", "quiz.html")
        quiz["back_href"] = "../" * (len(dir_parts) + 1) + "index.html"
    else:
        video["quiz_href"] = None

    # notes.txt, not notes.html: it's the user's own words verbatim, not app-generated
    # content, so it gets no HTML wrapper or escaping between them and what they wrote.
    video["notes_href"] = _export_href(*dir_parts, "notes.txt") if video.get("custom_notes") else None


def _assign_export_paths(context: dict) -> None:
    """Assigns filesystem-safe folder names and relative hrefs so the export can be laid
    out as goals/<goal>/<video>/{files, quizzes, YT data.html} rather than one combined
    page. Mutates the goal/video/quiz dicts in context in place."""
    goal_names_seen = {}
    for goal in context["goals"]:
        goal["dir_name"] = _dedupe_export_name(_safe_export_name(goal.get("title"), f"goal-{goal['id']}"), goal_names_seen)
        goal_dir_parts = ["goals", goal["dir_name"]]
        goal["export_dir"] = "/".join(goal_dir_parts)

        review_names_seen = {}
        for rq in goal["review_quizzes"]:
            rq["export_name"] = _dedupe_export_name("review-quiz", review_names_seen) + ".html"
            rq["href"] = _export_href(*goal_dir_parts, rq["export_name"])
            rq["back_href"] = "../" * len(goal_dir_parts) + "index.html"

        video_names_seen = {}
        for video in goal["videos"]:
            _assign_video_export_paths(video, goal_dir_parts, video_names_seen)

    video_names_seen = {}
    for video in context["uncategorized_videos"]:
        _assign_video_export_paths(video, ["uncategorized"], video_names_seen)


def _write_export_tree(zf: zipfile.ZipFile, context: dict, items_dir: Path) -> None:
    """Writes the readable layer as an actual folder tree: goals/<goal>/<video>/ with
    files/, quizzes/, and "YT data.html" nested per video. data.json (written separately,
    unchanged) stays the complete raw copy regardless of how this tree is organized."""
    zf.writestr("index.html", _EXPORT_TEMPLATES.get_template("export/index.html").render(context))

    written_docs = set()

    def write_video(video: dict) -> None:
        zf.writestr(
            f"{video['export_dir']}/YT data.html",
            _EXPORT_TEMPLATES.get_template("export/video.html").render(video=video),
        )
        quiz = video.get("quiz")
        if quiz and quiz.get("questions"):
            zf.writestr(
                f"{video['export_dir']}/quizzes/quiz.html",
                _EXPORT_TEMPLATES.get_template("export/quiz.html").render(quiz=quiz, title=video.get("title")),
            )
        if video.get("custom_notes"):
            zf.writestr(f"{video['export_dir']}/notes.txt", _render_export_notes(video["custom_notes"]))
        if items_dir.is_dir():
            for doc in sorted(items_dir.glob(f"doc_{video['id']}.*")):
                zf.write(doc, arcname=f"{video['export_dir']}/files/{doc.name}")
                written_docs.add(doc.name)

    for goal in context["goals"]:
        for rq in goal["review_quizzes"]:
            zf.writestr(
                f"{goal['export_dir']}/{rq['export_name']}",
                _EXPORT_TEMPLATES.get_template("export/quiz.html").render(
                    quiz=rq, title=f"{goal.get('title')} (goal review)"
                ),
            )
        for video in goal["videos"]:
            write_video(video)

    for video in context["uncategorized_videos"]:
        write_video(video)

    # Safety net: an uploaded document that didn't match any video above (e.g. its video
    # row was deleted separately) still ships rather than silently vanishing from the export.
    if items_dir.is_dir():
        for f in sorted(items_dir.iterdir()):
            if f.is_file() and f.name not in written_docs:
                zf.write(f, arcname=f"files/{f.name}")


@router.get("/user/export")
@limiter.limit("5/minute")
async def export_user_data(request: Request, username: str = Depends(get_active_username)):
    """Downloads everything stored about this account as a ZIP: a human-readable folder
    tree (goals/<goal>/<video>/{files, quizzes, YT data.html}), the raw data.json (one
    entry per table, unaffected by how the tree above is organized), and an index.html
    entry point.

    Exported tables are read from database._USER_DATA_TABLES_DELETE_ORDER, the
    same list account deletion uses, so anything the app stores about a user is
    either in this export or is a secret listed in _EXPORT_REDACTED_COLUMNS.
    """
    import json as _json

    conn = database.get_db_connection(username)
    user_uuid = conn.user_uuid
    export = {
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "username": username,
        "user_uuid": user_uuid,
        "tables": {},
    }
    try:
        cursor = conn.cursor()
        for table in ["user_profile"] + list(database._USER_DATA_TABLES_DELETE_ORDER):
            cursor.execute(f"SELECT * FROM {table} WHERE user_uuid = %s;", (user_uuid,))
            rows = []
            for row in cursor.fetchall():
                rows.append({
                    k: v for k, v in dict(row).items()
                    if k not in _EXPORT_REDACTED_COLUMNS
                })
            export["tables"][table] = rows
    finally:
        conn.close()

    report_context = _build_export_report_context(export)
    _assign_export_paths(report_context)

    # Built in a temp dir rather than in memory: an export includes every
    # uploaded document, which can be far larger than the 20 MB per-file cap.
    tmp_dir = Path(tempfile.mkdtemp(prefix="studiamo_export_"))
    zip_path = tmp_dir / f"studiamo-export-{username}.zip"
    try:
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            items_dir = config.USERS_DIR / user_uuid / "items"
            _write_export_tree(zf, report_context, items_dir)
            zf.writestr(
                "data.json",
                _json.dumps(export, indent=2, ensure_ascii=False, default=_json_safe),
            )
    except Exception:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise

    # FileResponse streams the file, so the temp dir has to outlive this
    # function and is cleaned up once the response has been sent.
    background = BackgroundTask(shutil.rmtree, tmp_dir, ignore_errors=True)
    return FileResponse(
        zip_path,
        media_type="application/zip",
        filename=zip_path.name,
        background=background,
    )


@router.post("/user/delete")
@limiter.limit("3/minute")
async def delete_own_account(
    request: Request,
    confirm_username: str = Form(...),
    username: str = Depends(get_active_username),
):
    """Permanently deletes the caller's own account and all of its data.

    Typing the username back is required as the final confirmation: it is the
    one check that works in both auth modes (cloud accounts are Google SSO and
    have no password to re-enter) and it can't be triggered by a stray click.
    """
    if (confirm_username or "").strip().lower() != username.lower():
        raise HTTPException(
            status_code=400,
            detail="The username you typed does not match your account.",
        )

    result = database.delete_user_account(username, dry_run=False)

    response = JSONResponse({
        "status": "success",
        "deleted_user_uuid": result["user_uuid"],
        "counts": result["counts"],
    })
    # The account is gone; leaving a signed session cookie behind would only
    # produce confusing 401s on the next request.
    for cookie in ("yb_session", "username", "profile_password"):
        response.delete_cookie(cookie, path="/")
    return response
