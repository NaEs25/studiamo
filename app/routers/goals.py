import json
import re
import asyncio
from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import APIRouter, Form, HTTPException, Depends, Query
from fastapi.responses import JSONResponse

from app import config, database, storage, ai, youtube
from app.dependencies import (
    get_active_username,
    get_srs_intervals,
    get_srs_multipliers,
    get_preferred_hour,
    adjust_next_review,
    require_app_access,
    build_concept_pool,
)

import logging

logger = logging.getLogger("studiamo")

router = APIRouter(prefix="/api", tags=["Goals"])



@router.get("/goals")
async def get_goals(include_archived: bool = False, username: str = Depends(require_app_access)):
    """Retrieves all active or archived goals along with their associated videos for active user."""
    conn = database.get_db_connection(username)
    user_uuid = conn.user_uuid
    cursor = conn.cursor()
    
    archived_clause = "AND g.is_archived = 1" if include_archived else "AND g.is_archived = 0"
    cursor.execute(f"""
        SELECT g.id, g.title, g.description, g.order_index, g.created_at, g.is_archived,
               CASE WHEN gr.recommendations_json IS NOT NULL AND gr.recommendations_json != '' AND gr.recommendations_json != '{{}}' THEN 1 ELSE 0 END AS has_saved_recommendations
        FROM goals g
        LEFT JOIN goal_recommendations gr ON g.id = gr.goal_id AND g.user_uuid = gr.user_uuid
        WHERE g.user_uuid = %s {archived_clause}
        ORDER BY g.order_index ASC, g.id ASC;
    """, (user_uuid,))
    rows = cursor.fetchall()
    if not rows:
        conn.close()
        return []

    goal_ids = [r["id"] for r in rows]
    cursor.execute("SELECT id, title, youtube_id, category, goal_order_index, learning_goal_id FROM videos WHERE user_uuid = %s AND learning_goal_id = ANY(%s) AND is_archived = 0 ORDER BY goal_order_index ASC, id DESC;", (user_uuid, goal_ids))
    all_videos = cursor.fetchall()
    conn.close()

    videos_by_goal = {}
    for v in all_videos:
        gid = v["learning_goal_id"]
        if gid not in videos_by_goal:
            videos_by_goal[gid] = []
        v_dict = dict(v)
        v_dict.pop("learning_goal_id", None)
        videos_by_goal[gid].append(v_dict)

    goals = []
    for row in rows:
        goal_item = dict(row)
        goal_item["videos"] = videos_by_goal.get(row["id"], [])
        goals.append(goal_item)
    return goals


def _assert_title_available(cursor, user_uuid: str, title: str, exclude_goal_id: int = None) -> None:
    """Rejects a goal title the user already has, compared case- and whitespace-insensitively.

    Backed by the uq_goals_user_title_lower index in schema.py, which is what actually
    guarantees uniqueness under concurrent requests. This check exists so the common case
    returns a readable message instead of a database integrity error.

    Archived goals count as taken. Allowing reuse while one is archived would mean
    un-archiving it later could collide with a goal created in the meantime, and the
    un-archive is the worse place to discover that.
    """
    clean = (title or "").strip()
    if not clean:
        raise HTTPException(status_code=400, detail="Give the goal a title.")

    sql = "SELECT id, is_archived FROM goals WHERE user_uuid = %s AND LOWER(TRIM(title)) = LOWER(%s)"
    params = [user_uuid, clean]
    if exclude_goal_id is not None:
        sql += " AND id <> %s"
        params.append(exclude_goal_id)
    cursor.execute(sql + " LIMIT 1;", tuple(params))

    existing = cursor.fetchone()
    if existing:
        if existing.get("is_archived"):
            raise HTTPException(
                status_code=409,
                detail=f'You already have an archived goal called "{clean}". Restore it from the archive, or pick a different title.'
            )
        raise HTTPException(status_code=409, detail=f'You already have a goal called "{clean}".')


