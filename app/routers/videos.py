import os
import json
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Depends
from fastapi.responses import FileResponse

from app import config, database, storage, ai, youtube
from app.import_manager import ImportQueueManager
from app.ai import UsageLimitExceeded
from app.dependencies import (
    get_active_username,
    get_question_counts,
    get_srs_multipliers,
    get_srs_intervals,
    get_preferred_hour,
    adjust_next_review,
    require_app_access,
    build_concept_pool,
    select_stage_questions,
    STAGE_KEYS,
)

logger = logging.getLogger("studiamo")

router = APIRouter(prefix="/api", tags=["Videos & Content"])


@router.get("/videos/import-tasks")
async def get_import_tasks_route(username: str = Depends(require_app_access)):
    """Returns active and recent import backlog tasks."""
    return ImportQueueManager.get_instance().get_user_backlog(username)


@router.post("/videos/import-tasks/{task_id}/retry")
async def retry_import_task_route(task_id: int, username: str = Depends(require_app_access)):
    """Retries a failed import backlog task."""
    success = ImportQueueManager.get_instance().retry_task(task_id, username)
    if not success:
        raise HTTPException(status_code=404, detail="Task not found")
    return {"status": "success", "task_id": task_id}


@router.delete("/videos/import-tasks/{task_id}")
async def dismiss_import_task_route(task_id: int, username: str = Depends(require_app_access)):
    """Dismisses/deletes an import task from backlog view."""
    success = ImportQueueManager.get_instance().dismiss_task(task_id, username)
    if not success:
        raise HTTPException(status_code=404, detail="Task not found")
    return {"status": "success", "task_id": task_id}


