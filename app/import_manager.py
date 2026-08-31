import io
import os
import time
import json
import asyncio
import traceback
from abc import ABC, abstractmethod
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional, List, Union
from pathlib import Path


from app import database, config, storage, ai, youtube


# ==============================================================================
# BETA-ONLY: import progress-bar calibration telemetry.
#
# Feeds the `import_timings` table, which exists purely to tune the fake-progress
# constants in static/js/core.js (renderProgressOnly). Records only how long an
# import took and what it was importing, no username, no user_uuid, no title.
#
# Collection now defaults to off: the progress bar has the calibration data it was
# added to gather. Set ENABLE_IMPORT_TIMING_LOG=true to resume recording, which is
# worth doing for a while after any change that alters how long an import takes.
#
# TO REMOVE ENTIRELY: delete this function and its two call sites in _execute_task
# (search "_log_import_timing"), then drop the table. Note the DROP needs its own
# migration script, since schema.py only ever adds.
# ==============================================================================
ENABLE_IMPORT_TIMING_LOG = os.getenv("ENABLE_IMPORT_TIMING_LOG", "false").strip().lower() in ("1", "true", "yes", "on")


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
    build_concept_pool,
)


# How long a finished import stays in the backlog drawer. The drawer reports what is running
# now, so a completed or failed task older than this is history rather than status. Without a
# window, a single failure kept greeting the user every time the drawer opened, including one
# raised by an import path that had since been replaced entirely.
FINISHED_TASK_RETENTION_DAYS = 7


class ImportInputError(ValueError):
    """Raised when the material itself is the problem, carrying copy safe to show a user.

    Subclasses ValueError so this stays a drop-in replacement for the plain ValueErrors the
    processors used to raise.
    """


_GENERIC_IMPORT_ERROR = (
    "Something went wrong while importing this. Please try again, and contact "
    "hello@studiamo.cloud if it keeps failing."
)


def _user_facing_error(exc: Exception) -> str:
    """Reduces an import failure to a message that is safe and useful to put on screen.

    A failure reaches the user twice, in the import drawer and on the material card, so only
    curated copy may be written to `import_tasks.error_message` and `videos.status_error`.
    Three exception types carry such copy by construction: ImportInputError above, and ai.py's
    AIServiceUnavailable / UsageLimitExceeded. Everything else is a bug or a raw provider
    payload, and writing str(e) put a rate-limit body complete with a signed URL, a stack of
    library-internal advice and a link to file a GitHub issue in front of the user. The full
    text is not lost, the caller logs it with the task id and a traceback.
    """
    if isinstance(exc, (ImportInputError, ai.AIServiceUnavailable, ai.UsageLimitExceeded)):
        message = str(exc).strip()
        if message:
            return message
    return _GENERIC_IMPORT_ERROR