@router.post("/goals")
async def create_goal(title: str = Form(...), description: str = Form(""), username: str = Depends(require_app_access)) -> JSONResponse:
    """Creates a new learning goal and saves its JSON file."""
    conn = database.get_db_connection(username)
    user_uuid = conn.user_uuid
    cursor = conn.cursor()

    try:
        _assert_title_available(cursor, user_uuid, title)
    except HTTPException:
        conn.close()
        raise

    cursor.execute("SELECT COALESCE(MAX(order_index), 0) + 1 FROM goals WHERE user_uuid = %s;", (user_uuid,))
    next_order = database.first_val(cursor.fetchone(), default=1)

    
    cursor.execute("INSERT INTO goals (user_uuid, title, description, order_index) VALUES (%s, %s, %s, %s) RETURNING id;", (user_uuid, title.strip(), description.strip(), next_order))
    res = cursor.fetchone()
    goal_id = res["id"] if isinstance(res, dict) and "id" in res else (res[0] if res else cursor.lastrowid)
    
    conn.commit()
    conn.close()
    return JSONResponse({"status": "success", "goal_id": goal_id, "title": title})


@router.post("/goals/{id}/edit")
async def edit_goal(id: int, title: str = Form(...), description: str = Form(""), username: str = Depends(require_app_access)):
    """Edits a learning goal title and description, cascading video category renames."""
    conn = database.get_db_connection(username)
    user_uuid = conn.user_uuid
    cursor = conn.cursor()

    try:
        _assert_title_available(cursor, user_uuid, title, exclude_goal_id=id)
    except HTTPException:
        conn.close()
        raise

    cursor.execute("UPDATE goals SET title = %s, description = %s WHERE id = %s AND user_uuid = %s;", (title.strip(), description.strip(), id, user_uuid))
    if cursor.rowcount == 0:
        conn.close()
        raise HTTPException(status_code=404, detail="Goal not found")
    cursor.execute("UPDATE videos SET category = %s WHERE learning_goal_id = %s AND user_uuid = %s;", (title.strip(), id, user_uuid))

    conn.commit()
    conn.close()
    return {"status": "success", "title": title}


@router.post("/goals/{id}/reorder")
async def reorder_goal(id: int, direction: str = Form(...), username: str = Depends(require_app_access)):
    """Reorders a goal position up or down among active goals."""
    conn = database.get_db_connection(username)
    user_uuid = conn.user_uuid
    cursor = conn.cursor()
    
    cursor.execute("SELECT id, title, description, order_index, created_at FROM goals WHERE user_uuid = %s AND is_archived = 0 ORDER BY order_index ASC, id ASC;", (user_uuid,))
    goals_list = [dict(r) for r in cursor.fetchall()]
    
    current_idx = next((i for i, g in enumerate(goals_list) if g["id"] == id), None)
    if current_idx is None:
        conn.close()
        raise HTTPException(status_code=404, detail="Goal not found")
        
    swap_idx = None
    if direction == "up" and current_idx > 0:
        swap_idx = current_idx - 1
    elif direction == "down" and current_idx < len(goals_list) - 1:
        swap_idx = current_idx + 1
        
    if swap_idx is not None:
        g1 = goals_list[current_idx]
        g2 = goals_list[swap_idx]
        
        idx1 = g2["order_index"]
        idx2 = g1["order_index"]
        
        if idx1 == idx2:
            for i, g in enumerate(goals_list):
                new_order = (swap_idx + 1) if i == current_idx else ((current_idx + 1) if i == swap_idx else (i + 1))
                cursor.execute("UPDATE goals SET order_index = %s WHERE id = %s AND user_uuid = %s;", (new_order, g["id"], user_uuid))
                g["order_index"] = new_order
            conn.commit()
        else:
            cursor.execute("UPDATE goals SET order_index = %s WHERE id = %s AND user_uuid = %s;", (idx1, g1["id"], user_uuid))
            cursor.execute("UPDATE goals SET order_index = %s WHERE id = %s AND user_uuid = %s;", (idx2, g2["id"], user_uuid))
            conn.commit()
            g1["order_index"] = idx1
            g2["order_index"] = idx2
            
    conn.close()
    return {"status": "success"}


