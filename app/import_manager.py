import io
import os
import time
import json
import asyncio
import traceback
from abc import ABC, abstractmethod
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional, List
from pathlib import Path


from app import database, config, storage, ai, youtube


# ==============================================================================
# BETA-ONLY: import progress-bar calibration telemetry.
#
# Feeds the `import_timings` table, which exists purely to tune the fake-progress
# constants in static/js/core.js (renderProgressOnly). Records only how long an
# import took and what it was importing, no username, no user_uuid, no title.
#
# Switch off with ENABLE_IMPORT_TIMING_LOG=false in .env.
# TO REMOVE ENTIRELY AFTER BETA: delete this function and its two call sites in
# _execute_task (search "_log_import_timing"), then DROP TABLE import_timings.
# ==============================================================================
ENABLE_IMPORT_TIMING_LOG = os.getenv("ENABLE_IMPORT_TIMING_LOG", "true").strip().lower() in ("1", "true", "yes", "on")


def _log_import_timing(
    task_type: str,
    processing_time_sec: float,
    video_url: Optional[str] = None,
    duration_seconds: Optional[int] = None,
):
    """Records one completed import in `import_timings` for progress-bar calibration."""
    if not ENABLE_IMPORT_TIMING_LOG:
        return
    conn = None
    try:
        conn = database.get_pooled_raw_connection()
        cursor = conn.cursor()
        cursor.execute(
            """INSERT INTO import_timings (task_type, video_url, duration_seconds, processing_time_sec)
               VALUES (%s, %s, %s, %s);""",
            (task_type, video_url, duration_seconds, processing_time_sec)
        )
        conn.commit()
        cursor.close()
    except Exception as e_log:
        # Telemetry must never break an import.
        if conn is not None:
            try:
                conn.rollback()
            except Exception:
                pass
        print(f"[ImportTimingLog] Error writing timing row: {e_log}")
    finally:
        if conn is not None:
            database.release_pooled_connection(conn)
from app.dependencies import (
    get_question_counts,
    get_srs_multipliers,
    get_srs_intervals,
    get_preferred_hour,
    adjust_next_review,
)


class IImportTaskProcessor(ABC):
    """Abstract interface for all background task processors."""

    @abstractmethod
    def process(
        self,
        task_id: int,
        video_id: Optional[int],
        payload: dict,
        username: str,
        update_stage_fn
    ) -> dict:
        """
        Executes synchronous task processing logic in a worker thread.
        Call update_stage_fn("stage_name") to push live stage updates.
        Returns dict with task result metadata.
        """
        pass


