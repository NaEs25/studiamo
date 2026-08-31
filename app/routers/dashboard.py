import logging
from fastapi import APIRouter, Depends
from app import database, gamification, storage
from app.dependencies import (
    get_active_username,
    require_app_access,
    get_srs_intervals,
    get_srs_caps_and_repetition,
    compute_max_stages,
)
from app.ai import get_usage_status

logger = logging.getLogger("studiamo")

router = APIRouter(prefix="/api", tags=["Dashboard"])


def _attach_video_summaries(video_list: list):
    """Fills summary bullets and custom notes for a list of video dictionary records from in-memory JSONB data."""
    for v in video_list:
        raw_summary = v.get("summary")
        v["summary"] = []
        if v.get("status") == "ready":
            if isinstance(raw_summary, list):
                v["summary"] = [
                    s for s in raw_summary
                    if s and isinstance(s, str) and s.strip()
                    and s.strip().lower() != "no summary available"
                    and not s.strip().lower().startswith("key concept preview for ")
                ]
            elif isinstance(raw_summary, str) and raw_summary.strip() and raw_summary.strip().lower() != "no summary available" and not raw_summary.strip().lower().startswith("key concept preview for "):
                try:
                    import json
                    parsed = json.loads(raw_summary)
                    if isinstance(parsed, list):
                        v["summary"] = [
                            s for s in parsed
                            if s and isinstance(s, str) and s.strip()
                            and s.strip().lower() != "no summary available"
                            and not s.strip().lower().startswith("key concept preview for ")
                        ]
                    else:
                        parsed_str = str(parsed).strip()
                        if not parsed_str.lower().startswith("key concept preview for "):
                            v["summary"] = [parsed_str]
                except Exception:
                    v["summary"] = [raw_summary.strip()]
        elif v.get("status") == "processing":
            v["summary"] = ["Generating content in the background. Please wait..."]
        elif v.get("status") == "failed":
            v["summary"] = [f"Import failed: {v.get('status_error', 'Unknown AI error')}"]