@router.delete("/goals/{id}")
async def delete_goal(
    id: int,
    delete_materials: bool = Query(False),
    username: str = Depends(require_app_access)
):
    """Deletes a learning goal and optionally deletes associated videos and quizzes."""
    conn = database.get_db_connection(username)
    user_uuid = conn.user_uuid
    cursor = conn.cursor()

    cursor.execute("SELECT id FROM goals WHERE id = %s AND user_uuid = %s;", (id, user_uuid))
    if not cursor.fetchone():
        conn.close()
        raise HTTPException(status_code=404, detail="Goal not found")

    if delete_materials:
        cursor.execute("SELECT id, youtube_id FROM videos WHERE learning_goal_id = %s AND user_uuid = %s;", (id, user_uuid))
        video_rows = cursor.fetchall()
        for v in video_rows:
            v_id = v["id"]
            yt_id = v.get("youtube_id") or f"doc_{v_id}"
            cursor.execute("DELETE FROM quiz_attempts WHERE video_id = %s AND user_uuid = %s;", (v_id, user_uuid))
            cursor.execute("DELETE FROM quizzes WHERE video_id = %s AND user_uuid = %s;", (v_id, user_uuid))
            cursor.execute("DELETE FROM videos WHERE id = %s AND user_uuid = %s;", (v_id, user_uuid))
            storage.delete_video_json(yt_id, username=username)
    else:
        cursor.execute("UPDATE videos SET learning_goal_id = NULL WHERE learning_goal_id = %s AND user_uuid = %s;", (id, user_uuid))
        
    cursor.execute("DELETE FROM goals WHERE id = %s AND user_uuid = %s;", (id, user_uuid))
    conn.commit()
    conn.close()
    return {"status": "success", "message": "Learning goal deleted successfully"}


@router.post("/goals/{id}/archive")
async def archive_goal(id: int, username: str = Depends(require_app_access)):
    """Toggles archived status for a learning goal."""
    conn = database.get_db_connection(username)
    user_uuid = conn.user_uuid
    cursor = conn.cursor()
    cursor.execute("SELECT id, title, description, order_index, is_archived FROM goals WHERE id = %s AND user_uuid = %s;", (id, user_uuid))
    row = cursor.fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Goal not found")
    
    goal_dict = dict(row)
    new_state = 0 if goal_dict.get("is_archived") else 1
    cursor.execute("UPDATE goals SET is_archived = %s WHERE id = %s AND user_uuid = %s;", (new_state, id, user_uuid))
    conn.commit()
    conn.close()
    return {"status": "success", "is_archived": new_state}


@router.get("/goals/{id}/recommendations")
async def get_goal_recommendations(id: int, username: str = Depends(require_app_access)):
    """Generates AI search queries & scraped YouTube video recommendations for a specific goal."""
    saved = storage.get_saved_goal_recommendations(id, username=username)
    if saved and saved.get("videos"):
        return saved

    conn = database.get_db_connection(username)
    user_uuid = conn.user_uuid
    cursor = conn.cursor()
    cursor.execute("SELECT title, description FROM goals WHERE id = %s AND user_uuid = %s;", (id, user_uuid))
    row = cursor.fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="Goal not found")
        
    try:
        recs = await asyncio.to_thread(ai.generate_goal_recommendations, row["title"], row["description"], username)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AI recommendations generation failed: {e}")
        
    queries = recs.get("search_queries", [])
    key_concepts = recs.get("key_concepts", [])
    
    excluded_yt_ids = storage.get_excluded_youtube_ids(username=username)
    
    videos = []
    seen_ids = set()
    for q in queries:
        v_list = await asyncio.to_thread(youtube.search_youtube_recommendations, q, 4)
        for v in v_list:
            yt_id = v.get("youtube_id")
            if yt_id and yt_id not in excluded_yt_ids and yt_id not in seen_ids and youtube.is_valid_duration(v.get("duration")):
                seen_ids.add(yt_id)
                videos.append(v)
                if len(videos) >= 4:
                    break
        if len(videos) >= 4:
            break
        
    result = {
        "key_concepts": key_concepts,
        "queries": queries,
        "videos": videos[:4],
        "youtube_api_key_missing": not youtube.is_configured()
    }
    storage.save_goal_recommendations(id, result, username=username)
    return result