class YouTubeTaskProcessor(IImportTaskProcessor):
    def process(
        self,
        task_id: int,
        video_id: Optional[int],
        payload: dict,
        username: str,
        update_stage_fn
    ) -> dict:
        t0 = time.time()
        url = payload.get("url")
        importance_rating = payload.get("importance_rating", 3)
        learning_goal_id = payload.get("learning_goal_id")

        update_stage_fn("Step 1/2: Fetching Video Info...")
        yt_id = youtube.extract_video_id(url)
        if not yt_id:
            raise ValueError("Invalid YouTube URL.")

        meta = youtube.get_video_metadata(yt_id)
        metadata_title = meta.get("title", f"YouTube Video ({yt_id})")
        thumbnail = meta.get("thumbnail_url", f"https://img.youtube.com/vi/{yt_id}/mqdefault.jpg")

        conn_title = database.get_db_connection(username)
        try:
            conn_title.execute("UPDATE import_tasks SET title = %s WHERE id = %s AND user_uuid = %s;", (metadata_title, task_id, conn_title.user_uuid))
            conn_title.commit()
        except Exception as e_title:
            print(f"[YouTubeTaskProcessor] Note: Title update failed for task {task_id}: {e_title}")
        finally:
            conn_title.close()

        t_meta = time.time()
        fetch_metadata_sec = round(t_meta - t0, 2)

        user_config = config.load_user_config(username)
        q_counts = get_question_counts(user_config)
        question_count = q_counts.get(5, 5)

        update_stage_fn("Step 2/2: Gemini Analyzing Video & Generating Quizzes...")

        analysis = ai.analyze_youtube_video(url, question_count, username=username)

        t_ai = time.time()
        gemini_ai_analysis_sec = round(t_ai - t_meta, 2)

        conn = database.get_db_connection(username)
        user_uuid = conn.user_uuid
        cursor = conn.cursor()
        try:

            category = analysis.get("category", "General")
            summary = analysis.get("summary", [])
            outline = analysis.get("outline", [])
            quiz_items = analysis.get("quiz", [])
            quiz_stages = analysis.get("stages", {})
            fact_check_result = analysis.get("fact_check", {})
            duration_seconds_val = analysis.get("duration_seconds") or 0

            # Long videos are clipped before being sent to Gemini (see ai.analyze_youtube_video),
            # so tell the user the summary/quizzes only cover the opening portion. Minutes are
            # derived from the constant rather than hardcoded so the two can't drift apart.
            if analysis.get("video_truncated"):
                _limit_min = ai.MAX_VIDEO_ANALYSIS_SECONDS // 60
                summary = [
                    f"⚠️ Only the first {_limit_min} minutes of this video were processed, "
                    f"due to technical limitations."
                ] + list(summary)

            target_goal_id = learning_goal_id
            if target_goal_id:
                cursor.execute("SELECT title FROM goals WHERE id = %s AND user_uuid = %s;", (target_goal_id, user_uuid))
                goal_row = cursor.fetchone()
                if goal_row:
                    category = goal_row["title"]

            intervals = get_srs_intervals(cursor, user_uuid=user_uuid)
            multipliers = get_srs_multipliers(username)
            multiplier = multipliers.get(importance_rating, 1.5)
            review_delay_days = intervals[0] * multiplier
            pref_hour = get_preferred_hour(cursor, user_uuid)
            next_review = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=review_delay_days)
            next_review = adjust_next_review(next_review, pref_hour)

            if video_id:
                cursor.execute("DELETE FROM quizzes WHERE video_id = %s AND user_uuid = %s AND quiz_type = 'video';", (video_id, user_uuid))

            q_list = [dict(q) for q in quiz_items]
            q_json = json.dumps(q_list)

            cursor.execute(
                """INSERT INTO quizzes 
                   (user_uuid, video_id, quiz_type, srs_stage, next_review_at, notified, importance_level, questions_json)
                   VALUES (%s, %s, 'video', 0, %s, 0, %s, %s::jsonb) RETURNING id;""",
                (user_uuid, video_id, next_review.isoformat(), importance_rating, q_json)
            )
            res = cursor.fetchone()
            quiz_id = res["id"] if isinstance(res, dict) and "id" in res else res[0]

            existing_v_json = storage.get_video_json(yt_id, username=username) or {}
            existing_notes = existing_v_json.get("custom_notes", "") if isinstance(existing_v_json, dict) else ""

            json_filename = yt_id
            video_json_payload = {
                "id": video_id,
                "youtube_id": yt_id,
                "title": metadata_title,
                "category": category,
                "thumbnail_url": thumbnail,
                "importance_rating": importance_rating,
                "learning_goal_id": target_goal_id,
                "is_archived": 0,
                "is_paused": 0,
                "is_temporary": 0,
                "is_watchlist": payload.get("is_watchlist", 0),
                "custom_notes": existing_notes,
                "duration_seconds": duration_seconds_val,
                "summary": summary,
                "outline": outline,
                "fact_check": fact_check_result,
                "created_at": datetime.now(timezone.utc).replace(tzinfo=None).isoformat(),
                "status": "ready"
            }

            storage.save_video_json(json_filename, video_json_payload, username=username)

            quiz_json_payload = {
                "id": quiz_id,
                "video_id": video_id,
                "video_filename": json_filename,
                "quiz_type": "video",
                "srs_stage": 0,
                "next_review_at": next_review.isoformat(),
                "questions": [dict(q) for q in quiz_items],
                "stages": quiz_stages,
                "importance_level": importance_rating
            }
            storage.save_quiz_json(quiz_id, quiz_json_payload, username=username)

            cursor.execute(
                """UPDATE videos
                   SET title = %s, category = %s, thumbnail_url = %s, learning_goal_id = %s, is_temporary = 0, duration_seconds = %s, status = 'ready', status_error = NULL
                   WHERE id = %s AND user_uuid = %s;""",
                (metadata_title, category, thumbnail, target_goal_id, duration_seconds_val, video_id, user_uuid)
            )
            conn.commit()

            telegram_token = config.get_config("TELEGRAM_BOT_TOKEN", username=username)
            if telegram_token:
                try:
                    from app.telegram_bot import send_telegram_message_sync
                    msg = (
                        f"📚 *New Study Material Ready!*\n\n"
                        f"Title: *{metadata_title}*\n"
                        f"Category: {category}\n"
                        f"Quiz Level: {importance_rating} ({len(quiz_items)} recall questions).\n\n"
                        f"Open your dashboard to start studying!"
                    )
                    send_telegram_message_sync(msg, username)
                except Exception as e_tel:
                    print(f"Telegram notification dispatch failed for {username}: {e_tel}")

            return {
                "video_id": video_id,
                "title": metadata_title,
                "category": category,
                "quiz_id": quiz_id
            }
        finally:
            conn.close()


