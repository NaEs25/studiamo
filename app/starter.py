"""The starter set: a few ready-made example videos, with their quizzes, copied into an account
on the free plan so the app has something in it before the learner has spent their one free
generation.

The sets live in starter_sets (system-owned, see app/schema.py) and were captured once from real
imports by scripts/snapshot_starter_set.py. Copying one is an ordinary insert of a material and
a quiz for the account: no AI call, nothing shared between accounts afterwards, and the learner
can delete them like any other material. starter_set_added_at on the profile makes the copy
happen once per account, so deleting the starter set does not bring it back.
"""
import json
import logging

from psycopg2.extras import RealDictCursor

from app import database, local_days, plans
from app.config import IS_CLOUD
from app.dependencies import get_question_counts, select_stage_questions

logger = logging.getLogger("studiamo")

STARTER_IMPORTANCE = 3


def add_starter_set_if_due(username: str) -> int:
    """Copies the active starter sets into the account if it is on the free plan and has not
    had them yet. Returns how many materials were added. Never raises: a failure here must not
    stop the dashboard from loading, and the account simply tries again on its next visit."""
    if not IS_CLOUD:
        return 0
    try:
        if plans.get_plan(username) != plans.PLAN_FREE:
            return 0
        conn = database.get_db_connection(username)
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT 1 FROM starter_sets WHERE active IS TRUE LIMIT 1;")
            if cursor.fetchone() is None:
                return 0
            # The claim on the marker is the lock: of two requests racing for the same account,
            # only the one whose UPDATE matches the NULL goes on to copy.
            cursor.execute(
                """UPDATE user_profile SET starter_set_added_at = CURRENT_TIMESTAMP
                    WHERE user_uuid = %s AND starter_set_added_at IS NULL RETURNING user_uuid;""",
                (conn.user_uuid,),
            )
            if cursor.fetchone() is None:
                conn.commit()
                return 0
            cursor.execute("SELECT * FROM starter_sets WHERE active IS TRUE ORDER BY position, id;")
            sets = [dict(r) for r in cursor.fetchall()]
            target = get_question_counts(username).get(STARTER_IMPORTANCE, 5)
            added = 0
            for entry in sets:
                added += _copy_one(cursor, conn.user_uuid, entry, target)
            conn.commit()
            return added
        finally:
            conn.close()
    except Exception as e:
        logger.warning(f"[starter] Could not add the starter set for '{username}': {e}")
        return 0


def _copy_one(cursor, user_uuid, entry: dict, target: int) -> int:
    cursor.execute("SELECT 1 FROM videos WHERE user_uuid = %s AND youtube_id = %s;", (user_uuid, entry["youtube_id"]))
    if cursor.fetchone():
        return 0  # the account already has this video; it keeps its own copy
    cursor.execute(
        """INSERT INTO videos
           (user_uuid, youtube_id, title, category, thumbnail_url, importance_rating, learning_goal_id,
            is_archived, is_paused, is_watchlist, status, summary, outline, duration_seconds,
            material_type, is_starter)
           VALUES (%s, %s, %s, %s, %s, %s, NULL, 0, 0, 0, 'ready', %s::jsonb, %s::jsonb, %s, 'youtube', TRUE)
           RETURNING id;""",
        (user_uuid, entry["youtube_id"], entry["title"], entry.get("category") or "General",
         entry.get("thumbnail_url"), STARTER_IMPORTANCE, json.dumps(entry["summary"] or []),
         json.dumps(entry["outline"] or []), entry.get("duration_seconds") or 0),
    )
    video_id = cursor.fetchone()["id"]
    pool = entry["concept_pool"] if isinstance(entry["concept_pool"], list) else json.loads(entry["concept_pool"] or "[]")
    active = select_stage_questions(pool, 0, None, target)
    cursor.execute(
        """INSERT INTO quizzes
           (user_uuid, video_id, goal_id, importance_level, srs_stage, next_review_at, quiz_type, in_progress_index,
            concept_pool, questions_json)
           VALUES (%s, %s, NULL, %s, 0, %s, 'video', 0, %s::jsonb, %s::jsonb);""",
        (user_uuid, video_id, STARTER_IMPORTANCE, local_days.utc_now().isoformat(),
         json.dumps(pool), json.dumps(active)),
    )
    return 1