@router.post("/goals/{id}/recommendations/replace_one")
async def replace_one_goal_recommendation(
    id: int,
    dismissed_yt_id: str = Form(...),
    username: str = Depends(require_app_access)
):
    """Dismisses 1 recommendation and returns 1 replacement video not previously excluded."""
    storage.add_dismissed_recommendation(dismissed_yt_id, username=username)

    conn = database.get_db_connection(username)
    user_uuid = conn.user_uuid
    cursor = conn.cursor()
    cursor.execute("SELECT title, description FROM goals WHERE id = %s AND user_uuid = %s;", (id, user_uuid))
    row = cursor.fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="Goal not found")

    try:
        recs = await asyncio.to_thread(ai.generate_goal_recommendations, row["title"], row["description"], username)
    except Exception as e:
        recs = {"search_queries": [f"{row['title']} tutorial"]}

    queries = recs.get("search_queries", [])
    excluded_yt_ids = storage.get_excluded_youtube_ids(username=username)

    replacement = None
    for q in queries:
        v_list = await asyncio.to_thread(youtube.search_youtube_recommendations, q, 6)
        for v in v_list:
            yt_id = v.get("youtube_id")
            if yt_id and yt_id not in excluded_yt_ids and youtube.is_valid_duration(v.get("duration")):
                replacement = v
                break
        if replacement:
            break

    # Update DB cache if present
    saved = storage.get_saved_goal_recommendations(id, username=username)
    if saved and saved.get("videos"):
        new_vids = [v for v in saved["videos"] if v.get("youtube_id") != dismissed_yt_id]
        if replacement:
            new_vids.append(replacement)
        saved["videos"] = new_vids[:4]
        storage.save_goal_recommendations(id, saved, username=username)

    return {"status": "success", "replacement": replacement}


@router.post("/goals/{id}/recommendations/reload_all")
async def reload_all_goal_recommendations(
    id: int,
    username: str = Depends(require_app_access)
):
    """Forces fresh 4 video recommendations for a goal excluding all dismissed videos."""
    conn = database.get_db_connection(username)
    user_uuid = conn.user_uuid
    cursor = conn.cursor()
    cursor.execute("SELECT title, description FROM goals WHERE id = %s AND user_uuid = %s;", (id, user_uuid))
    row = cursor.fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="Goal not found")

    try:
        recs = await asyncio.to_thread(ai.generate_goal_recommendations, row["title"], row["description"], username)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AI recommendations generation failed: {e}")

    queries = recs.get("search_queries", [])
    key_concepts = recs.get("key_concepts", [])
    excluded_yt_ids = storage.get_excluded_youtube_ids(username=username)

    videos = []
    seen_ids = set()
    for q in queries:
        v_list = await asyncio.to_thread(youtube.search_youtube_recommendations, q, 5)
        for v in v_list:
            yt_id = v.get("youtube_id")
            if yt_id and yt_id not in excluded_yt_ids and yt_id not in seen_ids and youtube.is_valid_duration(v.get("duration")):
                seen_ids.add(yt_id)
                videos.append(v)
                if len(videos) >= 4:
                    break
        if len(videos) >= 4:
            break

    result = {
        "status": "success",
        "key_concepts": key_concepts,
        "videos": videos[:4],
        "youtube_api_key_missing": not youtube.is_configured()
    }
    storage.save_goal_recommendations(id, result, username=username)
    return result