class DocumentTaskProcessor(IImportTaskProcessor):
    def process(
        self,
        task_id: int,
        video_id: Optional[int],
        payload: dict,
        username: str,
        update_stage_fn
    ) -> dict:
        file_path_str = payload.get("file_path")
        title = payload.get("title")
        importance_rating = payload.get("importance_rating", 3)
        learning_goal_id = payload.get("learning_goal_id")

        update_stage_fn("Step 1/3: Extracting Document Text...")
        doc_file = Path(file_path_str) if file_path_str else None
        if not doc_file or not doc_file.exists():
            raise ValueError("Uploaded document file was not found on server.")

        # doc_file's own extension was already validated at upload time
        # (storage.safe_doc_extension), reuse it here so save/serve/delete
        # all agree on the same doc_<video_id><ext> naming.
        saved_doc_path = storage.get_document_path(video_id, doc_file.suffix.lower(), goal_id=learning_goal_id, username=username)

        file_bytes = doc_file.read_bytes()
        # Uploads already land on saved_doc_path, so normally there is nothing
        # to copy. The write is kept for older queued tasks whose payload still
        # points at a legacy uploads/ staging path.
        if saved_doc_path.resolve() != doc_file.resolve():
            saved_doc_path.write_bytes(file_bytes)

        ext = saved_doc_path.suffix.lower()

        extracted_text = ""
        if ext == ".pdf":
            from pypdf import PdfReader
            reader = PdfReader(io.BytesIO(file_bytes))
            pages_text = []
            for page in reader.pages:
                t = page.extract_text()
                if t:
                    pages_text.append(t)
            extracted_text = "\n".join(pages_text).strip()
            if not extracted_text:
                raise ValueError("No text could be extracted from the PDF.")
        else:
            extracted_text = file_bytes.decode("utf-8", errors="ignore").strip()

        if len(extracted_text) < 30:
            raise ValueError("Document content is too short to generate high-quality quizzes.")

        original_filename = payload.get("original_filename") or doc_file.name
        metadata_title = title.strip() if (title and title.strip()) else original_filename
        thumbnail = "/static/images/document-icon.svg"

        word_count = len(extracted_text.split())
        update_stage_fn(f"Step 2/3: Parsed document ({word_count:,} words)...")

        conn_goals = database.get_db_connection(username)
        user_uuid = conn_goals.user_uuid
        try:
            cur_g = conn_goals.cursor()
            cur_g.execute("SELECT id, title, description FROM goals WHERE user_uuid = %s AND is_archived = 0;", (user_uuid,))
            active_goals = [dict(r) for r in cur_g.fetchall()]
        finally:
            conn_goals.close()

        user_config = config.load_user_config(username)
        q_counts = get_question_counts(user_config)
        question_count = q_counts.get(5, 5)

        update_stage_fn("Step 3/3: AI Generating 25 Quiz Items...")
        analysis = ai.analyze_video_transcript(extracted_text, question_count, active_goals, username=username)

        conn = database.get_db_connection(username)
        user_uuid = conn.user_uuid
        cursor = conn.cursor()
        try:

            category = analysis.get("category", "General")
            summary = analysis.get("summary", [])
            quiz_items = analysis.get("quiz", [])
            quiz_stages = analysis.get("stages", {})
            fact_check_result = analysis.get("fact_check", {})

            target_goal_id = learning_goal_id
            if target_goal_id is not None:
                cursor.execute("SELECT title FROM goals WHERE id = %s AND user_uuid = %s;", (target_goal_id, user_uuid))
                goal_row = cursor.fetchone()
                if goal_row:
                    category = goal_row["title"]


            intervals = get_srs_intervals(cursor, user_uuid=user_uuid)
            multipliers = get_srs_multipliers(username)
            multiplier = multipliers.get(importance_rating, 1.5)
            review_delay_days = intervals[0] * multiplier
            pref_hour = get_preferred_hour(cursor, user_uuid)
            next_review = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=review_delay_days)
            next_review = adjust_next_review(next_review, pref_hour)

            if video_id:
                cursor.execute("DELETE FROM quizzes WHERE video_id = %s AND user_uuid = %s AND quiz_type = 'video';", (video_id, user_uuid))

            q_list = [dict(q) for q in quiz_items]
            q_json = json.dumps(q_list)

            cursor.execute(
                """INSERT INTO quizzes
                   (user_uuid, video_id, quiz_type, srs_stage, next_review_at, notified, importance_level, questions_json)
                   VALUES (%s, %s, 'video', 0, %s, 0, %s, %s::jsonb) RETURNING id;""",
                (user_uuid, video_id, next_review.isoformat(), importance_rating, q_json)
            )
            res = cursor.fetchone()
            quiz_id = res["id"] if isinstance(res, dict) and "id" in res else res[0]

            json_filename = f"doc_{video_id}"
            video_json_payload = {
                "id": video_id,
                "youtube_id": None,
                "title": metadata_title,
                "category": category,
                "thumbnail_url": thumbnail,
                "importance_rating": importance_rating,
                "learning_goal_id": target_goal_id,
                "is_archived": 0,
                "is_paused": 0,
                "is_watchlist": 0,
                "custom_notes": "",
                "summary": summary,
                "fact_check": fact_check_result,
                "created_at": datetime.now(timezone.utc).replace(tzinfo=None).isoformat(),
                "status": "ready"
            }
            storage.save_video_json(json_filename, video_json_payload, username=username)

            quiz_json_payload = {
                "id": quiz_id,
                "video_id": video_id,
                "video_filename": json_filename,
                "quiz_type": "video",
                "srs_stage": 0,
                "next_review_at": next_review.isoformat(),
                "questions": [dict(q) for q in quiz_items],
                "stages": quiz_stages,
                "importance_level": importance_rating
            }
            storage.save_quiz_json(quiz_id, quiz_json_payload, username=username)

            cursor.execute(
                """UPDATE videos 
                   SET title = %s, category = %s, thumbnail_url = %s, learning_goal_id = %s, status = 'ready', status_error = NULL 
                   WHERE id = %s AND user_uuid = %s;""",
                (metadata_title, category, thumbnail, target_goal_id, video_id, user_uuid)
            )
            conn.commit()
            return {"video_id": video_id, "title": metadata_title, "quiz_id": quiz_id}
        finally:
            conn.close()