@router.post("/videos")
async def add_content(
    url: Optional[str] = Form(None),
    text_content: Optional[str] = Form(None),
    title: Optional[str] = Form(None),
    importance_rating: int = Form(3),
    learning_goal_id: Optional[int] = Form(None),
    is_watchlist: int = Form(0),
    file: Optional[UploadFile] = File(None),
    username: str = Depends(require_app_access)
):
    """Enqueues video, PDF document, or text notes processing in the background via persistent task queue."""
    if not config.is_configured(username):
        raise HTTPException(status_code=400, detail="App is not configured yet. Complete the setup wizard.")
        
    placeholder_title = "Processing Content..."
    placeholder_thumb = "/static/images/notes-icon.svg"
    yt_id = None
    task_type = "youtube"
    payload = {
        "url": url,
        "title": title,
        "importance_rating": importance_rating,
        "learning_goal_id": learning_goal_id,
        "is_watchlist": is_watchlist
    }

    if url and url.strip():
        yt_id = youtube.extract_video_id(url)
        if not yt_id:
            raise HTTPException(status_code=400, detail="Invalid YouTube URL.")
        placeholder_title = f"YouTube Video ({yt_id})"
        placeholder_thumb = f"https://img.youtube.com/vi/{yt_id}/hqdefault.jpg"
        task_type = "youtube"
    elif file:
        placeholder_title = title.strip() if (title and title.strip()) else file.filename
        placeholder_thumb = "/static/images/document-icon.svg"
        task_type = "document"
    elif text_content and text_content.strip():
        placeholder_title = title.strip() if (title and title.strip()) else f"Notes ({datetime.now().strftime('%Y-%m-%d')})"
        placeholder_thumb = "/static/images/notes-icon.svg"
        task_type = "notes"
        payload["text_content"] = text_content
    else:
        raise HTTPException(status_code=400, detail="Provide a YouTube URL, uploaded PDF/Text, or pasted notes.")
        
    conn = database.get_db_connection(username)
    cursor = conn.cursor()
    
    if yt_id:
        user_uuid = conn.user_uuid
        cursor.execute("SELECT id, status, is_watchlist, is_temporary FROM videos WHERE youtube_id = %s AND user_uuid = %s;", (yt_id, user_uuid))
        existing = cursor.fetchone()
        if existing:
            if existing["status"] == "failed" or existing.get("is_temporary") == 1 or existing.get("is_temporary") == True:
                cursor.execute("UPDATE videos SET status = 'processing', status_error = NULL, is_temporary = 0, expires_at = NULL WHERE id = %s AND user_uuid = %s;", (existing["id"], user_uuid))
                if is_watchlist == 1:
                    cursor.execute("UPDATE videos SET is_watchlist = 1 WHERE id = %s AND user_uuid = %s;", (existing["id"], user_uuid))
                conn.commit()
                conn.close()
                task_id = ImportQueueManager.get_instance().enqueue_task(
                    username=username,
                    task_type="youtube",
                    title=placeholder_title,
                    payload=payload,
                    video_id=existing["id"]
                )
                return {"status": "processing", "video_id": existing["id"], "task_id": task_id, "retrying": True}
            elif is_watchlist == 1:
                cursor.execute("UPDATE videos SET is_watchlist = 1 WHERE id = %s AND user_uuid = %s;", (existing["id"], user_uuid))
                conn.commit()
                conn.close()
                return {"status": "success", "video_id": existing["id"], "already_existed": True}
            conn.close()
            raise HTTPException(status_code=400, detail="This content has already been processed.")
            
    user_uuid = conn.user_uuid
    cursor.execute(
        """INSERT INTO videos 
           (user_uuid, youtube_id, title, category, thumbnail_url, importance_rating, learning_goal_id, is_archived, is_paused, is_watchlist, status)
           VALUES (%s, %s, %s, 'Processing', %s, %s, %s, 0, 0, %s, 'processing') RETURNING id;""",
        (user_uuid, yt_id, placeholder_title, placeholder_thumb, importance_rating, learning_goal_id, is_watchlist)
    )
    res = cursor.fetchone()
    video_id = res["id"] if isinstance(res, dict) and "id" in res else (res[0] if res else cursor.lastrowid)
    conn.commit()
    conn.close()
    
    if file:
        user_quota = config.get_user_storage_quota_bytes()
        if user_quota > 0 and config.get_user_storage_bytes(username) >= user_quota:
            quota_gb = user_quota / (1024 * 1024 * 1024)
            quota_str = f"{quota_gb:.0f} GB" if quota_gb >= 1 else f"{user_quota / (1024 * 1024):.0f} MB"
            raise HTTPException(
                status_code=413,
                detail=f"You've reached your {quota_str} storage limit. Delete some videos or documents before uploading more.",
            )

        max_file_bytes = config.get_max_file_upload_bytes()
        if max_file_bytes > 0:
            file_bytes = await file.read(max_file_bytes + 1)
            if len(file_bytes) > max_file_bytes:
                max_mb = max_file_bytes / (1024 * 1024)
                size_str = f"{max_mb:.0f}MB" if max_mb >= 1 else f"{max_file_bytes // 1024}KB"
                raise HTTPException(status_code=413, detail=f"Uploaded file is too large (maximum size is {size_str}).")
        else:
            file_bytes = await file.read()
        
        # Written straight to its permanent items/doc_<video_id><ext> home, the
        # same path serve_video_document() reads and delete_video() removes.
        # It used to land in a separate uploads/ staging copy that the importer
        # then duplicated into items/ and nobody ever deleted, so every document
        # upload leaked a second copy against the user's 2 GB quota.
        # Only a validated extension is taken from the client filename, never
        # the filename itself, so a crafted name (e.g. containing "../") can't
        # write outside this directory.
        safe_ext = storage.safe_doc_extension(file.filename)
        saved_file_path = storage.get_document_path(
            video_id, safe_ext, goal_id=learning_goal_id, username=username
        )
        saved_file_path.write_bytes(file_bytes)
        payload["file_path"] = str(saved_file_path)
        payload["original_filename"] = file.filename

    task_id = ImportQueueManager.get_instance().enqueue_task(
        username=username,
        task_type=task_type,
        title=placeholder_title,
        payload=payload,
        video_id=video_id
    )
    
    return {"status": "processing", "video_id": video_id, "task_id": task_id, "title": placeholder_title}


@router.post("/videos/{video_id}/retry")
async def retry_video_import_route(
    video_id: int,
    username: str = Depends(require_app_access)
):
    """Retries a failed video/document import task via ImportQueueManager."""
    conn = database.get_db_connection(username)
    user_uuid = conn.user_uuid
    cursor = conn.cursor()
    cursor.execute("SELECT id, youtube_id, title, importance_rating, learning_goal_id FROM videos WHERE id = %s AND user_uuid = %s;", (video_id, user_uuid))
    video = cursor.fetchone()
    if not video:
        conn.close()
        raise HTTPException(status_code=404, detail="Video not found")
        
    cursor.execute("UPDATE videos SET status = 'processing', status_error = NULL WHERE id = %s AND user_uuid = %s;", (video_id, user_uuid))
    
    # Check if existing task in import_tasks table
    cursor.execute("SELECT id FROM import_tasks WHERE video_id = %s AND user_uuid = %s ORDER BY id DESC LIMIT 1;", (video_id, user_uuid))
    task_row = cursor.fetchone()
    conn.commit()
    conn.close()
    
    if task_row:
        task_id = task_row["id"]
        success = ImportQueueManager.get_instance().retry_task(task_id, username)
        return {"status": "processing", "video_id": video_id, "task_id": task_id}
    else:
        url = f"https://www.youtube.com/watch?v={video['youtube_id']}" if video.get("youtube_id") else None
        task_type = "youtube" if video.get("youtube_id") else "document"
        payload = {
            "url": url,
            "title": video["title"],
            "importance_rating": video["importance_rating"],
            "learning_goal_id": video["learning_goal_id"],
            "is_watchlist": 0
        }
        task_id = ImportQueueManager.get_instance().enqueue_task(
            username=username,
            task_type=task_type,
            title=video["title"],
            payload=payload,
            video_id=video_id
        )
        return {"status": "processing", "video_id": video_id, "task_id": task_id}


