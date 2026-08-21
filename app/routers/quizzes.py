import asyncio
import json
import logging
from math import floor, sqrt
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Form, HTTPException, Depends

from app import config, database, ai
from app.ai import UsageLimitExceeded
from app.dependencies import (
    get_active_username,
    get_srs_intervals,
    get_srs_multipliers,
    get_question_counts,
    get_preferred_hour,
    adjust_next_review,
    parse_bool,
    require_app_access,
    build_concept_pool,
    select_stage_questions,
)

logger = logging.getLogger("studiamo")

router = APIRouter(prefix="/api", tags=["Quizzes & SRS"])


@router.get("/quiz/{id}")
async def get_quiz(id: int, username: str = Depends(require_app_access)):
    """Retrieves full SRS quiz questions and stage metadata for a specific quiz ID."""
    conn = database.get_db_connection(username)
    user_uuid = conn.user_uuid
    cursor = conn.cursor()
    cursor.execute("""
        SELECT q.video_id, q.goal_id, q.importance_level, q.srs_stage, q.next_review_at, q.quiz_type, q.in_progress_index,
               v.title AS video_title, v.youtube_id, g.title AS goal_title
        FROM quizzes q
        LEFT JOIN videos v ON q.video_id = v.id
        LEFT JOIN goals g ON g.id = COALESCE(q.goal_id, v.learning_goal_id)
        WHERE q.id = %s AND q.user_uuid = %s;
    """, (id, user_uuid))
    db_row = cursor.fetchone()
    conn.close()

    quiz_data = database.get_quiz_row(id, username=username)
    if not isinstance(quiz_data, dict):
        quiz_data = None

    if not quiz_data or not quiz_data.get("questions"):
        if not db_row:
            raise HTTPException(status_code=404, detail="Quiz details not found in DB or JSON storage")
            
        video_id = db_row["video_id"]
        level = db_row["importance_level"] if db_row.get("importance_level") is not None else 3
        srs_stage = db_row["srs_stage"] if db_row.get("srs_stage") is not None else 0
        next_review_at = db_row.get("next_review_at")
        quiz_type = db_row.get("quiz_type") or "video"
        
        conn = database.get_db_connection(username)
        cursor = conn.cursor()
        cursor.execute("SELECT youtube_id, title FROM videos WHERE id = %s AND user_uuid = %s;", (video_id, user_uuid))
        v_row = cursor.fetchone()
        if not v_row:
            conn.close()
            raise HTTPException(status_code=404, detail="Video details not found for regeneration")
            
        yt_id = v_row.get("youtube_id")
        title = v_row.get("title")
        filename = yt_id if yt_id else f"doc_{video_id}"

        video_data = database.get_video_row(video_id, username=username)
        user_config = config.load_user_config(username)
        q_counts = get_question_counts(user_config)
        question_count = q_counts.get(5, 5)
        
        try:
            if yt_id:
                ai_quiz_data = ai.analyze_youtube_video(f"https://www.youtube.com/watch?v={yt_id}", question_count=question_count, username=username)
            else:
                desc_text = "\n".join(video_data.get("summary", [])) if video_data else title
                ai_quiz_data = ai.generate_topic_quiz(
                    topic=title,
                    description=desc_text[:6000],
                    question_count=question_count,
                    username=username
                )
        except UsageLimitExceeded as e:
            conn.close()
            raise HTTPException(status_code=429, detail=str(e))
        except Exception as e:
            conn.close()
            raise HTTPException(status_code=500, detail=f"Failed to automatically regenerate quiz: {e}")
            
        conn.close()

        
        quiz_json_payload = {
            "id": id,
            "video_id": video_id,
            "video_filename": filename,
            "quiz_type": quiz_type,
            "srs_stage": srs_stage,
            "next_review_at": next_review_at,
            "questions": ai_quiz_data.get("quiz", []),
            "importance_level": level
        }
        database.save_quiz_active_questions(id, quiz_json_payload["questions"], username=username)
        database.save_quiz_concept_pool(id, build_concept_pool(ai_quiz_data), username=username)
        quiz_data = quiz_json_payload
        
    srs_stage = 0
    if db_row and db_row["srs_stage"] is not None:
        srs_stage = db_row["srs_stage"]
    elif isinstance(quiz_data, dict) and "srs_stage" in quiz_data:
        srs_stage = quiz_data.get("srs_stage", 0)

    level = 3
    if db_row and db_row["importance_level"] is not None:
        level = db_row["importance_level"]
    elif isinstance(quiz_data, dict) and "importance_level" in quiz_data:
        level = quiz_data.get("importance_level", 3)

    user_config = config.load_user_config(username)
    q_counts = get_question_counts(user_config)
    target_count = q_counts.get(level, 5)

    # The stage-appropriate questions come from quizzes.concept_pool, which holds every
    # generated question tagged with its stage, filtered by whatever topics the user selected
    # in the Focus overlay. Quizzes created before that column existed have an empty pool and
    # fall through to questions_json, which is the stage-0 set they have always been served.
    concept_pool, focus_topics = database.get_quiz_pool_and_focus(id, username=username)
    questions_pool = select_stage_questions(concept_pool, srs_stage, focus_topics)

    if not questions_pool and isinstance(quiz_data, dict):
        questions_pool = quiz_data.get("questions") or quiz_data.get("quiz") or []

    def _is_valid_q(q):
        if isinstance(q, str) and q.strip():
            return True
        if isinstance(q, dict) and any(q.get(k) for k in ["question", "Question", "q", "prompt", "text", "title"]):
            return True
        return False

    valid_questions = [q for q in questions_pool if _is_valid_q(q)]

    # If quiz JSON had 0 valid questions stored, auto-repair by generating questions on the fly
    if not valid_questions and db_row:
        video_id = db_row["video_id"]
        if video_id:
            try:
                conn = database.get_db_connection(username)
                cursor = conn.cursor()
                cursor.execute("SELECT youtube_id, title FROM videos WHERE id = %s AND user_uuid = %s;", (video_id, user_uuid))
                v_row = cursor.fetchone()
                conn.close()
                if v_row:
                    filename = v_row["youtube_id"] if v_row["youtube_id"] else f"doc_{video_id}"
                    video_data = database.get_video_row(video_id, username=username)
                    yt_id = v_row["youtube_id"]
                    if yt_id:
                        ai_quiz_data = ai.analyze_youtube_video(f"https://www.youtube.com/watch?v={yt_id}", question_count=target_count, username=username)
                    else:
                        desc_text = "\n".join(video_data.get("summary", [])) if video_data else v_row["title"]
                        ai_quiz_data = ai.generate_topic_quiz(
                            topic=v_row["title"],
                            description=desc_text[:6000],
                            question_count=target_count,
                            username=username
                        )
                    questions_pool = ai_quiz_data.get("quiz", [])
                    if isinstance(quiz_data, dict):
                        quiz_data["questions"] = questions_pool
                        database.save_quiz_active_questions(id, questions_pool, username=username)
                    database.save_quiz_concept_pool(id, build_concept_pool(ai_quiz_data), username=username)
            except Exception as e:
                logger.error(f"Auto-repair quiz {id} failed: {e}")

    # Prefix slice, never a sample: verify-guess and quiz_attempts.question_index both address
    # questions by position, so the served list has to be a stable prefix of the stored one.
    active_questions = questions_pool[:target_count] if questions_pool else []

    # Keep questions_json in step with what is actually being served this session, so a typed
    # guess is verified against the question the user is looking at.
    stored_questions = quiz_data.get("questions") if isinstance(quiz_data, dict) else None
    if active_questions and active_questions != stored_questions:
        try:
            database.save_quiz_active_questions(id, active_questions, username=username)
        except Exception as e_sync:
            logger.warning(f"Could not materialize active questions for quiz {id}: {e_sync}")

    response_payload = dict(quiz_data) if isinstance(quiz_data, dict) else {}
    response_payload["questions"] = active_questions
    response_payload["srs_stage"] = srs_stage
    response_payload["importance_level"] = level
    response_payload["in_progress_index"] = db_row["in_progress_index"] if (db_row and "in_progress_index" in db_row.keys() and db_row["in_progress_index"] is not None) else (quiz_data.get("in_progress_index") if isinstance(quiz_data, dict) else 0)
    if db_row:
        response_payload["quiz_type"] = db_row.get("quiz_type") or "video"
        if db_row["video_title"]:
            response_payload["video_title"] = db_row["video_title"]
        if db_row["youtube_id"]:
            response_payload["youtube_id"] = db_row["youtube_id"]
        if db_row["goal_title"]:
            response_payload["goal_title"] = db_row["goal_title"]
        if "next_review_at" in db_row.keys() and db_row["next_review_at"]:
            raw_nr = db_row["next_review_at"]
            response_payload["next_review_at"] = raw_nr.isoformat() if hasattr(raw_nr, "isoformat") else str(raw_nr)
    return response_payload


