"""
Storage Helper Module for Studiamo
Manages completely flat file-based storage: users/<user_uuid>/items/<filename>
Zero subdirectories inside items/ for absolute simplicity and flat hierarchy.
"""
import json
import os
import re
import shutil
import uuid
import logging
from pathlib import Path
from datetime import datetime
from app.database import get_db_connection
from app.config import get_user_dir, get_user_uuid_from_db, get_user_storage_bytes, USERS_DIR

logger = logging.getLogger("studiamo")

def BASE_DIR_USER(username_or_uuid: str) -> Path:
    user_uuid = get_user_uuid_from_db(username_or_uuid)
    if not user_uuid:
        raise ValueError(f"No user_profile row for '{username_or_uuid}' , cannot resolve a user directory.")
    u_dir = USERS_DIR / user_uuid
    u_dir.mkdir(parents=True, exist_ok=True)
    return u_dir

def get_user_items_dir(username: str = "default_user") -> Path:
    """Returns the flat items directory for a user: users/<user_uuid>/items/"""
    items_dir = BASE_DIR_USER(username) / "items"
    items_dir.mkdir(parents=True, exist_ok=True)
    return items_dir

def get_video_dir_path(filename: str, goal_id: int = None, title: str = None, username: str = "default_user") -> Path:
    """Returns the flat user items directory path: users/<user_uuid>/items/"""
    return get_user_items_dir(username)

_SAFE_DOC_EXT_PATTERN = re.compile(r"^\.[a-z0-9]{1,10}$")


def safe_doc_extension(filename) -> str:
    """Extracts a validated file extension from a (possibly hostile) client
    filename. Only the extension token is ever used , never the rest of the
    filename , so directory-traversal characters in the original name can
    never reach a saved path. Falls back to .txt (the format unrecognized
    extensions already get decoded as) if nothing safe is found."""
    ext = Path(filename or "").suffix.lower()
    return ext if _SAFE_DOC_EXT_PATTERN.fullmatch(ext) else ".txt"


def get_document_path(video_id, extension: str, goal_id: int = None, username: str = "default_user") -> Path:
    """Returns the on-disk path for an uploaded document, using one naming
    scheme (doc_<video_id><ext>) shared consistently by save, serve, and
    delete , never the client-supplied filename."""
    ext = extension if _SAFE_DOC_EXT_PATTERN.fullmatch(extension or "") else ".txt"
    return get_video_dir_path(f"doc_{video_id}", goal_id=goal_id, username=username) / f"doc_{video_id}{ext}"