class NotesTaskProcessor(IImportTaskProcessor):
    def process(
        self,
        task_id: int,
        video_id: Optional[int],
        payload: dict,
        username: str,
        update_stage_fn
    ) -> dict:
        text_content = payload.get("text_content", "").strip()
        title = payload.get("title")
        importance_rating = payload.get("importance_rating", 3)
        learning_goal_id = payload.get("learning_goal_id")

        if len(text_content) < 30:
            raise ValueError("Notes text is too short to generate high-quality quizzes.")

        update_stage_fn("Step 1/3: Reading Notes Content...")
        metadata_title = title.strip() if (title and title.strip()) else f"Notes ({datetime.now().strftime('%Y-%b-%d')})"
        thumbnail = "/static/images/notes-icon.svg"

        conn_goals = database.get_db_connection(username)
        user_uuid = conn_goals.user_uuid
        try:
            cur_g = conn_goals.cursor()
            cur_g.execute("SELECT id, title, description FROM goals WHERE user_uuid = %s AND is_archived = 0;", (user_uuid,))
            active_goals = [dict(r) for r in cur_g.fetchall()]
        finally:
            conn_goals.close()

        user_config = config.load_user_config(username)
        q_counts = get_question_counts(user_config)
        question_count = q_counts.get(5, 5)

        word_count = len(text_content.split())
        update_stage_fn(f"Step 2/3: Parsed notes ({word_count:,} words)...")
        update_stage_fn("Step 3/3: AI Generating 25 Quiz Items...")
        analysis = ai.analyze_video_transcript(text_content, question_count, active_goals, username=username)

        conn = database.get_db_connection(username)
        user_uuid = conn.user_uuid
        cursor = conn.cursor()
        try:

            category = analysis.get("category", "General")
            summary = analysis.get("summary", [])
            quiz_items = analysis.get("quiz", [])
            quiz_stages = analysis.get("stages", {})
            fact_check_result = analysis.get("fact_check", {})

            target_goal_id = learning_goal_id
            if target_goal_id is not None:
                cursor.execute("SELECT title FROM goals WHERE id = %s AND user_uuid = %s;", (target_goal_id, user_uuid))
                goal_row = cursor.fetchone()
                if goal_row:
                    category = goal_row["title"]


            intervals = get_srs_intervals(cursor, user_uuid=user_uuid)
            multipliers = get_srs_multipliers(username)
            multiplier = multipliers.get(importance_rating, 1.5)
            review_delay_days = intervals[0] * multiplier
            pref_hour = get_preferred_hour(cursor, user_uuid)
            next_review = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=review_delay_days)
            next_review = adjust_next_review(next_review, pref_hour)

            if video_id:
                cursor.execute("DELETE FROM quizzes WHERE video_id = %s AND user_uuid = %s AND quiz_type = 'video';", (video_id, user_uuid))

            q_list = [dict(q) for q in quiz_items]
            q_json = json.dumps(q_list)

            cursor.execute(
                """INSERT INTO quizzes
                   (user_uuid, video_id, quiz_type, srs_stage, next_review_at, notified, importance_level, questions_json)
                   VALUES (%s, %s, 'video', 0, %s, 0, %s, %s::jsonb) RETURNING id;""",
                (user_uuid, video_id, next_review.isoformat(), importance_rating, q_json)
            )
            res = cursor.fetchone()
            quiz_id = res["id"] if isinstance(res, dict) and "id" in res else res[0]

            json_filename = f"doc_{video_id}"
            video_json_payload = {
                "id": video_id,
                "youtube_id": None,
                "title": metadata_title,
                "category": category,
                "thumbnail_url": thumbnail,
                "importance_rating": importance_rating,
                "learning_goal_id": target_goal_id,
                "is_archived": 0,
                "is_paused": 0,
                "is_watchlist": 0,
                "custom_notes": text_content,
                "summary": summary,
                "fact_check": fact_check_result,
                "created_at": datetime.now(timezone.utc).replace(tzinfo=None).isoformat(),
                "status": "ready"
            }
            storage.save_video_json(json_filename, video_json_payload, username=username)

            quiz_json_payload = {
                "id": quiz_id,
                "video_id": video_id,
                "video_filename": json_filename,
                "quiz_type": "video",
                "srs_stage": 0,
                "next_review_at": next_review.isoformat(),
                "questions": [dict(q) for q in quiz_items],
                "stages": quiz_stages,
                "importance_level": importance_rating
            }
            storage.save_quiz_json(quiz_id, quiz_json_payload, username=username)

            cursor.execute(
                """UPDATE videos 
                   SET title = %s, category = %s, thumbnail_url = %s, learning_goal_id = %s, status = 'ready', status_error = NULL 
                   WHERE id = %s AND user_uuid = %s;""",
                (metadata_title, category, thumbnail, target_goal_id, video_id, user_uuid)
            )
            conn.commit()
            return {"video_id": video_id, "title": metadata_title, "quiz_id": quiz_id}
        finally:
            conn.close()