def _resolve_video_document(video_id: int, username: str) -> Path:
    conn = database.get_db_connection(username)
    user_uuid = conn.user_uuid
    cursor = conn.cursor()
    cursor.execute("SELECT learning_goal_id FROM videos WHERE id = %s AND user_uuid = %s;", (video_id, user_uuid))
    row = cursor.fetchone()
    conn.close()

    if not row:
        raise HTTPException(status_code=404, detail="Document item not found")

    doc_dir = storage.get_video_dir_path(f"doc_{video_id}", goal_id=row["learning_goal_id"], username=username)
    if not doc_dir.exists():
        raise HTTPException(status_code=404, detail="Document storage directory not found")

    matching_files = list(doc_dir.glob(f"doc_{video_id}.*"))
    if not matching_files:
        raise HTTPException(status_code=404, detail="Document file not found")

    return matching_files[0]


def _document_media_type(target_file: Path) -> str:
    ext = target_file.suffix.lower()
    return "application/pdf" if ext == ".pdf" else "text/plain; charset=utf-8" if ext in [".txt", ".md"] else "application/octet-stream"


@router.get("/videos/{video_id}/document")
async def serve_video_document(video_id: int, username: str = Depends(require_app_access)):
    """Serves raw PDF/document file as a forced download."""
    target_file = _resolve_video_document(video_id, username)
    return FileResponse(
        target_file,
        media_type=_document_media_type(target_file),
        filename=target_file.name,
        content_disposition_type="attachment",
    )


@router.get("/videos/{video_id}/pdf")
async def serve_video_pdf_inline(video_id: int, username: str = Depends(require_app_access)):
    """Serves raw PDF/document file inline for in-browser previewing."""
    target_file = _resolve_video_document(video_id, username)
    return FileResponse(
        target_file,
        media_type=_document_media_type(target_file),
        filename=target_file.name,
        content_disposition_type="inline",
    )


@router.post("/videos/{id}/archive")
async def archive_video(id: int, username: str = Depends(require_app_access)):
    """Toggles archived status for a video."""
    conn = database.get_db_connection(username)
    user_uuid = conn.user_uuid
    cursor = conn.cursor()
    cursor.execute("SELECT is_archived FROM videos WHERE id = %s AND user_uuid = %s;", (id, user_uuid))
    row = cursor.fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Video not found")
    new_state = 0 if row["is_archived"] else 1
    cursor.execute("UPDATE videos SET is_archived = %s WHERE id = %s AND user_uuid = %s;", (new_state, id, user_uuid))
    conn.commit()
    conn.close()
    return {"status": "success", "is_archived": new_state}


@router.post("/videos/{id}/pause")
async def pause_video(id: int, username: str = Depends(require_app_access)):
    """Toggles paused status for a video SRS review schedule."""
    conn = database.get_db_connection(username)
    user_uuid = conn.user_uuid
    cursor = conn.cursor()
    cursor.execute("SELECT is_paused FROM videos WHERE id = %s AND user_uuid = %s;", (id, user_uuid))
    row = cursor.fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Video not found")
    new_state = 0 if row["is_paused"] else 1
    cursor.execute("UPDATE videos SET is_paused = %s WHERE id = %s AND user_uuid = %s;", (new_state, id, user_uuid))
    conn.commit()
    conn.close()
    return {"status": "success", "is_paused": new_state}


@router.delete("/videos/{id}")
async def delete_video(id: int, username: str = Depends(require_app_access)):
    """Deletes a video and its associated quiz & JSON files."""
    conn = database.get_db_connection(username)
    user_uuid = conn.user_uuid
    cursor = conn.cursor()
    cursor.execute("SELECT youtube_id, learning_goal_id FROM videos WHERE id = %s AND user_uuid = %s;", (id, user_uuid))
    row = cursor.fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Video not found")
    yt_id = row.get("youtube_id") or f"doc_{id}"
    storage.delete_video_dir(yt_id, goal_id=row.get("learning_goal_id"), username=username)
    cursor.execute("DELETE FROM quiz_attempts WHERE video_id = %s AND user_uuid = %s;", (id, user_uuid))
    cursor.execute("DELETE FROM quizzes WHERE video_id = %s AND user_uuid = %s;", (id, user_uuid))
    cursor.execute("DELETE FROM videos WHERE id = %s AND user_uuid = %s;", (id, user_uuid))
    conn.commit()
    conn.close()
    return {"status": "success", "message": "Video deleted successfully"}