@router.get("/daily-recommendations")
async def get_daily_recommendations(username: str = Depends(require_app_access)):
    """Retrieves or generates daily video recommendations for active user, cached in local DB."""
    today_str = datetime.now().strftime("%Y-%m-%d")
    conn = database.get_db_connection(username)
    user_uuid = conn.user_uuid
    cursor = conn.cursor()

    cursor.execute("""
        SELECT dr.id, dr.youtube_id, dr.title, dr.thumbnail_url AS thumbnail, dr.url, dr.goal_id, dr.goal_title, dr.summary, dr.duration, dr.views, dr.channel,
               v.id AS video_id, v.is_temporary, v.last_position_seconds, v.duration_seconds
        FROM daily_recommendations dr
        LEFT JOIN videos v ON v.youtube_id = dr.youtube_id AND v.user_uuid = dr.user_uuid
        WHERE dr.user_uuid = %s AND dr.created_date = %s;
    """, (user_uuid, today_str))
    cached = [dict(r) for r in cursor.fetchall()]
    excluded_yt_ids = storage.get_excluded_youtube_ids(username=username)

    if cached:
        conn.close()
        filtered = [r for r in cached if r.get("youtube_id") not in excluded_yt_ids]
        return {
            "recommendations": filtered,
            "date": datetime.now().strftime("%B %d, %Y"),
            "youtube_api_key_missing": not youtube.is_configured()
        }

    cursor.execute("SELECT id, title, description FROM goals WHERE user_uuid = %s AND is_archived = 0 ORDER BY order_index ASC;", (user_uuid,))
    goals = [dict(r) for r in cursor.fetchall()]

    if not goals:
        conn.close()
        return {"recommendations": [], "date": datetime.now().strftime("%B %d, %Y")}

    try:
        recs = ai.generate_daily_recommendations(goals, username=username)
        for r in recs:
            cursor.execute("""
                INSERT INTO daily_recommendations
                (user_uuid, youtube_id, title, thumbnail_url, url, goal_id, goal_title, summary, duration, views, channel, created_date)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s);
            """, (
                user_uuid,
                r.get("youtube_id", "dQw4w9WgXcQ"),
                r.get("title", ""),
                r.get("thumbnail", ""),
                r.get("url", ""),
                r.get("goal_id"),
                r.get("goal_title", ""),
                json.dumps(r.get("summary", [])),
                r.get("duration", "N/A"),
                r.get("views", "N/A"),
                r.get("channel", ""),
                today_str
            ))
        conn.commit()
    except Exception as e:
        logger.warning(f"Failed to save daily recommendations: {e}")
        recs = []

    cursor.execute("""
        SELECT dr.id, dr.youtube_id, dr.title, dr.thumbnail_url AS thumbnail, dr.url, dr.goal_id, dr.goal_title, dr.summary, dr.duration, dr.views, dr.channel,
               v.id AS video_id, v.is_temporary, v.last_position_seconds, v.duration_seconds
        FROM daily_recommendations dr
        LEFT JOIN videos v ON v.youtube_id = dr.youtube_id AND v.user_uuid = dr.user_uuid
        WHERE dr.user_uuid = %s AND dr.created_date = %s;
    """, (user_uuid, today_str))
    saved_recs = [dict(r) for r in cursor.fetchall()]
    conn.close()

    final_recs = saved_recs if saved_recs else recs
    filtered_recs = [r for r in final_recs if r.get("youtube_id") not in excluded_yt_ids]

    return {
        "recommendations": filtered_recs,
        "date": datetime.now().strftime("%B %d, %Y"),
        "youtube_api_key_missing": not youtube.is_configured()
    }


@router.post("/daily-recommendations/dismiss")
async def dismiss_daily_recommendation(
    youtube_id: str = Form(...),
    username: str = Depends(require_app_access)
):
    """Dismisses a recommended video so it won't show again today."""
    storage.add_dismissed_recommendation(youtube_id, username=username)
    return {"status": "success"}