class GoalRecommendationsProcessor(IImportTaskProcessor):
    def process(
        self,
        task_id: int,
        video_id: Optional[int],
        payload: dict,
        username: str,
        update_stage_fn
    ) -> dict:
        goal_id = payload.get("goal_id")
        update_stage_fn("Analyzing Goal Topics & Web Searches...")

        conn = database.get_db_connection(username)
        user_uuid = conn.user_uuid
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT id, title, description FROM goals WHERE id = %s AND user_uuid = %s;", (goal_id, user_uuid))
            goal = cursor.fetchone()
            if not goal:
                raise ValueError("Goal not found.")

            cursor.execute("SELECT id, title, youtube_id, custom_notes FROM videos WHERE learning_goal_id = %s AND user_uuid = %s AND status = 'ready';", (goal_id, user_uuid))
            vids = [dict(r) for r in cursor.fetchall()]

            excluded = storage.get_excluded_youtube_ids(username)
            recs = ai.generate_goal_recommendations(dict(goal), vids, excluded_yt_ids=excluded, username=username)
            return {"goal_id": goal_id, "recommendations": recs}
        finally:
            conn.close()


class GoalQuizProcessor(IImportTaskProcessor):
    def process(
        self,
        task_id: int,
        video_id: Optional[int],
        payload: dict,
        username: str,
        update_stage_fn
    ) -> dict:
        goal_id = payload.get("goal_id")
        question_count = payload.get("question_count", 5)

        update_stage_fn("Synthesizing Transcripts & Concept Questions...")
        conn = database.get_db_connection(username)
        user_uuid = conn.user_uuid
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT id, title, description FROM goals WHERE id = %s AND user_uuid = %s;", (goal_id, user_uuid))
            goal = cursor.fetchone()
            if not goal:
                raise ValueError("Goal not found.")

            cursor.execute("SELECT id, title, youtube_id FROM videos WHERE learning_goal_id = %s AND user_uuid = %s AND status = 'ready';", (goal_id, user_uuid))
            goal_videos = [dict(r) for r in cursor.fetchall()]


            transcripts = []
            for gv in goal_videos:
                yt_id_val = gv["youtube_id"] or f"doc_{gv['id']}"
                vdata = storage.load_video_json(yt_id_val, username=username)
                if vdata and vdata.get("summary"):
                    transcripts.append(f"Video '{gv['title']}':\n" + "\n".join(vdata.get("summary", [])))

            if not transcripts:
                raise ValueError("No video summaries available under this goal.")

            combined_text = "\n\n---\n\n".join(transcripts)
            analysis = ai.analyze_video_transcript(combined_text, question_count, [], username=username)

            quiz_items = analysis.get("quiz", [])
            intervals = get_srs_intervals(cursor, user_uuid=user_uuid)
            pref_hour = get_preferred_hour(cursor, user_uuid)
            next_review = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=intervals[0])
            next_review = adjust_next_review(next_review, pref_hour)

            q_list = [dict(q) for q in quiz_items]
            q_json = json.dumps(q_list)

            cursor.execute(
                """INSERT INTO quizzes 
                   (user_uuid, video_id, goal_id, quiz_type, srs_stage, next_review_at, notified, importance_level, questions_json)
                   VALUES (%s, NULL, %s, 'goal', 0, %s, 0, 3, %s::jsonb) RETURNING id;""",
                (user_uuid, goal_id, next_review.isoformat(), q_json)
            )
            res = cursor.fetchone()
            quiz_id = res["id"] if isinstance(res, dict) and "id" in res else res[0]

            quiz_json_payload = {
                "id": quiz_id,
                "goal_id": goal_id,
                "quiz_type": "goal",
                "srs_stage": 0,
                "next_review_at": next_review.isoformat(),
                "questions": [dict(q) for q in quiz_items],
                "importance_level": 3
            }
            storage.save_quiz_json(quiz_id, quiz_json_payload, username=username)
            conn.commit()

            return {"goal_id": goal_id, "quiz_id": quiz_id}
        finally:
            conn.close()


