"""
Storage helpers for the files Studiamo keeps on disk: uploaded documents under
users/<user_uuid>/items/, plus the small set of DB-backed lookups the recommendation
flows use.

This module used to also carry save/get_video_json and save/get_quiz_json, a leftover of a
file-based era that had become a JSON-document facade over relational tables. They took a
filename-shaped key, resolved it against two columns with an OR, and persisted a hardcoded
subset of whatever dict they were handed while silently discarding the rest. Reads returned
rich dicts, writes kept three fields, and nothing reported the mismatch: that is how every
document's analysis was lost, how four fifths of each import's questions were discarded, and
how a quiz payload could claim a video_filename the frontend then read as undefined. Callers
now read and write the columns they mean, keyed on a primary key, via app.database.
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

_SAFE_DOC_EXT_PATTERN = re.compile(r"^\.[a-z0-9]{1,10}$")


def safe_doc_extension(filename) -> str:
    """Extracts a validated file extension from a (possibly hostile) client
    filename. Only the extension token is ever used , never the rest of the
    filename , so directory-traversal characters in the original name can
    never reach a saved path. Falls back to .txt (the format unrecognized
    extensions already get decoded as) if nothing safe is found."""
    ext = Path(filename or "").suffix.lower()
    return ext if _SAFE_DOC_EXT_PATTERN.fullmatch(ext) else ".txt"


def get_document_path(video_id, extension: str, username: str = "default_user") -> Path:
    """Returns the on-disk path for an uploaded document, using one naming
    scheme (doc_<video_id><ext>) shared consistently by save, serve, and
    delete , never the client-supplied filename."""
    ext = extension if _SAFE_DOC_EXT_PATTERN.fullmatch(extension or "") else ".txt"
    return get_user_items_dir(username) / f"doc_{video_id}{ext}"

def delete_file(filepath: Path):
    """Deletes a file if it exists."""
    if filepath.exists():
        os.remove(filepath)

# Video Storage Handlers
def delete_video_json(filename: str, username: str = "default_user"):
    items_dir = get_user_items_dir(username)
    for ext in [".json", ".pdf", ".txt", ".png", ".jpg", ".jpeg", "_thumb.jpg"]:
        target = items_dir / f"{filename}{ext}"
        if target.exists():
            delete_file(target)

# Quiz Storage Handlers
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