def save_json(filepath: Path, data: dict):
    """Writes a dictionary to a JSON file on disk, formatted nicely."""
    filepath.parent.mkdir(parents=True, exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def load_json(filepath: Path) -> dict:
    """Reads a JSON file from disk and returns a dictionary, safely handling empty or corrupted files."""
    if not filepath.exists():
        return {}
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read().strip()
            if not content:
                return {}
            return json.loads(content)
    except Exception as e:
        logger.warning(f"Failed to parse JSON file {filepath}: {e}")
        return {}


def delete_file(filepath: Path):
    """Deletes a file if it exists."""
    if filepath.exists():
        os.remove(filepath)

def sanitize_folder_name(name: str) -> str:
    import re
    clean = re.sub(r'[\\/*?:"<>|]', "", name).strip()
    return clean if clean else "unnamed_item"

# Video Storage Handlers
def _video_row_key(filename: str, data: dict = None) -> tuple:
    """Resolves the (youtube_key, video_id) a legacy video "filename" refers to.

    Video rows are still addressed here by a filename-shaped string: a bare YouTube id for
    videos, or "doc_<video_id>" for uploaded documents. The document form matches neither
    `youtube_id` (NULL for documents) nor `id::text`, so a WHERE clause built from the string
    alone matched zero rows and silently dropped every document's summary, outline and
    fact_check on write, and returned {} on read. Parsing the id back out is what makes the
    document paths address a real row.
    """
    key = (filename or "").replace("video_", "").replace(".json", "")
    if data and data.get("youtube_id"):
        key = data["youtube_id"]

    video_id = None
    if data and isinstance(data.get("id"), int):
        video_id = data["id"]
    elif key.startswith("doc_"):
        try:
            video_id = int(key[4:])
        except ValueError:
            video_id = None
    return key, video_id


def save_video_json(filename: str, data: dict, username: str = "default_user"):
    """Saves video summary, outline, and fact_check directly to PostgreSQL videos table."""
    from app.database import get_pooled_raw_connection, release_pooled_connection
    import psycopg2.extras
    conn = get_pooled_raw_connection()
    try:
        cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        user_uuid = get_user_uuid_from_db(username)

        summary = json.dumps(data.get("summary") or [])
        outline = json.dumps(data.get("outline") or [])
        fact_check = json.dumps(data.get("fact_check") or {})

        yt_id, video_id = _video_row_key(filename, data)

        cursor.execute("""
            UPDATE videos
            SET summary = %s::jsonb,
                outline = %s::jsonb,
                fact_check = %s::jsonb
            WHERE user_uuid = %s AND (youtube_id = %s OR id::text = %s OR id = %s);
        """, (summary, outline, fact_check, user_uuid, yt_id, yt_id, video_id))
        if cursor.rowcount == 0:
            logger.warning(
                f"save_video_json matched no video row for key '{filename}' (user {username}); "
                "summary/outline/fact_check were not persisted."
            )
        conn.commit()
        cursor.close()
    finally:
        release_pooled_connection(conn)
    return None

def get_video_json(filename: str, username: str = "default_user") -> dict:
    """Loads video summary, outline, and fact_check directly from PostgreSQL videos table."""
    from app.database import get_pooled_raw_connection, release_pooled_connection
    import psycopg2.extras
    conn = get_pooled_raw_connection()
    try:
        cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        user_uuid = get_user_uuid_from_db(username)
        yt_id, video_id = _video_row_key(filename)

        cursor.execute("""
            SELECT id, user_uuid, youtube_id, title, category, thumbnail_url, importance_rating,
                   learning_goal_id, is_archived, is_paused, is_watchlist, custom_notes, status,
                   summary, outline, fact_check, created_at
            FROM videos
            WHERE user_uuid = %s AND (youtube_id = %s OR id::text = %s OR id = %s)
            LIMIT 1;
        """, (user_uuid, yt_id, yt_id, video_id))
        row = cursor.fetchone()
        cursor.close()
        if row:
            d = dict(row)
            if hasattr(d.get("created_at"), "isoformat"):
                d["created_at"] = d["created_at"].isoformat()
            return d
        return {}
    finally:
        release_pooled_connection(conn)

def delete_video_json(filename: str, username: str = "default_user"):
    items_dir = get_user_items_dir(username)
    for ext in [".json", ".pdf", ".txt", ".png", ".jpg", ".jpeg", "_thumb.jpg"]:
        target = items_dir / f"{filename}{ext}"
        if target.exists():
            delete_file(target)

# Quiz Storage Handlers
def save_quiz_json(quiz_id: int, data: dict, username: str = "default_user"):
    """Saves quiz payload questions_json directly to PostgreSQL quizzes table."""
    from app.database import get_pooled_raw_connection, release_pooled_connection
    import psycopg2.extras
    conn = get_pooled_raw_connection()
    try:
        cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        user_uuid = get_user_uuid_from_db(username)
        
        q_list = data.get("questions") or data.get("questions_json") or []
        q_json = json.dumps(q_list)
        srs_stage = data.get("srs_stage")
        next_review = data.get("next_review_at")
        in_prog = data.get("in_progress_index")
        
        cursor.execute("""
            UPDATE quizzes
            SET questions_json = %s::jsonb,
                srs_stage = COALESCE(%s, srs_stage),
                next_review_at = COALESCE(%s::timestamptz, next_review_at),
                in_progress_index = %s
            WHERE user_uuid = %s AND id = %s;
        """, (q_json, srs_stage, next_review, in_prog, user_uuid, quiz_id))
        conn.commit()
        cursor.close()
    finally:
        release_pooled_connection(conn)
    return None

def get_quiz_json(quiz_id: int, username: str = "default_user") -> dict:
    """Loads quiz payload directly from PostgreSQL quizzes table."""
    from app.database import get_pooled_raw_connection, release_pooled_connection
    import psycopg2.extras
    conn = get_pooled_raw_connection()
    try:
        cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        user_uuid = get_user_uuid_from_db(username)
        
        cursor.execute("""
            SELECT id, user_uuid, video_id, goal_id, quiz_type, srs_stage, next_review_at,
                   in_progress_index, questions_json, created_at
            FROM quizzes
            WHERE user_uuid = %s AND id = %s
            LIMIT 1;
        """, (user_uuid, quiz_id))
        row = cursor.fetchone()
        cursor.close()
        if row:
            d = dict(row)
            questions = d.get("questions_json") or []
            if isinstance(questions, str):
                try:
                    questions = json.loads(questions)
                except Exception:
                    questions = []
            return {
                "id": d["id"],
                "video_id": d.get("video_id"),
                "goal_id": d.get("goal_id"),
                "srs_stage": d.get("srs_stage", 0),
                "next_review_at": d.get("next_review_at").isoformat() if hasattr(d.get("next_review_at"), "isoformat") else str(d.get("next_review_at") or ""),
                "in_progress_index": d.get("in_progress_index"),
                "questions": questions
            }
        return {}
    finally:
        release_pooled_connection(conn)

def add_dismissed_recommendation(youtube_id: str, username: str = "default_user"):
    conn = get_db_connection(username)
    user_uuid = conn.user_uuid
    try:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO dismissed_recommendations (user_uuid, youtube_id) VALUES (%s, %s) ON CONFLICT DO NOTHING;",
            (user_uuid, youtube_id)
        )
        conn.commit()
    except Exception as e:
        logger.error(f"Error adding dismissed recommendation for {username}: {e}")
    finally:
        conn.close()