@router.post("/videos/{id}/goal")
async def assign_video_goal(
    id: int,
    learning_goal_id: Optional[int] = Form(None),
    username: str = Depends(require_app_access)
):
    """Assigns or updates the learning goal ID for a video."""
    conn = database.get_db_connection(username)
    user_uuid = conn.user_uuid
    cursor = conn.cursor()
    cursor.execute("UPDATE videos SET learning_goal_id = %s WHERE id = %s AND user_uuid = %s;", (learning_goal_id, id, user_uuid))
    if cursor.rowcount == 0:
        conn.close()
        raise HTTPException(status_code=404, detail="Video not found")
    conn.commit()
    conn.close()
    return {"status": "success", "learning_goal_id": learning_goal_id}


@router.post("/videos/{id}/watchlist")
async def toggle_watchlist(id: int, username: str = Depends(require_app_access)):
    """Toggles watchlist status for a video."""
    conn = database.get_db_connection(username)
    user_uuid = conn.user_uuid
    cursor = conn.cursor()
    cursor.execute("SELECT is_watchlist FROM videos WHERE id = %s AND user_uuid = %s;", (id, user_uuid))
    row = cursor.fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Video not found")
    new_state = 0 if row["is_watchlist"] else 1
    cursor.execute("UPDATE videos SET is_watchlist = %s WHERE id = %s AND user_uuid = %s;", (new_state, id, user_uuid))
    conn.commit()
    conn.close()
    return {"status": "success", "is_watchlist": new_state}


@router.get("/videos/{id}/factcheck")
async def get_fact_check(id: int, username: str = Depends(require_app_access)):
    """Returns AI fact-checking analysis for a video content payload, using cached result if available."""
    conn = database.get_db_connection(username)
    user_uuid = conn.user_uuid
    cursor = conn.cursor()
    cursor.execute("SELECT youtube_id, title, learning_goal_id FROM videos WHERE id = %s AND user_uuid = %s;", (id, user_uuid))
    row = cursor.fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="Video not found")
        
    yt_id = row.get("youtube_id") or f"doc_{id}"
    video_json = storage.get_video_json(yt_id, username=username)
    if not video_json:
        raise HTTPException(status_code=404, detail="Video metadata not found")
        
    if "fact_check" in video_json and video_json["fact_check"]:
        return video_json["fact_check"]

    # "Key concept preview for {title}" is a display-only placeholder stamped onto
    # `summary` for freshly-created preview videos (see /videos/preview) before any
    # real content exists. It must never be treated as real transcript/notes content,
    # and must not mask real custom_notes the way a plain `or` fallback would.
    real_summary_lines = [
        line for line in video_json.get("summary", [])
        if not line.startswith("Key concept preview for ")
    ]
    text_content = "\n".join(real_summary_lines + [video_json.get("custom_notes") or ""]).strip()
    if not text_content:
        # Nothing to compare against consensus on yet. Fail loudly instead of
        # asking Gemini to fact-check an empty string, which risks a
        # confidently-worded verdict for content it never actually reviewed.
        raise HTTPException(status_code=409, detail="No content available to fact-check yet. Wait for the video's summary to finish generating.")

    fact_check = ai.generate_fact_check(row["title"], text_content, username=username)
    video_json["fact_check"] = fact_check
    storage.save_video_json(yt_id, video_json, username=username)
    return fact_check


@router.post("/videos/{id}/edit")
async def edit_video(
    id: int,
    title: Optional[str] = Form(None),
    category: Optional[str] = Form(None),
    importance_rating: Optional[int] = Form(None),
    learning_goal_id: Optional[int] = Form(None),
    custom_notes: Optional[str] = Form(None),
    username: str = Depends(require_app_access)
):
    """Edits video details, rating, goal mapping, and notes safely supporting partial updates."""
    conn = database.get_db_connection(username)
    user_uuid = conn.user_uuid
    cursor = conn.cursor()
    cursor.execute("SELECT title, category, importance_rating, learning_goal_id, custom_notes FROM videos WHERE id = %s AND user_uuid = %s;", (id, user_uuid))
    existing = cursor.fetchone()
    if not existing:
        conn.close()
        raise HTTPException(status_code=404, detail="Video not found")
        
    new_title = title.strip() if (title is not None and title.strip()) else existing["title"]
    new_category = category.strip() if category is not None else existing["category"]
    new_rating = importance_rating if importance_rating is not None else existing["importance_rating"]
    
    if learning_goal_id is not None:
        new_goal_id = None if learning_goal_id == 0 else learning_goal_id
    else:
        new_goal_id = existing["learning_goal_id"]
        
    new_notes = custom_notes if custom_notes is not None else existing["custom_notes"]

    cursor.execute("""
        UPDATE videos 
        SET title = %s, category = %s, importance_rating = %s, learning_goal_id = %s, custom_notes = %s
        WHERE id = %s AND user_uuid = %s;
    """, (new_title, new_category, new_rating, new_goal_id, new_notes, id, user_uuid))
    conn.commit()
    conn.close()
    return {"status": "success", "title": new_title}


