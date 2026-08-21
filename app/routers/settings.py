import os
import shutil
import tempfile
import uuid
import zipfile
import logging
from datetime import datetime, timezone, timedelta
import math
from pathlib import Path
from typing import Optional

import psycopg2.errors
from fastapi import APIRouter, Form, File, UploadFile, HTTPException, Depends, Request
from fastapi.responses import FileResponse, JSONResponse
from starlette.background import BackgroundTask

from app import config, database, storage, ai, moderation
from app.dependencies import (
    get_active_username,
    get_question_counts,
    get_srs_intervals,
    limiter,
    hash_password,
    verify_password,
    require_dev_tools_enabled,
)

router = APIRouter(prefix="/api", tags=["Settings & Backup"])
logger = logging.getLogger("studiamo")


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
                       subscription_status, is_tester
                FROM user_profile WHERE user_uuid = %s LIMIT 1;
                """,
                (user_uuid,)
            )
            settings_row = cursor.fetchone() or {}

            cursor.execute(
                """
                SELECT enable_stage_5_repetition, stage_5_repeat_interval
                FROM srs_settings WHERE user_uuid = %s LIMIT 1;
                """,
                (user_uuid,)
            )
            srs_row = cursor.fetchone() or {}
        finally:
            conn.close()

        cap_by_imp = user_cfg.get("CAP_STAGES_BY_IMPORTANCE") if "CAP_STAGES_BY_IMPORTANCE" in user_cfg else user_cfg.get("cap_stages_by_importance", True)

        def _mask_key(k):
            if not k or not isinstance(k, str) or not k.strip():
                return ""
            if len(k) > 8:
                return k[:4] + "****" + k[-4:]
            return "****"

        gemini_key_raw = user_cfg.get("GEMINI_API_KEY") or user_cfg.get("gemini_api_key", "") or ""
        telegram_token_raw = user_cfg.get("TELEGRAM_BOT_TOKEN") or user_cfg.get("telegram_bot_token", "") or ""

        has_custom_srs = bool(user_cfg.get("srs_stage_1") is not None or user_cfg.get("SRS_STAGE_1") is not None)
        has_custom_question_counts = bool(user_cfg.get("QUESTION_COUNT_1") is not None or user_cfg.get("question_count_1") is not None)
        has_custom_multipliers = bool(user_cfg.get("SRS_MULTIPLIER_1") is not None or user_cfg.get("srs_mult_1") is not None)
        has_custom_caps = bool(user_cfg.get("SRS_CAP_1") is not None or user_cfg.get("srs_cap_1") is not None)

        return {
            "username": username,
            "display_name": user_cfg.get("DISPLAY_NAME") or user_cfg.get("display_name", username),
            "is_anonymous": bool(user_cfg.get("IS_ANONYMOUS", False)),
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
                "multiplier_1": _safe_float(user_cfg.get("SRS_MULTIPLIER_1") if user_cfg.get("SRS_MULTIPLIER_1") is not None else user_cfg.get("srs_mult_1"), config.DEFAULT_SRS_MULTIPLIERS[0]),
                "multiplier_2": _safe_float(user_cfg.get("SRS_MULTIPLIER_2") if user_cfg.get("SRS_MULTIPLIER_2") is not None else user_cfg.get("srs_mult_2"), config.DEFAULT_SRS_MULTIPLIERS[1]),
                "multiplier_3": _safe_float(user_cfg.get("SRS_MULTIPLIER_3") if user_cfg.get("SRS_MULTIPLIER_3") is not None else user_cfg.get("srs_mult_3"), config.DEFAULT_SRS_MULTIPLIERS[2]),
                "multiplier_4": _safe_float(user_cfg.get("SRS_MULTIPLIER_4") if user_cfg.get("SRS_MULTIPLIER_4") is not None else user_cfg.get("srs_mult_4"), config.DEFAULT_SRS_MULTIPLIERS[3]),
                "multiplier_5": _safe_float(user_cfg.get("SRS_MULTIPLIER_5") if user_cfg.get("SRS_MULTIPLIER_5") is not None else user_cfg.get("srs_mult_5"), config.DEFAULT_SRS_MULTIPLIERS[4]),
            },
            "srs_caps": {
                "cap_1": _safe_int(user_cfg.get("SRS_CAP_1") if user_cfg.get("SRS_CAP_1") is not None else user_cfg.get("srs_cap_1"), config.DEFAULT_SRS_CAPS[0]),
                "cap_2": _safe_int(user_cfg.get("SRS_CAP_2") if user_cfg.get("SRS_CAP_2") is not None else user_cfg.get("srs_cap_2"), config.DEFAULT_SRS_CAPS[1]),
                "cap_3": _safe_int(user_cfg.get("SRS_CAP_3") if user_cfg.get("SRS_CAP_3") is not None else user_cfg.get("srs_cap_3"), config.DEFAULT_SRS_CAPS[2]),
                "cap_4": _safe_int(user_cfg.get("SRS_CAP_4") if user_cfg.get("SRS_CAP_4") is not None else user_cfg.get("srs_cap_4"), config.DEFAULT_SRS_CAPS[3]),
                "cap_5": _safe_int(user_cfg.get("SRS_CAP_5") if user_cfg.get("SRS_CAP_5") is not None else user_cfg.get("srs_cap_5"), config.DEFAULT_SRS_CAPS[4]),
            },
            "question_counts": {
                "count_1": _safe_int(user_cfg.get("QUESTION_COUNT_1") if user_cfg.get("QUESTION_COUNT_1") is not None else user_cfg.get("question_count_1"), config.DEFAULT_QUESTION_COUNTS[0]),
                "count_2": _safe_int(user_cfg.get("QUESTION_COUNT_2") if user_cfg.get("QUESTION_COUNT_2") is not None else user_cfg.get("question_count_2"), config.DEFAULT_QUESTION_COUNTS[1]),
                "count_3": _safe_int(user_cfg.get("QUESTION_COUNT_3") if user_cfg.get("QUESTION_COUNT_3") is not None else user_cfg.get("question_count_3"), config.DEFAULT_QUESTION_COUNTS[2]),
                "count_4": _safe_int(user_cfg.get("QUESTION_COUNT_4") if user_cfg.get("QUESTION_COUNT_4") is not None else user_cfg.get("question_count_4"), config.DEFAULT_QUESTION_COUNTS[3]),
                "count_5": _safe_int(user_cfg.get("QUESTION_COUNT_5") if user_cfg.get("QUESTION_COUNT_5") is not None else user_cfg.get("question_count_5"), config.DEFAULT_QUESTION_COUNTS[4]),
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
            "voice_speed": _safe_float(settings_row.get("voice_speed"), 1.25),
            "enable_stage_5_repetition": _parse_bool(srs_row.get("enable_stage_5_repetition") if srs_row.get("enable_stage_5_repetition") is not None else user_cfg.get("ENABLE_STAGE_5_REPETITION", config.DEFAULT_ENABLE_STAGE_5_REPETITION)),
            "stage_5_repeat_interval": _safe_int(srs_row.get("stage_5_repeat_interval") if srs_row.get("stage_5_repeat_interval") is not None else user_cfg.get("STAGE_5_REPEAT_INTERVAL"), config.DEFAULT_STAGE_5_REPEAT_INTERVAL),
            "subscription_status": settings_row.get("subscription_status") or "inactive",
            "is_tester": _parse_bool(settings_row.get("is_tester", 0)),
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

            # Handle SRS stage intervals
            has_srs_input = any(s is not None and str(s).strip() != "" for s in [stage_1, stage_2, stage_3, stage_4, stage_5])
            if has_srs_input:
                s1 = int(stage_1) if stage_1 and str(stage_1).isdigit() else config.DEFAULT_SRS_INTERVALS[0]
                s2 = int(stage_2) if stage_2 and str(stage_2).isdigit() else config.DEFAULT_SRS_INTERVALS[1]
                s3 = int(stage_3) if stage_3 and str(stage_3).isdigit() else config.DEFAULT_SRS_INTERVALS[2]
                s4 = int(stage_4) if stage_4 and str(stage_4).isdigit() else config.DEFAULT_SRS_INTERVALS[3]
                s5 = int(stage_5) if stage_5 and str(stage_5).isdigit() else config.DEFAULT_SRS_INTERVALS[4]

                rep_bool = _parse_bool(enable_stage_5_repetition) if enable_stage_5_repetition is not None else config.DEFAULT_ENABLE_STAGE_5_REPETITION
                rep_int = max(1, min(365, int(stage_5_repeat_interval))) if stage_5_repeat_interval is not None and str(stage_5_repeat_interval).strip().isdigit() else config.DEFAULT_STAGE_5_REPEAT_INTERVAL

                cursor.execute("SELECT COUNT(*) FROM srs_settings WHERE user_uuid = %s;", (user_uuid,))
                if database.first_val(cursor.fetchone()) == 0:
                    cursor.execute(
                        "INSERT INTO srs_settings (user_uuid, stage_1_days, stage_2_days, stage_3_days, stage_4_days, stage_5_days, enable_stage_5_repetition, stage_5_repeat_interval) VALUES (%s, %s, %s, %s, %s, %s, %s, %s);",
                        (user_uuid, s1, s2, s3, s4, s5, rep_bool, rep_int)
                    )
                else:
                    cursor.execute(
                        "UPDATE srs_settings SET stage_1_days=%s, stage_2_days=%s, stage_3_days=%s, stage_4_days=%s, stage_5_days=%s, enable_stage_5_repetition=%s, stage_5_repeat_interval=%s WHERE user_uuid=%s;",
                        (s1, s2, s3, s4, s5, rep_bool, rep_int, user_uuid)
                    )
                user_cfg["srs_stage_1"] = s1
                user_cfg["srs_stage_2"] = s2
                user_cfg["srs_stage_3"] = s3
                user_cfg["srs_stage_4"] = s4
                user_cfg["srs_stage_5"] = s5
            elif all(s == "" for s in [stage_1, stage_2, stage_3, stage_4, stage_5] if s is not None):
                # User cleared all SRS inputs to revert to global defaults
                cursor.execute("DELETE FROM srs_settings WHERE user_uuid = %s;", (user_uuid,))
                for k in ["srs_stage_1", "srs_stage_2", "srs_stage_3", "srs_stage_4", "srs_stage_5", "SRS_STAGE_1"]:
                    user_cfg.pop(k, None)

            conn.commit()
        finally:
            conn.close()

        # Handle Question Counts
        has_qc_input = any(q is not None and str(q).strip() != "" for q in [question_count_1, question_count_2, question_count_3, question_count_4, question_count_5])
        if has_qc_input:
            user_cfg["QUESTION_COUNT_1"] = user_cfg["question_count_1"] = int(question_count_1) if question_count_1 and str(question_count_1).isdigit() else config.DEFAULT_QUESTION_COUNTS[0]
            user_cfg["QUESTION_COUNT_2"] = user_cfg["question_count_2"] = int(question_count_2) if question_count_2 and str(question_count_2).isdigit() else config.DEFAULT_QUESTION_COUNTS[1]
            user_cfg["QUESTION_COUNT_3"] = user_cfg["question_count_3"] = int(question_count_3) if question_count_3 and str(question_count_3).isdigit() else config.DEFAULT_QUESTION_COUNTS[2]
            user_cfg["QUESTION_COUNT_4"] = user_cfg["question_count_4"] = int(question_count_4) if question_count_4 and str(question_count_4).isdigit() else config.DEFAULT_QUESTION_COUNTS[3]
            user_cfg["QUESTION_COUNT_5"] = user_cfg["question_count_5"] = int(question_count_5) if question_count_5 and str(question_count_5).isdigit() else config.DEFAULT_QUESTION_COUNTS[4]
        elif all(q == "" for q in [question_count_1, question_count_2, question_count_3, question_count_4, question_count_5] if q is not None):
            for i in range(1, 6):
                user_cfg.pop(f"QUESTION_COUNT_{i}", None)
                user_cfg.pop(f"question_count_{i}", None)

        if enable_stage_5_repetition is not None:
            val_bool = _parse_bool(enable_stage_5_repetition)
            user_cfg["ENABLE_STAGE_5_REPETITION"] = val_bool
            user_cfg["enable_stage_5_repetition"] = val_bool

        if stage_5_repeat_interval is not None and str(stage_5_repeat_interval).strip().isdigit():
            val_int = max(1, min(365, int(stage_5_repeat_interval)))
            user_cfg["STAGE_5_REPEAT_INTERVAL"] = val_int
            user_cfg["stage_5_repeat_interval"] = val_int

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
                sp_val = _safe_float(voice_speed, 1.25)
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
    
    conn = database.get_db_connection(username)
    cursor = conn.cursor()
    
    try:
        # Include leaderboard_hidden column directly, no per-user config lookup needed
        cursor.execute(
            "SELECT user_uuid, username, display_name, xp, level, streak, last_quiz_at, "
            "COALESCE(leaderboard_hidden, 0) AS leaderboard_hidden "
            "FROM user_profile ORDER BY xp DESC;"
        )

        profiles = cursor.fetchall()
        
        all_rankings = []
        for p in profiles:
            u_uuid = p["user_uuid"]
            u_name = p["username"]
            is_anonymous = bool(p.get("leaderboard_hidden"))

            total_xp = p["xp"] if p.get("xp") is not None else 0
            stored_level = p["level"] if p.get("level") is not None else 1
            streak = p["streak"] if p.get("streak") is not None else 0
            
            calc_level = math.floor(math.sqrt(total_xp / 50)) + 1 if total_xp >= 0 else 1
            level = max(stored_level, calc_level)
            
            cursor.execute("""
                SELECT COALESCE(SUM(xp_gained), 0) AS weekly_xp 
                FROM quiz_attempts 
                WHERE user_uuid = %s AND created_at >= %s;
            """, (u_uuid, start_of_week))
            w_row = cursor.fetchone()
            weekly_xp = int(w_row["weekly_xp"]) if w_row and w_row.get("weekly_xp") is not None else 0
            
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
            if not r["display_name"] or r["display_name"].startswith("Learner "):
                if not r.get("is_anonymous") and r["display_name"] != "Anonymous":
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
    username: str = Depends(get_active_username),
    _dev_only: None = Depends(require_dev_tools_enabled),
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
    username: str = Depends(get_active_username),
    _dev_only: None = Depends(require_dev_tools_enabled),
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
    is_anonymous: Optional[bool] = Form(None),
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

    if is_anonymous is not None:
        updates["IS_ANONYMOUS"] = bool(is_anonymous)

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
_EXPORT_REDACTED_COLUMNS = {
    "password_hash",
    "gemini_api_key",
    "telegram_bot_token",
    "youtube_api_key",
    "subscription_json",
}


def _json_safe(value):
    """Makes psycopg2 row values JSON-serializable (datetimes, Decimals, memoryviews)."""
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, (bytes, bytearray, memoryview)):
        return bytes(value).decode("utf-8", errors="replace")
    return str(value)


@router.get("/user/export")
@limiter.limit("5/minute")
async def export_user_data(request: Request, username: str = Depends(get_active_username)):
    """Downloads everything stored about this account as a ZIP: one JSON file
    per table plus every uploaded document.

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

    # Built in a temp dir rather than in memory: an export includes every
    # uploaded document, which can be far larger than the 20 MB per-file cap.
    tmp_dir = Path(tempfile.mkdtemp(prefix="studiamo_export_"))
    zip_path = tmp_dir / f"studiamo-export-{username}.zip"
    try:
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(
                "data.json",
                _json.dumps(export, indent=2, ensure_ascii=False, default=_json_safe),
            )
            items_dir = config.USERS_DIR / user_uuid / "items"
            if items_dir.is_dir():
                for f in sorted(items_dir.iterdir()):
                    if f.is_file():
                        zf.write(f, arcname=f"files/{f.name}")
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