def get_excluded_youtube_ids(username: str = "default_user") -> set:
    conn = get_db_connection(username)
    user_uuid = conn.user_uuid
    excluded = set()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT youtube_id FROM videos WHERE user_uuid = %s AND (is_temporary = 0 OR is_temporary IS NULL) AND youtube_id IS NOT NULL AND youtube_id != '';", (user_uuid,))
        for r in cursor.fetchall():
            if r.get("youtube_id"):
                excluded.add(r["youtube_id"])
                
        cursor.execute("SELECT youtube_id FROM dismissed_recommendations WHERE user_uuid = %s AND youtube_id IS NOT NULL AND youtube_id != '';", (user_uuid,))
        for r in cursor.fetchall():
            if r.get("youtube_id"):
                excluded.add(r["youtube_id"])
    except Exception as e:
        logger.error(f"Error fetching excluded youtube_ids for {username}: {e}")
    finally:
        conn.close()
    return excluded

def save_goal_recommendations(goal_id: int, data: dict, username: str = "default_user"):
    conn = get_db_connection(username)
    user_uuid = conn.user_uuid
    try:
        cursor = conn.cursor()
        json_str = json.dumps(data)
        cursor.execute(
            """INSERT INTO goal_recommendations (user_uuid, goal_id, recommendations_json, updated_at)
               VALUES (%s, %s, %s, CURRENT_TIMESTAMP)
               ON CONFLICT (user_uuid, goal_id) 
               DO UPDATE SET recommendations_json = EXCLUDED.recommendations_json, updated_at = CURRENT_TIMESTAMP;""",
            (user_uuid, goal_id, json_str)
        )
        conn.commit()
    except Exception as e:
        logger.error(f"Error saving goal recommendations for goal {goal_id} ({username}): {e}")
    finally:
        conn.close()

def get_saved_goal_recommendations(goal_id: int, username: str = "default_user") -> dict:
    conn = get_db_connection(username)
    user_uuid = conn.user_uuid
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT recommendations_json FROM goal_recommendations WHERE goal_id = %s AND user_uuid = %s;",
            (goal_id, user_uuid)
        )
        row = cursor.fetchone()
        if row and row.get("recommendations_json"):
            return json.loads(row["recommendations_json"])
    except Exception as e:
        logger.error(f"Error fetching saved goal recommendations for goal {goal_id} ({username}): {e}")
    finally:
        conn.close()
    return None

def clear_daily_recommendation_cache(username: str = "default_user"):
    conn = get_db_connection(username)
    user_uuid = conn.user_uuid
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM daily_recommendations WHERE user_uuid = %s;", (user_uuid,))
        conn.commit()
    except Exception as e:
        logger.error(f"Error clearing daily recommendations for {username}: {e}")
    finally:
        conn.close()

def delete_video_dir(filename: str, goal_id: int = None, username: str = "default_user"):
    delete_video_json(filename, username=username)