@router.post("/videos/{id}/position")
async def update_video_position(
    id: int,
    position: float = Form(0.0),
    username: str = Depends(require_app_access)
):
    """Updates the saved playback position (in seconds) for a video material."""
    conn = database.get_db_connection(username)
    user_uuid = conn.user_uuid
    try:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE videos SET last_position_seconds = %s WHERE id = %s AND user_uuid = %s;",
            (max(0.0, float(position)), id, user_uuid)
        )
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Video not found")
        conn.commit()
        return {"status": "success", "last_position_seconds": position}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update video position: {e}")
    finally:
        conn.close()


@router.post("/videos/preview")
async def create_preview_video(
    url: str = Form(...),
    title: Optional[str] = Form(None),
    goal_id: Optional[int] = Form(None),
    username: str = Depends(require_app_access)
):
    """Imports a YouTube video in 24h temporary Preview mode (is_temporary=1) without generating quizzes yet."""
    import re
    from datetime import datetime, timezone, timedelta
    from app import youtube, storage
    
    yt_id = None
    if "youtube.com" in url or "youtu.be" in url:
        match = re.search(r"(?:v=|\/)([0-9A-Za-z_-]{11})", url)
        if match:
            yt_id = match.group(1)
            
    if not yt_id:
        raise HTTPException(status_code=400, detail="Invalid YouTube URL")

    meta = {}
    if not title or title.startswith("YouTube Video"):
        try:
            meta = youtube.get_video_metadata(yt_id) or {}
        except Exception:
            meta = {}
        title = meta.get("title") or f"YouTube Video ({yt_id})"

    thumbnail = meta.get("thumbnail_url") or f"https://img.youtube.com/vi/{yt_id}/mqdefault.jpg"

    conn = database.get_db_connection(username)
    user_uuid = conn.user_uuid
    try:
        cursor = conn.cursor()
        target_goal = None if not goal_id or goal_id == 0 else goal_id

        # Check if already exists for this user
        cursor.execute("SELECT id FROM videos WHERE youtube_id = %s AND user_uuid = %s;", (yt_id, user_uuid))
        existing = cursor.fetchone()
        if existing:
            video_id = database.first_val(existing)
            cursor.execute("UPDATE videos SET is_watchlist = 1" + (", learning_goal_id = %s" if target_goal else "") + " WHERE id = %s AND user_uuid = %s;", ([target_goal, video_id, user_uuid] if target_goal else [video_id, user_uuid]))
            conn.commit()
            return {
                "status": "success",
                "video_id": video_id,
                "youtube_id": yt_id,
                "title": title
            }

        expires_at = (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat()
        cursor.execute(
            """INSERT INTO videos 
               (user_uuid, youtube_id, title, category, thumbnail_url, importance_rating, learning_goal_id, status, is_temporary, is_watchlist, expires_at)
               VALUES (%s, %s, %s, %s, %s, %s, %s, 'ready', 1, 1, %s)
               RETURNING id;""",
            (user_uuid, yt_id, title, "Preview Material", thumbnail, 3, target_goal, expires_at)
        )
        row = cursor.fetchone()
        video_id = database.first_val(row)
        conn.commit()

        json_filename = yt_id
        video_json_payload = {
            "id": video_id,
            "youtube_id": yt_id,
            "title": title,
            "thumbnail_url": thumbnail,
            "learning_goal_id": target_goal,
            "custom_notes": "",
            "is_temporary": 1,
            "is_watchlist": 1,
            "expires_at": expires_at,
            "summary": []
        }
        storage.save_video_json(json_filename, video_json_payload, username=username)

        return {
            "status": "success",
            "video_id": video_id,
            "youtube_id": yt_id,
            "title": title,
            "is_temporary": 1,
            "expires_at": expires_at
        }
    except Exception as e:
        print(f"Failed to create preview video for {yt_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to create preview video: {e}")
    finally:
        conn.close()


@router.post("/videos/{id}/confirm_import")
async def confirm_video_import(
    id: int,
    username: str = Depends(require_app_access)
):
    """Converts a 24h temporary preview material into a permanent video (is_temporary=0) and enqueues background processing for AI takeaways & quiz generation."""
    conn = database.get_db_connection(username)
    user_uuid = conn.user_uuid
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT youtube_id, title, importance_rating, learning_goal_id, status FROM videos WHERE id = %s AND user_uuid = %s;",
            (id, user_uuid)
        )
        v_row = cursor.fetchone()
        if not v_row:
            raise HTTPException(status_code=404, detail="Video not found")

        youtube_id = v_row.get("youtube_id")
        title = v_row.get("title") or "Material"
        importance_rating = v_row.get("importance_rating") or 3
        learning_goal_id = v_row.get("learning_goal_id")

        cursor.execute(
            "UPDATE videos SET is_temporary = 0, expires_at = NULL, status = 'processing', status_error = NULL WHERE id = %s AND user_uuid = %s;",
            (id, user_uuid)
        )
        conn.commit()
        
        yt_id = youtube_id or f"doc_{id}"
        json_data = storage.get_video_json(yt_id, username=username)
        if isinstance(json_data, dict) and json_data:
            json_data["is_temporary"] = 0
            json_data["expires_at"] = None
            json_data["status"] = "processing"
            storage.save_video_json(yt_id, json_data, username=username)

        task_id = None
        if youtube_id and not youtube_id.startswith("doc_"):
            payload = {
                "url": f"https://www.youtube.com/watch?v={youtube_id}",
                "importance_rating": importance_rating,
                "learning_goal_id": learning_goal_id,
                "is_watchlist": 1
            }
            task_id = ImportQueueManager.get_instance().enqueue_task(
                username=username,
                task_type="youtube",
                title=title,
                payload=payload,
                video_id=id
            )

        return {"status": "processing", "video_id": id, "task_id": task_id}
    except Exception as e:
        print(f"Failed to confirm video import for video #{id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to confirm video import: {e}")
    finally:
        conn.close()