@router.post("/daily-recommendations/refresh")
async def refresh_daily_recommendations(username: str = Depends(require_app_access)):
    """Refreshes daily recommendations by generating new queries and saving to DB."""
    storage.clear_daily_recommendation_cache(username=username)
    conn = database.get_db_connection(username)
    user_uuid = conn.user_uuid
    cursor = conn.cursor()
    cursor.execute("SELECT id, title, description FROM goals WHERE user_uuid = %s AND is_archived = 0 ORDER BY order_index ASC;", (user_uuid,))
    goals = [dict(r) for r in cursor.fetchall()]

    recs = ai.generate_daily_recommendations(goals, force_refresh=True, username=username)
    today_str = datetime.now().strftime("%Y-%m-%d")

    try:
        for r in recs:
            cursor.execute("""
                INSERT INTO daily_recommendations 
                (user_uuid, youtube_id, title, thumbnail_url, url, goal_id, goal_title, summary, duration, views, created_date)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s);
            """, (
                user_uuid,
                r.get("youtube_id", "dQw4w9WgXcQ"),
                r.get("title", ""),
                r.get("thumbnail", ""),
                r.get("url", ""),
                r.get("goal_id"),
                r.get("goal_title", ""),
                json.dumps(r.get("summary", [])),
                r.get("duration", "N/A"),
                r.get("views", "N/A"),
                today_str
            ))
        conn.commit()
    except Exception as e:
        logger.warning(f"Failed to save refreshed daily recommendations: {e}")
    finally:
        conn.close()

    return {
        "recommendations": recs,
        "date": datetime.now().strftime("%B %d, %Y"),
        "youtube_api_key_missing": not youtube.is_configured()
    }


@router.post("/goals/{id}/practice")
async def generate_goal_practice_quiz(
    id: int,
    question_count: int = Form(5),
    username: str = Depends(require_app_access)
):
    """Generates an active recall quiz from transcripts of all videos associated with a goal."""
    conn = database.get_db_connection(username)
    user_uuid = conn.user_uuid
    cursor = conn.cursor()
    cursor.execute("SELECT title, description FROM goals WHERE id = %s AND user_uuid = %s;", (id, user_uuid))
    goal_row = cursor.fetchone()
    if not goal_row:
        conn.close()
        raise HTTPException(status_code=404, detail="Goal not found")

    cursor.execute("SELECT id, youtube_id, title FROM videos WHERE learning_goal_id = %s AND user_uuid = %s AND is_archived = 0 AND status = 'ready';", (id, user_uuid))
    videos = cursor.fetchall()
    
    transcripts = []
    for v in videos:
        v_data = database.get_video_row(v["id"], username=username)
        if v_data and v_data.get("summary"):
            transcripts.append(f"--- Video: {v['title']} ---\n" + "\n".join(v_data.get("summary", [])))

    combined_text = "\n\n".join(transcripts) if transcripts else goal_row["description"]
    if not combined_text:
        conn.close()
        raise HTTPException(status_code=400, detail="No video summaries or description available for this goal.")


    user_config = config.load_user_config(username)
    intervals = get_srs_intervals(cursor, user_uuid=user_uuid)
    multipliers = get_srs_multipliers(username)
    multiplier = multipliers.get(3, 1.5)
    review_delay_days = intervals[0] * multiplier
    pref_hour = get_preferred_hour(cursor, user_uuid)
    next_review_dt = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=review_delay_days)
    next_review = adjust_next_review(next_review_dt, pref_hour).isoformat()

    cursor.execute(
        """INSERT INTO quizzes (user_uuid, goal_id, quiz_type, srs_stage, next_review_at, notified, importance_level)
           VALUES (%s, %s, 'goal', 0, %s, 0, 3) RETURNING id;""",
        (user_uuid, id, next_review)
    )
    res = cursor.fetchone()
    quiz_id = res["id"] if isinstance(res, dict) and "id" in res else (res[0] if res else cursor.lastrowid)

    try:
        ai_quiz_data = ai.generate_topic_quiz(
            topic=goal_row["title"],
            description=combined_text[:6000],
            question_count=question_count,
            username=username
        )
    except Exception as e:
        ai_quiz_data = {"quiz": [], "stages": {}}

    conn.commit()
    conn.close()


    # The INSERT above does not carry questions_json, so this is the write that fills it.
    database.save_quiz_active_questions(quiz_id, ai_quiz_data.get("quiz", []), username=username)
    database.save_quiz_concept_pool(quiz_id, build_concept_pool(ai_quiz_data), username=username)

    return {"status": "success", "quiz_id": quiz_id}