def _note_text_truncation(analysis: dict, summary: list) -> list:
    """Prepends a notice when only part of a document reached the AI.

    The long-document counterpart of the long-video notice in the YouTube path. The import
    still succeeds either way, so without this the summary and quizzes would cover just the
    opening section with nothing on screen saying so. Word count comes from the constant
    rather than being written out here, so the two cannot drift apart.
    """
    if not analysis.get("text_truncated"):
        return list(summary)
    return [
        f"⚠️ Only the first {ai.MAX_TRANSCRIPT_WORDS:,} words of this content were processed, "
        f"due to technical limitations."
    ] + list(summary)


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
            raise ImportInputError("Invalid YouTube URL.")

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

        q_counts = get_question_counts(username)
        question_count = q_counts.get(5, 5)

        update_stage_fn("Step 2/2: Gemini Analyzing Video & Generating Quizzes...")

        # Read the goal before the AI call, not after: it is passed into the prompt as an
        # attention filter, so it has to be known up front. The post-analysis lookup further
        # down still runs, because it also renames the video's category.
        goal_title, goal_description = "", ""
        if learning_goal_id:
            conn_goal = database.get_db_connection(username)
            try:
                cur_goal = conn_goal.cursor()
                cur_goal.execute(
                    "SELECT title, description FROM goals WHERE id = %s AND user_uuid = %s;",
                    (learning_goal_id, conn_goal.user_uuid)
                )
                g_row = cur_goal.fetchone()
                if g_row:
                    goal_title = g_row.get("title") or ""
                    goal_description = g_row.get("description") or ""
            except Exception as e_goal:
                print(f"[YouTubeTaskProcessor] Could not read goal {learning_goal_id} for prompt focus: {e_goal}")
            finally:
                conn_goal.close()

        analysis = ai.analyze_youtube_video(
            url,
            question_count,
            username=username,
            goal_title=goal_title,
            goal_description=goal_description
        )

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
            pool_json = json.dumps(build_concept_pool(analysis))

            cursor.execute(
                """INSERT INTO quizzes
                   (user_uuid, video_id, quiz_type, srs_stage, next_review_at, notified, importance_level, questions_json, concept_pool)
                   VALUES (%s, %s, 'video', 0, %s, 0, %s, %s::jsonb, %s::jsonb) RETURNING id;""",
                (user_uuid, video_id, next_review.isoformat(), importance_rating, q_json, pool_json)
            )
            res = cursor.fetchone()
            quiz_id = res["id"] if isinstance(res, dict) and "id" in res else res[0]

            database.save_video_analysis(
                video_id, username,
                summary=summary, outline=outline, fact_check=fact_check_result
            )


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
            raise ImportInputError("Uploaded document file was not found on server.")

        # doc_file's own extension was already validated at upload time
        # (storage.safe_doc_extension), reuse it here so save/serve/delete
        # all agree on the same doc_<video_id><ext> naming.
        saved_doc_path = storage.get_document_path(video_id, doc_file.suffix.lower(), username=username)

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
                raise ImportInputError("No text could be extracted from the PDF.")
        else:
            extracted_text = file_bytes.decode("utf-8", errors="ignore").strip()

        if len(extracted_text) < 30:
            raise ImportInputError("Document content is too short to generate high-quality quizzes.")

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

        q_counts = get_question_counts(username)
        question_count = q_counts.get(5, 5)

        update_stage_fn("Step 3/3: AI Generating 25 Quiz Items...")
        analysis = ai.analyze_video_transcript(extracted_text, question_count, active_goals, username=username)

        conn = database.get_db_connection(username)
        user_uuid = conn.user_uuid
        cursor = conn.cursor()
        try:

            category = analysis.get("category", "General")
            summary = _note_text_truncation(analysis, analysis.get("summary", []))
            outline = analysis.get("outline", [])
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
            pool_json = json.dumps(build_concept_pool(analysis))

            cursor.execute(
                """INSERT INTO quizzes
                   (user_uuid, video_id, quiz_type, srs_stage, next_review_at, notified, importance_level, questions_json, concept_pool)
                   VALUES (%s, %s, 'video', 0, %s, 0, %s, %s::jsonb, %s::jsonb) RETURNING id;""",
                (user_uuid, video_id, next_review.isoformat(), importance_rating, q_json, pool_json)
            )
            res = cursor.fetchone()
            quiz_id = res["id"] if isinstance(res, dict) and "id" in res else res[0]

            database.save_video_analysis(
                video_id, username,
                summary=summary, outline=outline, fact_check=fact_check_result
            )


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
            raise ImportInputError("Notes text is too short to generate high-quality quizzes.")

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

        q_counts = get_question_counts(username)
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
            summary = _note_text_truncation(analysis, analysis.get("summary", []))
            outline = analysis.get("outline", [])
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
            pool_json = json.dumps(build_concept_pool(analysis))

            cursor.execute(
                """INSERT INTO quizzes
                   (user_uuid, video_id, quiz_type, srs_stage, next_review_at, notified, importance_level, questions_json, concept_pool)
                   VALUES (%s, %s, 'video', 0, %s, 0, %s, %s::jsonb, %s::jsonb) RETURNING id;""",
                (user_uuid, video_id, next_review.isoformat(), importance_rating, q_json, pool_json)
            )
            res = cursor.fetchone()
            quiz_id = res["id"] if isinstance(res, dict) and "id" in res else res[0]

            database.save_video_analysis(
                video_id, username,
                summary=summary, outline=outline, fact_check=fact_check_result
            )


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
                raise ImportInputError("Goal not found.")

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
                raise ImportInputError("Goal not found.")

            cursor.execute("SELECT id, title, youtube_id FROM videos WHERE learning_goal_id = %s AND user_uuid = %s AND status = 'ready';", (goal_id, user_uuid))
            goal_videos = [dict(r) for r in cursor.fetchall()]


            transcripts = []
            for gv in goal_videos:
                vdata = database.get_video_row(gv["id"], username=username)
                if vdata and vdata.get("summary"):
                    transcripts.append(f"Video '{gv['title']}':\n" + "\n".join(vdata.get("summary", [])))

            if not transcripts:
                raise ImportInputError("No video summaries available under this goal.")

            combined_text = "\n\n---\n\n".join(transcripts)
            analysis = ai.analyze_video_transcript(combined_text, question_count, [], username=username)

            quiz_items = analysis.get("quiz", [])
            intervals = get_srs_intervals(cursor, user_uuid=user_uuid)
            pref_hour = get_preferred_hour(cursor, user_uuid)
            next_review = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=intervals[0])
            next_review = adjust_next_review(next_review, pref_hour)

            q_list = [dict(q) for q in quiz_items]
            q_json = json.dumps(q_list)
            pool_json = json.dumps(build_concept_pool(analysis))

            cursor.execute(
                """INSERT INTO quizzes
                   (user_uuid, video_id, goal_id, quiz_type, srs_stage, next_review_at, notified, importance_level, questions_json, concept_pool)
                   VALUES (%s, NULL, %s, 'goal', 0, %s, 0, 3, %s::jsonb, %s::jsonb) RETURNING id;""",
                (user_uuid, goal_id, next_review.isoformat(), q_json, pool_json)
            )
            res = cursor.fetchone()
            quiz_id = res["id"] if isinstance(res, dict) and "id" in res else res[0]

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
        # Task ids currently executing, so the same task cannot be launched twice. See
        # _process_task_async for why that matters.
        self._inflight_task_ids: set = set()

    def is_task_inflight(self, task_id: int) -> bool:
        """Returns True if the task is currently executing in this process."""
        return task_id in self._inflight_task_ids

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
        """Runs a task once, ignoring a launch for a task that is already running.

        The retry control appears in two places for the same failed import, on the material
        card and in the import drawer, and neither the route nor retry_task checked whether a
        run was already in flight. Two runs of the same task upload the same video within the
        same minute and, between them, exceed the per-minute token quota, so a retry reliably
        recreated the rate limit that had made the import fail in the first place: measured at
        four attempts and two minutes per run, twice over, while a single import of the same
        size succeeded moments later.

        Tracked in memory rather than by task status, because both launches read the row
        before either has written 'processing' to it.
        """
        if task_id in self._inflight_task_ids:
            print(f"[ImportQueueManager] Task #{task_id} is already running, ignoring duplicate launch.")
            return

        self._inflight_task_ids.add(task_id)
        try:
            await self._run_task_async(task_id, username)
        finally:
            self._inflight_task_ids.discard(task_id)

    async def _run_task_async(self, task_id: int, username: str):
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

                # Claim the task, and only proceed if this worker won it. The `status <>
                # 'processing'` predicate makes the update the claim: whichever connection
                # commits first flips the row, the other matches nothing and backs out.
                #
                # The in-memory guard above only covers one process, and more than one app
                # instance can share a database: a second instance picks up a task left
                # 'pending' when it recovers on startup, and both then upload the same video
                # inside the same minute and exhaust the per-minute token quota between them.
                # That is what made retrying an import fail while importing the same video
                # fresh succeeded.
                cursor.execute(
                    """UPDATE import_tasks
                          SET status = 'processing', progress_stage = 'Starting...', updated_at = CURRENT_TIMESTAMP
                        WHERE id = %s AND user_uuid = %s AND status <> 'processing'
                    RETURNING id;""",
                    (task_id, user_uuid)
                )
                claimed = cursor.fetchone()
                conn.commit()
                if not claimed:
                    print(f"[ImportQueueManager] Task #{task_id} is already claimed by another worker, skipping.")
                    conn.close()
                    return

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
                user_message = _user_facing_error(e)
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
                            (user_message, task_id, user_uuid)
                        )
                        if task_dict and task_dict.get("video_id"):
                            fail_cur.execute(
                                "UPDATE videos SET status = 'failed', status_error = %s WHERE id = %s AND user_uuid = %s;",
                                (user_message, task_dict["video_id"], user_uuid)
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
        """Resumes incomplete tasks after a restart, and does the backlog's housekeeping.

        Runs both at startup (per user, from main.lifespan) and every minute from the
        scheduler daemon, which is why the retention sweep lives here rather than in its own
        pass: this already holds a connection for the user.
        """
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

            # Retire finished tasks past the retention window. Only the row goes: an import
            # that produced a video wrote it long before this, and import_tasks.video_id is a
            # reference to that video, not the other way around.
            cursor.execute(
                """DELETE FROM import_tasks
                    WHERE user_uuid = %s
                      AND status IN ('completed', 'failed')
                      AND updated_at < CURRENT_TIMESTAMP - (INTERVAL '1 day' * %s)
                 RETURNING id;""",
                (user_uuid, FINISHED_TASK_RETENTION_DAYS)
            )
            purged = cursor.fetchall()
            conn.commit()
            if purged:
                print(
                    f"[ImportQueueManager] Removed {len(purged)} finished import task(s) older "
                    f"than {FINISHED_TASK_RETENTION_DAYS} days for user '{username}'."
                )

            # Only tasks that have gone quiet. A running task touches updated_at at every
            # progress step, so anything newer than this is being worked on right now, either
            # by this process or by another instance sharing the database.
            #
            # Recovering those was actively harmful: this resets status to 'pending' before
            # relaunching, which also defeats the claim in _run_task_async, so a restart during
            # an import produced a second worker for a task already in flight. Both then
            # uploaded the same video within the same minute and exhausted the per-minute token
            # quota between them. A failing import is the most exposed, because its backoff
            # keeps it alive for two minutes rather than the fifty seconds a successful one
            # takes.
            cursor.execute(
                """SELECT id FROM import_tasks
                    WHERE status IN ('pending', 'processing')
                      AND user_uuid = %s
                      AND updated_at < CURRENT_TIMESTAMP - INTERVAL '15 minutes';""",
                (user_uuid,)
            )
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

    def recover_all_pending_tasks(self):
        """Scans database periodically across all users for orphaned incomplete tasks and resumes them."""
        try:
            for username in database.get_all_users():
                self.recover_pending_tasks(username)
        except Exception as e:
            print(f"Error during periodic task recovery: {e}")

    def reset_inflight_tasks_on_shutdown(self):
        """Resets tasks currently running in memory to pending on graceful server shutdown.

        Setting updated_at back ensures that the next process start immediately picks them up
        instead of waiting for the 15-minute quiet threshold."""
        if not self._inflight_task_ids:
            return
        try:
            raw_conn = database.get_pooled_raw_connection()
            try:
                cursor = raw_conn.cursor()
                task_ids = list(self._inflight_task_ids)
                cursor.execute(
                    """UPDATE import_tasks 
                       SET status = 'pending', progress_stage = 'Queued (Restart)',
                           updated_at = CURRENT_TIMESTAMP - INTERVAL '16 minutes'
                       WHERE id = ANY(%s) AND status = 'processing';""",
                    (task_ids,)
                )
                if not getattr(raw_conn, "autocommit", False):
                    raw_conn.commit()
                cursor.close()
            finally:
                database.release_pooled_connection(raw_conn)
        except Exception as e:
            print(f"Error resetting in-flight tasks on shutdown: {e}")

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

    def retry_task(self, task_id: Union[int, str], username: str) -> bool:
        """Resets a failed or incomplete task to pending and re-runs it."""
        tid_str = str(task_id)
        if tid_str.startswith("v_"):
            conn = database.get_db_connection(username)
            user_uuid = conn.user_uuid
            cursor = conn.cursor()
            try:
                vid = int(tid_str.replace("v_", ""))
                cursor.execute("SELECT id, youtube_id, title FROM videos WHERE id = %s AND user_uuid = %s;", (vid, user_uuid))
                v_row = cursor.fetchone()
                if not v_row:
                    return False
                yt_id = v_row.get("youtube_id")
                payload = {}
                if yt_id and not yt_id.startswith("doc_"):
                    payload = {"url": f"https://www.youtube.com/watch?v={yt_id}", "importance_rating": 3}
                    task_type = "youtube"
                else:
                    task_type = "document"
                cursor.execute("UPDATE videos SET status = 'processing', status_error = NULL WHERE id = %s AND user_uuid = %s;", (vid, user_uuid))
                conn.commit()
                self.enqueue_task(
                    username=username,
                    task_type=task_type,
                    title=v_row.get("title") or f"Content {vid}",
                    payload=payload,
                    video_id=vid
                )
                return True
            except Exception as e:
                print(f"[retry_task] Error retrying synthetic video task {task_id}: {e}")
                return False
            finally:
                conn.close()

        conn = database.get_db_connection(username)
        user_uuid = conn.user_uuid
        cursor = conn.cursor()
        try:
            numeric_tid = int(task_id)
            cursor.execute("SELECT video_id FROM import_tasks WHERE id = %s AND user_uuid = %s;", (numeric_tid, user_uuid))
            row = cursor.fetchone()
            if not row:
                return False

            if row.get("video_id"):
                cursor.execute("UPDATE videos SET status = 'processing', status_error = NULL WHERE id = %s AND user_uuid = %s;", (row["video_id"], user_uuid))

            cursor.execute(
                """UPDATE import_tasks 
                   SET status = 'pending', progress_stage = 'Retrying...', error_message = NULL, updated_at = CURRENT_TIMESTAMP 
                   WHERE id = %s AND user_uuid = %s;""",
                (numeric_tid, user_uuid)
            )
            conn.commit()

            asyncio.create_task(self._process_task_async(numeric_tid, username))
            return True
        except (ValueError, TypeError):
            return False
        finally:
            conn.close()

    def dismiss_task(self, task_id: Union[int, str], username: str) -> bool:
        """Deletes a task record or clears stuck synthetic task from backlog view."""
        tid_str = str(task_id)
        conn = database.get_db_connection(username)
        user_uuid = conn.user_uuid
        cursor = conn.cursor()
        try:
            if tid_str.startswith("v_"):
                try:
                    vid = int(tid_str.replace("v_", ""))
                    cursor.execute("DELETE FROM videos WHERE id = %s AND user_uuid = %s AND status = 'processing';", (vid, user_uuid))
                    conn.commit()
                    return True
                except ValueError:
                    return False

            numeric_tid = int(task_id)
            cursor.execute("DELETE FROM import_tasks WHERE id = %s AND user_uuid = %s;", (numeric_tid, user_uuid))
            conn.commit()
            return True
        except (ValueError, TypeError):
            return False
        finally:
            conn.close()



queue_manager = ImportQueueManager.get_instance()