@router.post("/videos/{id}/generate_quiz")
async def generate_video_quiz_for_level(
    id: int,
    level: int = Form(3),
    username: str = Depends(require_app_access)
):
    """Generates or retrieves active recall quiz for a specific importance level of a video material."""
    conn = database.get_db_connection(username)
    user_uuid = conn.user_uuid
    cursor = conn.cursor()
    cursor.execute("SELECT youtube_id, title, learning_goal_id FROM videos WHERE id = %s AND user_uuid = %s;", (id, user_uuid))
    row = cursor.fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Material card not found.")

    yt_id = row.get("youtube_id") or f"doc_{id}"
    title = row["title"]
    goal_id = row["learning_goal_id"]

    cursor.execute("""
        SELECT id, importance_level FROM quizzes
        WHERE video_id = %s AND user_uuid = %s AND quiz_type = 'video';
    """, (id, user_uuid))
    q_row = cursor.fetchone()

    if q_row:
        # A video keeps a single quiz row: changing the star rating just relabels the
        # importance level of the existing quiz (which already carries a full-size
        # question pool per SRS stage, see YouTubeTaskProcessor.process) so the display
        # slice in GET /api/quiz picks up the new count without an AI call or losing
        # in-progress srs_stage. Creating a second row here was the source of duplicate
        # "due now" entries for the same video.
        if q_row["importance_level"] != level:
            cursor.execute(
                "UPDATE quizzes SET importance_level = %s WHERE id = %s AND user_uuid = %s;",
                (level, q_row["id"], user_uuid)
            )
            conn.commit()
        conn.close()
        return {"status": "success", "quiz_id": q_row["id"]}

    user_config = config.load_user_config(username)
    intervals = get_srs_intervals(cursor, user_uuid=user_uuid)
    multipliers = get_srs_multipliers(username)
    multiplier = multipliers.get(level, 1.5)
    review_delay_days = intervals[0] * multiplier
    pref_hour = get_preferred_hour(cursor, user_uuid)
    next_review_dt = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=review_delay_days)
    next_review = adjust_next_review(next_review_dt, pref_hour).isoformat()

    try:
        cursor.execute("""
            INSERT INTO quizzes (user_uuid, video_id, goal_id, importance_level, srs_stage, next_review_at, quiz_type, in_progress_index)
            VALUES (%s, %s, %s, %s, 0, %s, 'video', 0) RETURNING id;
        """, (user_uuid, id, goal_id, level, next_review))
        res = cursor.fetchone()
        quiz_id = res["id"] if isinstance(res, dict) and "id" in res else (res[0] if res else cursor.lastrowid)

        conn.commit()

        video_data = storage.get_video_json(yt_id, username=username)
        q_counts = get_question_counts(user_config)
        # Generate a pool sized for the largest configured star level, not just this one,
        # so later star-rating changes can reslice the existing pool (see the lookup above)
        # instead of triggering another AI generation.
        question_count = max(q_counts.values()) if q_counts else 12

        try:
            if row.get("youtube_id"):
                ai_quiz_data = ai.analyze_youtube_video(f"https://www.youtube.com/watch?v={row['youtube_id']}", question_count=question_count, username=username)
            else:
                desc_text = "\n".join(video_data.get("summary", [])) if video_data else title
                ai_quiz_data = ai.generate_topic_quiz(
                    topic=title,
                    description=desc_text[:6000],
                    question_count=question_count,
                    username=username
                )
        except UsageLimitExceeded as e:
            # conn.close() happens in the enclosing `finally` below, don't double-release
            # the pooled connection here.
            raise HTTPException(status_code=429, detail=str(e))
        except Exception as e:
            logger.warning(f"AI quiz generation fallback used for quiz {quiz_id}: {e}")
            ai_quiz_data = {"quiz": [], "stages": {}}



        quiz_json_payload = {
            "id": quiz_id,
            "video_id": id,
            "video_filename": yt_id,
            "quiz_type": "video",
            "srs_stage": 0,
            "next_review_at": next_review,
            "questions": ai_quiz_data.get("quiz", []),
            "importance_level": level
        }
        storage.save_quiz_json(quiz_id, quiz_json_payload, username=username)
        database.save_quiz_concept_pool(quiz_id, build_concept_pool(ai_quiz_data), username=username)

        return {"status": "success", "quiz_id": quiz_id}
    finally:
        conn.close()