class ImportQueueManager:
    """Task Queue Manager managing background processing and PostgreSQL crash resilience."""

    _instance = None

    def __init__(self):
        self._processors: Dict[str, IImportTaskProcessor] = {
            "youtube": YouTubeTaskProcessor(),
            "document": DocumentTaskProcessor(),
            "notes": NotesTaskProcessor(),
            "goal_recommendations": GoalRecommendationsProcessor(),
            "goal_quiz": GoalQuizProcessor()
        }
        self._user_semaphores: Dict[str, asyncio.Semaphore] = {}

    def _get_user_semaphore(self, username: str) -> asyncio.Semaphore:
        if username not in self._user_semaphores:
            self._user_semaphores[username] = asyncio.Semaphore(2)
        return self._user_semaphores[username]

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = ImportQueueManager()
        return cls._instance

    def enqueue_task(
        self,
        username: str,
        task_type: str,
        title: str,
        payload: dict,
        video_id: Optional[int] = None
    ) -> int:
        """Registers task into PostgreSQL database and triggers non-blocking background task processing."""
        conn = database.get_db_connection(username)
        cursor = conn.cursor()
        user_uuid = conn.user_uuid
        try:
            cursor.execute(
                """INSERT INTO import_tasks 
                   (user_uuid, video_id, task_type, title, payload_json, status, progress_stage)
                   VALUES (%s, %s, %s, %s, %s, 'pending', 'Queued') RETURNING id;""",
                (user_uuid, video_id, task_type, title, json.dumps(payload))
            )
            res = cursor.fetchone()
            task_id = res["id"] if isinstance(res, dict) and "id" in res else (res[0] if res else cursor.lastrowid)
            conn.commit()

            # Trigger non-blocking async execution
            asyncio.create_task(self._process_task_async(task_id, username))
            return task_id
        finally:
            conn.close()

    async def _process_task_async(self, task_id: int, username: str):
        sem = self._get_user_semaphore(username)
        async with sem:
            conn = database.get_db_connection(username)
            user_uuid = conn.user_uuid
            cursor = conn.cursor()
            task_dict = None
            start_time = time.time()
            try:
                cursor.execute("SELECT * FROM import_tasks WHERE id = %s AND user_uuid = %s;", (task_id, user_uuid))
                task = cursor.fetchone()
                if not task:
                    conn.close()
                    return

                task_dict = dict(task)
                task_type = task_dict["task_type"]
                video_id = task_dict["video_id"]
                payload = json.loads(task_dict["payload_json"])


                processor = self._processors.get(task_type)
                if not processor:
                    raise ValueError(f"No task processor registered for type '{task_type}'.")

                cursor.execute(
                    "UPDATE import_tasks SET status = 'processing', progress_stage = 'Starting...', updated_at = CURRENT_TIMESTAMP WHERE id = %s AND user_uuid = %s;",
                    (task_id, user_uuid)
                )
                conn.commit()

                def update_stage_fn(stage_name: str):
                    c = database.get_db_connection(username)
                    try:
                        c.execute(
                            "UPDATE import_tasks SET progress_stage = %s, updated_at = CURRENT_TIMESTAMP WHERE id = %s AND user_uuid = %s;",
                            (stage_name, task_id, user_uuid)
                        )
                        c.commit()
                    except Exception as e_stg:
                        print(f"Error updating task stage: {e_stg}")
                    finally:
                        c.close()

                # Execute blocking sync processor inside thread pool executor to prevent blocking FastAPI event loop!
                result = await asyncio.to_thread(
                    processor.process, task_id, video_id, payload, username, update_stage_fn
                )

                cursor.execute(
                    """UPDATE import_tasks 
                       SET status = 'completed', progress_stage = 'Ready', updated_at = CURRENT_TIMESTAMP 
                       WHERE id = %s AND user_uuid = %s;""",
                    (task_id, user_uuid)
                )
                conn.commit()

                elapsed_sec = round(time.time() - start_time, 2)

                # Progress-bar calibration telemetry. Read the video row only now:
                # for a YouTube import the duration is unknown until metadata has
                # been fetched, so reading it before processing always yielded NULL.
                timing_url, timing_duration = None, None
                effective_video_id = video_id or (result.get("video_id") if isinstance(result, dict) else None)
                if effective_video_id:
                    try:
                        cursor.execute(
                            "SELECT youtube_id, duration_seconds FROM videos WHERE id = %s AND user_uuid = %s;",
                            (effective_video_id, user_uuid)
                        )
                        r_vid = cursor.fetchone()
                        if r_vid:
                            timing_duration = r_vid.get("duration_seconds") or None
                            if r_vid.get("youtube_id"):
                                timing_url = f"https://youtu.be/{r_vid['youtube_id']}"
                    except Exception:
                        conn.rollback()

                _log_import_timing(
                    task_type=task_type,
                    processing_time_sec=elapsed_sec,
                    video_url=timing_url,
                    duration_seconds=timing_duration,
                )

            except Exception as e:
                err_str = str(e)
                elapsed_sec = round(time.time() - start_time, 2)
                print(f"Import task #{task_id} failed for user '{username}': {err_str}")
                traceback.print_exc()

                # Failed imports are deliberately not logged to import_timings, # the progress bar is calibrated against runs that actually finish.

                try:
                    raw_fail_conn = database.get_pooled_raw_connection()
                    try:
                        fail_cur = raw_fail_conn.cursor()
                        fail_cur.execute(
                            """UPDATE import_tasks 
                               SET status = 'failed', progress_stage = 'Failed', error_message = %s, updated_at = CURRENT_TIMESTAMP 
                               WHERE id = %s AND user_uuid = %s;""",
                            (err_str, task_id, user_uuid)
                        )
                        if task_dict and task_dict.get("video_id"):
                            fail_cur.execute(
                                "UPDATE videos SET status = 'failed', status_error = %s WHERE id = %s AND user_uuid = %s;",
                                (err_str, task_dict["video_id"], user_uuid)
                            )
                        if not getattr(raw_fail_conn, "autocommit", False):
                            raw_fail_conn.commit()
                        fail_cur.close()
                    finally:
                        database.release_pooled_connection(raw_fail_conn)
                except Exception as e_db:
                    print(f"Failed to record task failure in DB: {e_db}")
            finally:
                conn.close()


    def recover_pending_tasks(self, username: str):
        """Scans database for incomplete tasks after server restart and resumes execution."""
        conn = database.get_db_connection(username)
        user_uuid = conn.user_uuid
        cursor = conn.cursor()
        try:
            # Auto-resolve any stuck videos whose quizzes/SRS generation finished or are ready
            cursor.execute(
                """UPDATE videos SET status = 'ready' 
                   WHERE status = 'processing' AND user_uuid = %s 
                   AND id IN (SELECT DISTINCT video_id FROM quizzes WHERE user_uuid = %s);""",
                (user_uuid, user_uuid)
            )
            conn.commit()

            cursor.execute("SELECT id FROM import_tasks WHERE status IN ('pending', 'processing') AND user_uuid = %s;", (user_uuid,))
            rows = cursor.fetchall()
            for r in rows:
                tid = r["id"]
                print(f"Server Startup: Recovering incomplete import task #{tid} for user '{username}'...")
                cursor.execute("UPDATE import_tasks SET status = 'pending', progress_stage = 'Queued (Recovered)' WHERE id = %s AND user_uuid = %s;", (tid, user_uuid))
                conn.commit()
                asyncio.create_task(self._process_task_async(tid, username))
        except Exception as e:
            print(f"Error recovering pending tasks for '{username}': {e}")
        finally:
            conn.close()

    def get_user_backlog(self, username: str) -> List[dict]:
        """Fetches active and recent backlog tasks for user UI widget."""
        conn = database.get_db_connection(username)
        user_uuid = conn.user_uuid
        cursor = conn.cursor()
        try:
            # Auto-clean stuck processing status if quizzes already exist
            cursor.execute(
                """UPDATE videos SET status = 'ready' 
                   WHERE status = 'processing' AND user_uuid = %s 
                   AND id IN (SELECT DISTINCT video_id FROM quizzes WHERE user_uuid = %s);""",
                (user_uuid, user_uuid)
            )
            conn.commit()

            cursor.execute(
                """SELECT t.id, t.video_id, t.task_type, t.title, t.status, t.progress_stage, t.error_message, t.created_at,
                          v.thumbnail_url, v.youtube_id, v.duration_seconds
                   FROM import_tasks t
                   LEFT JOIN videos v ON t.video_id = v.id
                   WHERE t.user_uuid = %s
                   ORDER BY t.id DESC LIMIT 20;""",
                (user_uuid,)
            )
            tasks = [dict(row) for row in cursor.fetchall()]
            
            # Find any videos with status = 'processing' for this user that are not already present in import_tasks
            known_video_ids = {t["video_id"] for t in tasks if t.get("video_id")}
            cursor.execute(
                """SELECT id AS video_id, title, thumbnail_url, youtube_id, duration_seconds, created_at
                   FROM videos WHERE status = 'processing' AND user_uuid = %s;""",
                (user_uuid,)
            )
            for v_row in cursor.fetchall():
                v_dict = dict(v_row)
                if v_dict["video_id"] not in known_video_ids:
                    tasks.append({
                        "id": f"v_{v_dict['video_id']}",
                        "video_id": v_dict["video_id"],
                        "task_type": "youtube",
                        "title": v_dict["title"],
                        "status": "processing",
                        "progress_stage": "Processing AI Quizzes & SRS...",
                        "error_message": None,
                        "created_at": v_dict["created_at"],
                        "thumbnail_url": v_dict["thumbnail_url"],
                        "youtube_id": v_dict["youtube_id"],
                        "duration_seconds": v_dict.get("duration_seconds") or 0
                    })

            # Separate active tasks (pending/processing) from finished tasks (completed/failed)
            # Active tasks sort chronologically (oldest processing first, newest enqueued at bottom of queue).
            # Finished tasks sort newest first at the bottom of the list.
            active_tasks = [t for t in tasks if t.get("status") in ("pending", "processing")]
            completed_tasks = [t for t in tasks if t.get("status") not in ("pending", "processing")]

            def active_sort_key(t):
                c_at = str(t.get("created_at") or "")
                t_id = t.get("id")
                id_num = t_id if isinstance(t_id, int) else 999999
                return (c_at, id_num)

            def completed_sort_key(t):
                c_at = str(t.get("created_at") or "")
                t_id = t.get("id")
                id_num = t_id if isinstance(t_id, int) else 0
                return (c_at, id_num)

            active_tasks.sort(key=active_sort_key)
            completed_tasks.sort(key=completed_sort_key, reverse=True)

            return active_tasks + completed_tasks
        except Exception as e_backlog:
            print(f"Error in get_user_backlog for '{username}': {e_backlog}")
            traceback.print_exc()
            return []
        finally:
            conn.close()

    def retry_task(self, task_id: int, username: str) -> bool:
        """Resets a failed or incomplete task to pending and re-runs it."""
        conn = database.get_db_connection(username)
        user_uuid = conn.user_uuid
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT video_id FROM import_tasks WHERE id = %s AND user_uuid = %s;", (task_id, user_uuid))
            row = cursor.fetchone()
            if not row:
                return False

            if row.get("video_id"):
                cursor.execute("UPDATE videos SET status = 'processing', status_error = NULL WHERE id = %s AND user_uuid = %s;", (row["video_id"], user_uuid))

            cursor.execute(
                """UPDATE import_tasks 
                   SET status = 'pending', progress_stage = 'Retrying...', error_message = NULL, updated_at = CURRENT_TIMESTAMP 
                   WHERE id = %s AND user_uuid = %s;""",
                (task_id, user_uuid)
            )
            conn.commit()

            asyncio.create_task(self._process_task_async(task_id, username))
            return True
        finally:
            conn.close()

    def dismiss_task(self, task_id: int, username: str) -> bool:
        """Deletes a task record from backlog view."""
        conn = database.get_db_connection(username)
        user_uuid = conn.user_uuid
        cursor = conn.cursor()
        try:
            cursor.execute("DELETE FROM import_tasks WHERE id = %s AND user_uuid = %s;", (task_id, user_uuid))
            conn.commit()
            return True
        finally:
            conn.close()



queue_manager = ImportQueueManager.get_instance()