@router.post("/tts")
async def generate_edge_tts(
    text: str = Form(...),
    speed: float = Form(1.0),
    username: str = Depends(require_app_access)
):
    """Generates audio bytes via Edge-TTS for question speech readout."""
    if not text or not text.strip():
        raise HTTPException(status_code=400, detail="No text provided for TTS")
    try:
        import base64
        audio_bytes, mime_type = await asyncio.to_thread(ai.generate_speech_audio, text.strip(), speed)
        base64_audio = base64.b64encode(audio_bytes).decode("utf-8")
        clean_mime = "audio/wav" if "wav" in mime_type or "pcm" in mime_type else mime_type
        return {"status": "success", "audio_data": f"data:{clean_mime};base64,{base64_audio}"}
    except Exception as e:
        logger.error(f"Edge TTS generation error: {e}")
        raise HTTPException(status_code=500, detail=f"Edge TTS voice synthesis failed: {e}")


@router.post("/quiz/{id}/grade")
async def grade_quiz(
    id: int,
    grade: str = Form(...),
    question_index: int = Form(...),
    question: str = Form(...),
    given_answer: str = Form(""),
    correct_answer: str = Form(...),
    progress_srs: bool = Form(True),
    is_final_question: bool = Form(False),
    explanation: Optional[str] = Form(None),
    feedback: Optional[str] = Form(None),
    username: str = Depends(require_app_access)
):
    """Grades a quiz attempt item, updates SRS stages on final completion, computes XP/Streaks, and updates badges."""
    if grade not in ["remembered", "forgot"]:
        raise HTTPException(status_code=400, detail="Invalid grade value.")
        
    conn = database.get_db_connection(username)
    user_uuid = conn.user_uuid
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT q.id, q.srs_stage, q.quiz_type, q.video_id, q.goal_id,
               v.importance_rating
        FROM quizzes q
        LEFT JOIN videos v ON q.video_id = v.id
        WHERE q.id = %s AND q.user_uuid = %s;
    """, (id, user_uuid))


    row = cursor.fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Quiz not found")
        
    is_final_bool = is_final_question if isinstance(is_final_question, bool) else (str(is_final_question).lower() in ("true", "1"))
    progress_srs_bool = progress_srs if isinstance(progress_srs, bool) else (str(progress_srs).lower() in ("true", "1"))

    current_stage = row["srs_stage"] if (row["srs_stage"] is not None) else 0
    importance = row["importance_rating"] if row["importance_rating"] is not None else 3
    
    intervals = get_srs_intervals(cursor, user_uuid=user_uuid)

    active_intervals = [x for x in intervals if x is not None]
    if not active_intervals:
        active_intervals = [1, 3, 7, 14, 30]
        
    num_stages = len(active_intervals)
    user_config = config.load_user_config(username)
    cap_by_importance = user_config.get("CAP_STAGES_BY_IMPORTANCE", False)
    
    if cap_by_importance:
        cap_1 = int(user_config.get("SRS_CAP_1", 2))
        cap_2 = int(user_config.get("SRS_CAP_2", 3))
        cap_3 = int(user_config.get("SRS_CAP_3", 4))
        cap_4 = int(user_config.get("SRS_CAP_4", 5))
        cap_5 = int(user_config.get("SRS_CAP_5", 5))
        importance_caps = {
            5: max(1, min(cap_5, num_stages)),
            4: max(1, min(cap_4, num_stages)),
            3: max(1, min(cap_3, num_stages)),
            2: max(1, min(cap_2, num_stages)),
            1: max(1, min(cap_1, num_stages))
        }
        max_stages = importance_caps.get(importance, num_stages)
    else:
        max_stages = num_stages

    multipliers = get_srs_multipliers(username)
    multiplier = multipliers.get(importance, 1.5)
    
    stage_unlocked_srs_5 = False
    next_stage = min(current_stage + 1, max_stages)
    if next_stage == num_stages and current_stage < num_stages:
        stage_unlocked_srs_5 = True
        
    stage_idx = max(0, min(next_stage - 1, num_stages - 1))
    days = active_intervals[stage_idx] * multiplier
    
    if grade == "remembered":
        xp_gain = 10
    else:
        xp_gain = 3
        
    pref_hour = get_preferred_hour(cursor, conn.user_uuid)
    enable_stage_5_rep = parse_bool(user_config.get("ENABLE_STAGE_5_REPETITION") if user_config.get("ENABLE_STAGE_5_REPETITION") is not None else user_config.get("enable_stage_5_repetition", config.DEFAULT_ENABLE_STAGE_5_REPETITION))
    stage_5_repeat_interval = int(user_config.get("STAGE_5_REPEAT_INTERVAL") if user_config.get("STAGE_5_REPEAT_INTERVAL") is not None else user_config.get("stage_5_repeat_interval", config.DEFAULT_STAGE_5_REPEAT_INTERVAL))

    if next_stage < max_stages or enable_stage_5_rep:
        if next_stage >= max_stages:
            days = stage_5_repeat_interval * multiplier
        next_review = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=days)
        next_review = adjust_next_review(next_review, pref_hour)
        next_review_iso = next_review.isoformat()
    else:
        # Graduated: final stage reached and stage-5 repetition is off (the default).
        # next_review_at is NOT NULL, so this can't be left as None, that used to throw
        # a DB error on the UPDATE below and abort grading before XP/streak were saved.
        # Push it far into the future instead, which keeps the quiz out of every "due"
        # query without giving it a real repeat schedule.
        next_review_iso = datetime(2999, 1, 1).isoformat()

    user_uuid = conn.user_uuid
    next_in_progress = question_index + 1
    if progress_srs_bool:
        if is_final_bool:
            cursor.execute(
                "UPDATE quizzes SET srs_stage = %s, next_review_at = %s, notified = 0, in_progress_index = NULL WHERE id = %s AND user_uuid = %s;",
                (next_stage, next_review_iso, id, user_uuid)
            )
        else:
            cursor.execute(
                "UPDATE quizzes SET in_progress_index = %s WHERE id = %s AND user_uuid = %s;",
                (next_in_progress, id, user_uuid)
            )
    
    cursor.execute(
        """INSERT INTO quiz_attempts (user_uuid, quiz_id, video_id, goal_id, question_index, question, given_answer, correct_answer, grade, xp_gained, explanation, feedback)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s);""",
        (user_uuid, id, row["video_id"], row["goal_id"], question_index, question, given_answer, correct_answer, grade, xp_gain, explanation, feedback)
    )
    
    cursor.execute("SELECT xp, level, streak, last_quiz_at, badges, review_mode FROM user_profile WHERE user_uuid = %s LIMIT 1;", (user_uuid,))
    row_user = cursor.fetchone()
    if not row_user:
        cursor.execute("SELECT xp, level, streak, last_quiz_at, badges, review_mode FROM user_profile WHERE LOWER(username) = LOWER(%s) LIMIT 1;", (username,))
        row_user = cursor.fetchone()
    if not row_user:
        conn.close()
        raise HTTPException(status_code=500, detail="User profile not found for XP grading.")
        
    user = dict(row_user)
    
    old_xp = user["xp"]
    new_xp = old_xp + xp_gain
    
    new_level = floor(sqrt(new_xp / 50)) + 1
    leveled_up = new_level > user["level"]
    
    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
    streak = user.get("streak", 0)
    if user.get("last_quiz_at"):
        try:
            raw_last = user["last_quiz_at"]
            last_dt = raw_last if isinstance(raw_last, datetime) else datetime.fromisoformat(str(raw_last))
            if last_dt.tzinfo is not None:
                last_dt = last_dt.replace(tzinfo=None)

            if (now_utc - last_dt) > timedelta(hours=48):
                streak = 1
            elif last_dt.date() < now_utc.date():
                streak += 1
        except Exception:
            streak = 1
    else:
        streak = 1
        
    badges = json.loads(user["badges"]) if user.get("badges") else []
    new_badges = []
    
    if streak >= 5 and "5-Day Streak" not in badges:
        new_badges.append("5-Day Streak")
    if streak >= 10 and "10-Day Streak" not in badges:
        new_badges.append("10-Day Streak")
        
    if stage_unlocked_srs_5 and "SRS Stage 5 Master" not in badges:
        new_badges.append("SRS Stage 5 Master")
        
    if "Video Collector" not in badges:
        cursor.execute("SELECT COUNT(*) FROM videos WHERE user_uuid = %s;", (user_uuid,))
        video_count = database.first_val(cursor.fetchone())
        if video_count >= 10:
            new_badges.append("Video Collector")
        
    if "Renaissance Learner" not in badges:
        cursor.execute("SELECT COUNT(DISTINCT category) FROM videos WHERE user_uuid = %s;", (user_uuid,))
        category_count = database.first_val(cursor.fetchone())
        if category_count >= 3:
            new_badges.append("Renaissance Learner")

        
    badges.extend(new_badges)
    
    cursor.execute(
        """UPDATE user_profile 
           SET xp = %s, level = %s, streak = %s, last_quiz_at = %s, badges = %s WHERE user_uuid = %s;""",
        (new_xp, new_level, streak, now_utc.isoformat(), json.dumps(badges), user_uuid)
    )


    
    if progress_srs_bool:
        # The srs_stage and next_review_at columns were already written above; this keeps the
        # in-progress position in step. Finishing a session clears it, mid-session advances it.
        if is_final_bool:
            database.update_quiz_progress(id, username=username, in_progress_index=None)
        else:
            database.update_quiz_progress(id, username=username, in_progress_index=next_in_progress)

        # A block here previously read the video row, set srs_stage and next_review_at on the
        # dict, and wrote it back. The videos table has neither column, and save_video_json
        # persisted only summary, outline and fact_check, so it rewrote those three to
        # themselves and changed nothing. Removed rather than translated.
                
    conn.commit()
    conn.close()
    
    return {
        "status": "success",
        "new_stage": next_stage,
        "xp_gained": xp_gain,
        "total_xp": new_xp,
        "level": new_level,
        "streak": streak,
        "leveled_up": leveled_up,
        "new_badges": new_badges
    }


@router.post("/quiz/{id}/reschedule")
async def reschedule_quiz(id: int, username: str = Depends(require_app_access)):
    """Reschedules a quiz review by 1 day."""
    conn = database.get_db_connection(username)
    user_uuid = conn.user_uuid
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM quizzes WHERE id = %s AND user_uuid = %s;", (id, user_uuid))
    row = cursor.fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Quiz not found")
        
    pref_hour = get_preferred_hour(cursor, user_uuid)
    next_review = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=1)
    next_review = adjust_next_review(next_review, pref_hour)

    cursor.execute("UPDATE quizzes SET next_review_at = %s, notified = 0 WHERE id = %s AND user_uuid = %s;", (next_review.isoformat(), id, user_uuid))
    conn.commit()
    conn.close()


    return {"status": "success", "next_review_at": next_review.isoformat()}


@router.post("/quiz/verify-guess")
async def verify_quiz_guess(
    quiz_id: int = Form(...),
    question_index: int = Form(...),
    user_guess: str = Form(""),
    username: str = Depends(require_app_access)
):
    """Uses Gemini AI to conceptually evaluate a user's typed guess against the correct answer."""
    quiz_data = database.get_quiz_row(quiz_id, username=username)
    if not quiz_data or "questions" not in quiz_data:
        raise HTTPException(status_code=404, detail="Quiz payload not found")
        
    questions = quiz_data.get("questions", [])
    if question_index < 0 or question_index >= len(questions):
        raise HTTPException(status_code=400, detail="Invalid question index")
        
    q_obj = questions[question_index]
    question_text = q_obj.get("question", "") if isinstance(q_obj, dict) else str(q_obj)
    correct_answer = q_obj.get("answer", "") if isinstance(q_obj, dict) else ""
    
    if not user_guess or not user_guess.strip():
        return {
            "is_correct": False,
            "feedback": "Flipped card directly without typing a guess."
        }
        
    try:
        video_id = quiz_data.get("video_id") if isinstance(quiz_data, dict) else None
        res = ai.verify_user_guess(question_text, correct_answer, user_guess, quiz_id=quiz_id, video_id=video_id, username=username)
        return res
    except Exception as e:
        logger.error(f"Error in verify_quiz_guess: {e}")
        return {
            "is_correct": False,
            "feedback": f"Could not perform AI conceptual check: {e}"
        }