@router.get("/dashboard")
async def get_dashboard_data(username: str = Depends(require_app_access)):
    """Retrieves full aggregated dashboard data: user profile, active/archived goals, videos, and quizzes."""
    conn = database.get_db_connection(username)
    user_uuid = conn.user_uuid
    cursor = conn.cursor()
    
    # 1. Fetch user stats
    try:
        cursor.execute("SELECT xp, level, streak, last_quiz_at, badges, review_mode FROM user_profile WHERE user_uuid = %s LIMIT 1;", (user_uuid,))
        user = cursor.fetchone()
    except Exception as e_prof:
        logger.error(f"Error fetching user profile for {username}: {e_prof}")
        user = None

    user_data = dict(user) if user else {"xp": 0, "level": 1, "streak": 0, "last_quiz_at": None, "badges": "[]", "review_mode": "video"}

    # Self-healing: lift the cached profile total if the XP ledger accounts for more than it.
    # Reads xp_events rather than quiz_attempts because attempts are deleted along with their
    # video, which made this comparison drift downwards and stop firing. Only ever raises the
    # total, so it cannot take XP away from an account.
    try:
        cursor.execute("SELECT COALESCE(SUM(xp), 0) AS total_xp, MAX(created_at) AS last_event FROM xp_events WHERE user_uuid = %s;", (user_uuid,))
        xp_summary = cursor.fetchone()
        if xp_summary and xp_summary.get("total_xp", 0) > user_data.get("xp", 0):
            calc_xp = xp_summary["total_xp"]
            last_event = xp_summary.get("last_event")

            user_data["xp"] = calc_xp
            user_data["level"] = max(user_data.get("level", 1), gamification.level_for_xp(calc_xp))
            if last_event and not user_data.get("last_quiz_at"):
                user_data["last_quiz_at"] = last_event

            cursor.execute(
                "UPDATE user_profile SET xp = %s, level = %s, last_quiz_at = COALESCE(last_quiz_at, %s) WHERE user_uuid = %s;",
                (calc_xp, user_data["level"], last_event, user_uuid)
            )
            conn.commit()
    except Exception as e_sync:
        conn.rollback()
        logger.warning(f"Note on XP self-healing sync for {username}: {e_sync}")

    # A lapsed streak reads as 0 without being written back. This used to expire the streak
    # after 24 rolling hours and UPDATE the zero into user_profile, which ran on every app
    # boot and so always beat the grading path's own rule: quizzing at 9:00 one day and 9:30
    # the next is 24.5 hours apart, and the streak was gone before the second quiz was
    # graded. No account could hold a streak above 1. See app/gamification.py.
    user_data["streak"] = gamification.effective_streak(
        user_data.get("streak"), user_data.get("last_quiz_at")
    )

    # The instant the streak lapses, sent so the frontend countdown reads the rule instead of
    # reimplementing it. app.js used to derive this itself as last_quiz_at + 24 rolling hours,
    # i.e. the exact rule this module replaced, and so displayed an expiry up to a day earlier
    # than the real one. Serialized with an explicit Z because the stored value is naive UTC.
    _streak_deadline = gamification.streak_deadline(user_data.get("last_quiz_at"))
    user_data["streak_deadline"] = _streak_deadline.isoformat() + "Z" if _streak_deadline else None

    # 2. Fetch all learning goals ordered by order_index (non-archived only)
    cursor.execute("""
        SELECT g.id, g.title, g.description, g.order_index,
               CASE WHEN gr.recommendations_json IS NOT NULL AND gr.recommendations_json != '' AND gr.recommendations_json != '{}' THEN 1 ELSE 0 END AS has_saved_recommendations
        FROM goals g
        LEFT JOIN goal_recommendations gr ON g.id = gr.goal_id AND g.user_uuid = gr.user_uuid
        WHERE g.user_uuid = %s AND g.is_archived = 0
        ORDER BY g.order_index ASC, g.id ASC;
    """, (user_uuid,))
    goals = [dict(r) for r in cursor.fetchall()]
    
    # 2b. Fetch archived learning goals
    cursor.execute("""
        SELECT g.id, g.title, g.description, g.order_index,
               CASE WHEN gr.recommendations_json IS NOT NULL AND gr.recommendations_json != '' AND gr.recommendations_json != '{}' THEN 1 ELSE 0 END AS has_saved_recommendations
        FROM goals g
        LEFT JOIN goal_recommendations gr ON g.id = gr.goal_id AND g.user_uuid = gr.user_uuid
        WHERE g.user_uuid = %s AND g.is_archived = 1
        ORDER BY g.order_index ASC, g.id ASC;
    """, (user_uuid,))
    archived_goals = [dict(r) for r in cursor.fetchall()]
    
    # 3. Fetch all active videos with summary
    cursor.execute("""
        SELECT v.id, v.youtube_id, v.title, v.category, v.thumbnail_url,
               v.importance_rating, v.learning_goal_id, v.is_archived, v.is_paused,
               v.status, v.status_error, v.is_watchlist, v.custom_notes,
               v.last_position_seconds, v.duration_seconds, v.is_temporary, v.expires_at, v.summary,
               g.title AS goal_title,
               -- Gates the "Adjust Learning Focus" menu entry. Material imported before topic
               -- extraction existed has an empty pool and would open an empty overlay.
               EXISTS (
                   SELECT 1 FROM quizzes q
                    WHERE q.video_id = v.id AND q.user_uuid = v.user_uuid
                      AND jsonb_array_length(COALESCE(q.concept_pool, '[]'::jsonb)) > 0
               ) AS has_concept_pool
        FROM videos v
        LEFT JOIN goals g ON v.learning_goal_id = g.id
        WHERE v.user_uuid = %s AND v.is_archived = 0
        ORDER BY v.id DESC;
    """, (user_uuid,))
    videos = [dict(r) for r in cursor.fetchall()]

    # 4. Fetch archived videos with summary
    # Same card renderer and same context menu as the active list above, so the two column
    # lists have to agree on everything either of them reads. is_archived and
    # has_concept_pool were missing here: renderVideoCard's menu reads both off
    # _videoCardCache, which the frontend fills from this list too, so every archived
    # material offered "Archive Video" instead of "Send to Active" and never offered
    # "Adjust Learning Focus".
    cursor.execute("""
        SELECT v.id, v.youtube_id, v.title, v.category, v.thumbnail_url, v.importance_rating,
               v.learning_goal_id, v.is_archived, v.is_paused, v.status, v.status_error,
               v.is_watchlist, v.custom_notes, v.summary,
               g.title AS goal_title,
               EXISTS (
                   SELECT 1 FROM quizzes q
                    WHERE q.video_id = v.id AND q.user_uuid = v.user_uuid
                      AND jsonb_array_length(COALESCE(q.concept_pool, '[]'::jsonb)) > 0
               ) AS has_concept_pool
        FROM videos v
        LEFT JOIN goals g ON v.learning_goal_id = g.id
        WHERE v.user_uuid = %s AND v.is_archived = 1;
    """, (user_uuid,))
    archived = [dict(r) for r in cursor.fetchall()]
    
    # 5. Fetch all quizzes
    cursor.execute("""
        SELECT q.id, q.video_id, q.goal_id, q.quiz_type, q.srs_stage, q.next_review_at, q.notified, q.importance_level, q.in_progress_index,
               v.title AS video_title, v.importance_rating, COALESCE(g.title, g2.title) AS goal_title
        FROM quizzes q
        LEFT JOIN videos v ON q.video_id = v.id
        LEFT JOIN goals g ON q.goal_id = g.id
        LEFT JOIN goals g2 ON v.learning_goal_id = g2.id
        WHERE q.user_uuid = %s;
    """, (user_uuid,))
    quizzes = [dict(r) for r in cursor.fetchall()]

    # Each quiz's "mastered" state: has it reached the highest SRS stage it can, given this
    # user's stage-count and (optional) importance-based cap settings. Same rule grade_quiz
    # uses to decide whether to keep scheduling reviews for it.
    intervals = get_srs_intervals(cursor, user_uuid=user_uuid)
    num_stages = len([x for x in intervals if x is not None]) or 5
    srs_caps_cfg = get_srs_caps_and_repetition(cursor, user_uuid=user_uuid)
    for q in quizzes:
        q_importance = q.pop("importance_rating", None) or 3
        q_max_stages = compute_max_stages(srs_caps_cfg["cap_by_importance"], srs_caps_cfg["caps"], q_importance, num_stages)
        q["max_stages"] = q_max_stages
        q["mastered"] = (q.get("srs_stage") or 0) >= q_max_stages

    conn.close()
    
    _attach_video_summaries(videos)
    _attach_video_summaries(archived)
        
    return {
        "user": user_data,
        "goals": goals,
        "archived_goals": archived_goals,
        "videos": videos,
        "archived": archived,
        "quizzes": quizzes
    }