# Shown under each stage tab in the focus overlay. Server-side so the ladder is described in
# one place, matching the prompt that generated the questions.
_STAGE_LABELS = [
    "Immediate: definitions and key facts",
    "1 day: concepts and core mechanics",
    "3 days: cause, effect and practical logic",
    "7 days: synthesis, edge cases, comparison",
    "14-30 days: transfer and real-world judgment",
]


def _load_focus_context(video_id: int, username: str):
    """Resolves a video to its quiz row, concept pool, saved focus and per-star question count."""
    conn = database.get_db_connection(username)
    user_uuid = conn.user_uuid
    try:
        cursor = conn.cursor()
        cursor.execute(
            """SELECT q.id AS quiz_id, q.srs_stage, v.importance_rating, v.title
                 FROM videos v
                 JOIN quizzes q ON q.video_id = v.id AND q.user_uuid = v.user_uuid
                WHERE v.id = %s AND v.user_uuid = %s AND q.quiz_type = 'video'
                LIMIT 1;""",
            (video_id, user_uuid)
        )
        row = cursor.fetchone()
    finally:
        conn.close()

    if not row:
        raise HTTPException(status_code=404, detail="No quiz found for this material yet.")

    pool, focus = database.get_quiz_pool_and_focus(row["quiz_id"], username=username)
    if not pool:
        raise HTTPException(
            status_code=409,
            detail="This material was imported before topic extraction existed, so it has no topics to choose from."
        )

    q_counts = get_question_counts(config.load_user_config(username))
    target_count = q_counts.get(row.get("importance_rating") or 3, 5)
    return row, pool, focus, target_count


@router.get("/videos/{id}/concept-pool")
async def get_concept_pool(id: int, username: str = Depends(require_app_access)):
    """Returns the topics available per SRS stage, for the learning-focus overlay.

    Selection state falls back to the AI's own picks when the user has never saved one, so the
    overlay opens pre-filled with a sensible quiz rather than nothing ticked."""
    row, pool, focus, target_count = _load_focus_context(id, username)

    stages = []
    for stage_index, stage_key in enumerate(STAGE_KEYS):
        items = [q for q in pool if q.get("stage") == stage_index]
        if not items:
            continue

        saved = focus.get(stage_key) if isinstance(focus, dict) else None
        topics = {}
        for item in items:
            name = (item.get("topic") or "Ungrouped").strip() or "Ungrouped"
            entry = topics.setdefault(name, {"topic": name, "count": 0, "recommended": False})
            entry["count"] += 1
            if item.get("ai_recommended"):
                entry["recommended"] = True

        for entry in topics.values():
            # No saved choice means "use what the AI recommended", which is also what
            # select_stage_questions falls back to when it reads an empty selection.
            entry["selected"] = (entry["topic"] in saved) if saved else entry["recommended"]

        ordered = sorted(topics.values(), key=lambda t: (not t["recommended"], -t["count"], t["topic"]))
        stages.append({
            "stage": stage_index,
            "label": _STAGE_LABELS[stage_index],
            "topics": ordered,
            "total_questions": len(items),
            "selected_questions": sum(t["count"] for t in ordered if t["selected"]),
            "has_saved_selection": bool(saved),
        })

    return {
        "video_id": id,
        "quiz_id": row["quiz_id"],
        "title": row.get("title"),
        "current_stage": row.get("srs_stage") or 0,
        "target_count": target_count,
        "stages": stages,
    }