@router.get("/stats")
async def get_ai_stats(username: str = Depends(require_app_access)):
    """Returns AI API usage logs and total call count for the active user."""
    conn = database.get_db_connection(username)
    user_uuid = conn.user_uuid
    try:
        cursor = conn.cursor()
        cursor.execute(
            """SELECT timestamp, action_type, model, prompt_tokens, completion_tokens,
                      cached_tokens, duration_ms, video_id, quiz_id, status, attempts
               FROM ai_usage_logs WHERE user_uuid = %s ORDER BY timestamp DESC LIMIT 100;""",
            (user_uuid,)
        )
        rows = cursor.fetchall()
        logs = []
        for r in rows:
            ts = r.get("timestamp")
            if hasattr(ts, "isoformat"):
                ts = ts.isoformat()
            logs.append({
                "timestamp": str(ts) if ts else "",
                "action_type": r.get("action_type") or "ai_call",
                "model": r.get("model") or "gemini-3.5-flash-lite",
                "prompt_tokens": r.get("prompt_tokens") or 0,
                "completion_tokens": r.get("completion_tokens") or 0,
                "cached_tokens": r.get("cached_tokens") or 0,
                "duration_ms": r.get("duration_ms"),
                "video_id": r.get("video_id"),
                "quiz_id": r.get("quiz_id"),
                "status": r.get("status") or "success",
                "attempts": r.get("attempts") or 1
            })
        return {
            "total_calls": len(logs),
            "logs": logs,
            "usage_status": get_usage_status(username)
        }
    finally:
        conn.close()


@router.get("/stats/history")
async def get_stats_history(username: str = Depends(require_app_access)):
    """Returns active recall quiz attempt statistics and accuracy metrics for the active user.
    quiz_attempts stores one row per graded question (grade='remembered'/'forgot'), not one row
    per quiz, there is no score/total_questions column, so aggregation happens over `grade`."""
    conn = database.get_db_connection(username)
    user_uuid = conn.user_uuid
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT COUNT(*) AS total,
                   SUM(CASE WHEN grade = 'remembered' THEN 1 ELSE 0 END) AS remembered,
                   SUM(CASE WHEN grade = 'forgot' THEN 1 ELSE 0 END) AS forgot
            FROM quiz_attempts
            WHERE user_uuid = %s;
        """, (user_uuid,))
        agg = cursor.fetchone() or {}
        total_attempts = agg.get("total") or 0
        remembered = agg.get("remembered") or 0
        forgot = agg.get("forgot") or 0
        accuracy_pct = round((remembered / total_attempts * 100), 1) if total_attempts > 0 else 0.0

        cursor.execute("""
            SELECT a.id, a.quiz_id, a.question_index, a.question, a.given_answer, a.correct_answer,
                   a.grade, a.created_at, a.explanation, a.feedback,
                   COALESCE(v.title, g.title) AS source_title,
                   COALESCE(q.srs_stage, 0) AS srs_stage,
                   v.importance_rating
            FROM quiz_attempts a
            LEFT JOIN videos v ON a.video_id = v.id
            LEFT JOIN goals g ON a.goal_id = g.id
            LEFT JOIN quizzes q ON a.quiz_id = q.id
            WHERE a.user_uuid = %s
            ORDER BY a.id DESC
            LIMIT 200;
        """, (user_uuid,))
        intervals = get_srs_intervals(cursor, user_uuid=user_uuid)
        num_stages = len([x for x in intervals if x is not None]) or 5
        srs_caps_cfg = get_srs_caps_and_repetition(cursor, user_uuid=user_uuid)
        recent_attempts = []
        for r in cursor.fetchall():
            att = dict(r)
            created_at = att.get("created_at")
            att["created_at"] = created_at.isoformat() if hasattr(created_at, "isoformat") else (str(created_at) if created_at else "")
            att_importance = att.pop("importance_rating", None) or 3
            att_max_stages = compute_max_stages(srs_caps_cfg["cap_by_importance"], srs_caps_cfg["caps"], att_importance, num_stages)
            att["max_stages"] = att_max_stages
            att["mastered"] = (att.get("srs_stage") or 0) >= att_max_stages
            recent_attempts.append(att)

        return {
            "total_attempts": total_attempts,
            "remembered": remembered,
            "forgot": forgot,
            "accuracy_pct": accuracy_pct,
            "recent_attempts": recent_attempts
        }
    finally:
        conn.close()