@router.post("/videos/{id}/focus")
async def save_concept_focus(
    id: int,
    focus_topics: str = Form(...),
    username: str = Depends(require_app_access)
):
    """Saves the per-stage topic selection and rebuilds the active question list.

    Purely local: the questions already exist in concept_pool, so this costs no AI call."""
    try:
        parsed = json.loads(focus_topics)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Could not read the focus selection.")
    if not isinstance(parsed, dict):
        raise HTTPException(status_code=400, detail="Could not read the focus selection.")

    row, pool, _, target_count = _load_focus_context(id, username)

    # Keep only topics that exist in this pool, so a stale overlay cannot persist a selection
    # that silently resolves to nothing.
    known = {(q.get("topic") or "Ungrouped").strip() or "Ungrouped" for q in pool}
    cleaned = {}
    for stage_index, stage_key in enumerate(STAGE_KEYS):
        chosen = parsed.get(stage_key)
        if not isinstance(chosen, list):
            continue
        kept = [t for t in chosen if isinstance(t, str) and t.strip() in known]
        if kept:
            cleaned[stage_key] = kept

    current_stage = row.get("srs_stage") or 0
    active = select_stage_questions(pool, current_stage, cleaned, target_count)
    database.save_quiz_focus(row["quiz_id"], cleaned, active, username=username)

    return {
        "status": "success",
        "quiz_id": row["quiz_id"],
        "current_stage": current_stage,
        "active_questions": len(active),
        "target_count": target_count,
    }


@router.get("/videos/{id}/stats")
async def get_video_stats(id: int, username: str = Depends(require_app_access)):
    """Returns analytics, SRS status, and attempt history for a specific material/video."""
    conn = database.get_db_connection(username)
    user_uuid = conn.user_uuid
    cursor = conn.cursor()
    
    cursor.execute("SELECT id, title, importance_rating, learning_goal_id FROM videos WHERE id = %s AND user_uuid = %s;", (id, user_uuid))
    v_row = cursor.fetchone()
    if not v_row:
        conn.close()
        raise HTTPException(status_code=404, detail="Material not found")
        
    title = v_row["title"]
    importance = v_row.get("importance_rating") or 3
    
    cursor.execute("""
        SELECT srs_stage, next_review_at 
        FROM quizzes 
        WHERE video_id = %s AND user_uuid = %s AND importance_level = %s AND quiz_type = 'video'
        ORDER BY id DESC LIMIT 1;
    """, (id, user_uuid, importance))
    q_row = cursor.fetchone()
    
    if not q_row:
        cursor.execute("""
            SELECT srs_stage, next_review_at 
            FROM quizzes 
            WHERE video_id = %s AND user_uuid = %s
            ORDER BY id DESC LIMIT 1;
        """, (id, user_uuid))
        q_row = cursor.fetchone()
        
    srs_stage = q_row["srs_stage"] if (q_row and q_row.get("srs_stage") is not None) else 0
    raw_next = q_row.get("next_review_at") if q_row else None
    next_review_at = raw_next.isoformat() if hasattr(raw_next, "isoformat") else (str(raw_next) if raw_next else None)
    
    cursor.execute("""
        SELECT a.id, a.quiz_id, a.question_index, a.question, a.given_answer, 
               a.correct_answer, a.grade, a.created_at, a.explanation, a.feedback,
               COALESCE(q.srs_stage, 0) AS srs_stage
        FROM quiz_attempts a
        LEFT JOIN quizzes q ON a.quiz_id = q.id
        WHERE a.user_uuid = %s AND (a.video_id = %s OR a.quiz_id IN (SELECT id FROM quizzes WHERE video_id = %s AND user_uuid = %s))
        ORDER BY a.id DESC;
    """, (user_uuid, id, id, user_uuid))
    rows = cursor.fetchall()
    attempts = []
    for r in rows:
        att = dict(r)
        c_at = att.get("created_at")
        if hasattr(c_at, "isoformat"):
            att["created_at"] = c_at.isoformat()
        attempts.append(att)
    conn.close()
    
    return {
        "video_id": id,
        "title": title,
        "srs_stage": srs_stage,
        "next_review_at": next_review_at,
        "attempts": attempts
    }



