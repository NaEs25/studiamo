import asyncio
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Form, HTTPException, Depends, Query
from fastapi.responses import JSONResponse

from app import config, database, storage, ai, youtube, local_days, plans
from app.dependencies import (
    get_srs_intervals,
    get_srs_multipliers,
    get_user_timezone,
    require_account_access,
    require_ai_access,
    build_concept_pool,
)

import logging

logger = logging.getLogger("studiamo")

router = APIRouter(prefix="/api", tags=["Goals"])



@router.get("/goals")
def get_goals(include_archived: bool = False, username: str = Depends(require_account_access)):
    """Retrieves all active or archived goals along with their associated videos for active user."""
    conn = database.get_db_connection(username)
    try:
        user_uuid = conn.user_uuid
        cursor = conn.cursor()
    
        archived_clause = "AND g.is_archived = 1" if include_archived else "AND g.is_archived = 0"
        cursor.execute(f"""
            SELECT g.id, g.title, g.description, g.key_concepts, g.order_index, g.created_at, g.is_archived,
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
        cursor.execute("SELECT id, title, youtube_id, category, learning_goal_id FROM videos WHERE user_uuid = %s AND learning_goal_id = ANY(%s) AND is_archived = 0 ORDER BY id DESC;", (user_uuid, goal_ids))
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
    finally:
        conn.close()


MAX_GOAL_CONCEPTS = 8
MAX_CONCEPT_CHARS = 60


def parse_concepts(raw) -> list:
    """Turns the comma separated concepts a user typed (or a stored string) into a clean list.

    Splits on commas and line breaks, collapses whitespace, drops blanks and case-insensitive
    duplicates, caps each concept's length and the number kept. Used on every write, so what is
    stored is always already normalized.
    """
    if isinstance(raw, (list, tuple)):
        parts = [str(p) for p in raw]
    else:
        parts = str(raw or "").replace("\n", ",").split(",")
    seen = set()
    concepts = []
    for part in parts:
        clean = " ".join(part.split())[:MAX_CONCEPT_CHARS].strip()
        if clean and clean.casefold() not in seen:
            seen.add(clean.casefold())
            concepts.append(clean)
        if len(concepts) >= MAX_GOAL_CONCEPTS:
            break
    return concepts


def _save_goal_concepts(cursor, user_uuid: str, goal_id: int, concepts: list) -> None:
    cursor.execute("UPDATE goals SET key_concepts = %s WHERE id = %s AND user_uuid = %s;", (", ".join(concepts), goal_id, user_uuid))


def _store_generated_concepts(goal_id: int, generated, username: str) -> list:
    """Keeps AI-proposed concepts on a goal that has none yet and returns the clean list.

    The UPDATE only fires while the column is empty, so concepts the user typed in the
    meantime are never overwritten by a slower generation.
    """
    concepts = parse_concepts(generated)
    if not concepts:
        return concepts
    conn = database.get_db_connection(username)
    try:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE goals SET key_concepts = %s WHERE id = %s AND user_uuid = %s AND COALESCE(key_concepts, '') = '';",
            (", ".join(concepts), goal_id, conn.user_uuid),
        )
        conn.commit()
    finally:
        conn.close()
    return concepts


def _current_goal_concepts(goal_id: int, username: str) -> list:
    conn = database.get_db_connection(username)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT key_concepts FROM goals WHERE id = %s AND user_uuid = %s;", (goal_id, conn.user_uuid))
        row = cursor.fetchone()
        return parse_concepts(row.get("key_concepts")) if row else []
    finally:
        conn.close()


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
def create_goal(title: str = Form(...), description: str = Form(""), username: str = Depends(require_account_access)) -> JSONResponse:
    """Creates a new learning goal and saves its JSON file."""
    conn = database.get_db_connection(username)
    try:
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
    finally:
        conn.close()


@router.post("/goals/{id}/edit")
def edit_goal(id: int, title: str = Form(...), description: str = Form(""), key_concepts: Optional[str] = Form(None), username: str = Depends(require_account_access)):
    """Edits a learning goal title, description and key concepts, cascading video category renames.

    key_concepts is a comma separated string; omitted leaves the stored concepts untouched, an
    empty string clears them (they are then generated again the next time recommendations load).
    """
    conn = database.get_db_connection(username)
    try:
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
        if key_concepts is not None:
            _save_goal_concepts(cursor, user_uuid, id, parse_concepts(key_concepts))

        conn.commit()
        conn.close()
        return {"status": "success", "title": title}
    finally:
        conn.close()


@router.post("/goals/{id}/reorder")
def reorder_goal(id: int, direction: str = Form(...), username: str = Depends(require_account_access)):
    """Reorders a goal position up or down among active goals."""
    conn = database.get_db_connection(username)
    try:
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
    finally:
        conn.close()


@router.post("/goals/order")
def reorder_goals(ids: str = Form(...), username: str = Depends(require_account_access)):
    """Stores the priority order of the active goals. `ids` is the full list of the account's
    active goal ids in the wanted order, comma separated. Rejected unless it names exactly those
    goals, so a request can neither reorder another account's rows nor drop a goal from the order."""
    try:
        wanted = [int(x) for x in ids.split(",") if x.strip()]
    except ValueError:
        raise HTTPException(status_code=400, detail="ids must be a comma separated list of numbers.")
    if len(set(wanted)) != len(wanted):
        raise HTTPException(status_code=400, detail="ids must not repeat.")
    conn = database.get_db_connection(username)
    try:
        user_uuid = conn.user_uuid
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM goals WHERE user_uuid = %s AND is_archived = 0;", (user_uuid,))
        have = {r["id"] for r in cursor.fetchall()}
        if set(wanted) != have:
            raise HTTPException(status_code=409, detail="The list changed. Reload and try again.")
        for position, goal_id in enumerate(wanted, start=1):
            cursor.execute("UPDATE goals SET order_index = %s WHERE id = %s AND user_uuid = %s;", (position, goal_id, user_uuid))
        conn.commit()
        return {"status": "success"}
    finally:
        conn.close()


@router.post("/goals/{id}/materials/order")
def reorder_goal_materials(id: int, ids: str = Form(...), username: str = Depends(require_account_access)):
    """Stores the order of a goal's materials. `ids` is the full list of the goal's material ids
    in the wanted order, comma separated. Rejected unless it names exactly the materials the
    account has in this goal (active and not in the Study Queue, the ones the goal shows), so a
    request can neither reorder another account's rows nor drop a material from the order."""
    try:
        wanted = [int(x) for x in ids.split(",") if x.strip()]
    except ValueError:
        raise HTTPException(status_code=400, detail="ids must be a comma separated list of numbers.")
    if len(set(wanted)) != len(wanted):
        raise HTTPException(status_code=400, detail="ids must not repeat.")
    conn = database.get_db_connection(username)
    try:
        user_uuid = conn.user_uuid
        cursor = conn.cursor()
        cursor.execute("SELECT 1 FROM goals WHERE id = %s AND user_uuid = %s;", (id, user_uuid))
        if cursor.fetchone() is None:
            raise HTTPException(status_code=404, detail="Goal not found")
        cursor.execute(
            "SELECT id FROM videos WHERE learning_goal_id = %s AND user_uuid = %s AND is_archived = 0 AND is_watchlist = 0;",
            (id, user_uuid),
        )
        have = {r["id"] for r in cursor.fetchall()}
        if set(wanted) != have:
            raise HTTPException(status_code=409, detail="The list changed. Reload and try again.")
        for position, video_id in enumerate(wanted, start=1):
            cursor.execute(
                "UPDATE videos SET goal_order_index = %s WHERE id = %s AND user_uuid = %s AND learning_goal_id = %s;",
                (position, video_id, user_uuid, id),
            )
        conn.commit()
        return {"status": "success"}
    finally:
        conn.close()


MAX_FOLDER_NAME_CHARS = 60
MAX_FOLDERS_PER_GOAL = 50


def _clean_folder_name(name: str) -> str:
    clean = " ".join((name or "").split())[:MAX_FOLDER_NAME_CHARS].strip()
    if not clean:
        raise HTTPException(status_code=400, detail="Give the folder a name.")
    return clean


def _owned_folder(cursor, user_uuid: str, goal_id: int, folder_id: int) -> dict:
    """The folder row, or 404 unless it is this account's and sits inside this goal."""
    cursor.execute(
        "SELECT id, goal_id, name FROM goal_folders WHERE id = %s AND goal_id = %s AND user_uuid = %s;",
        (folder_id, goal_id, user_uuid),
    )
    row = cursor.fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Folder not found")
    return dict(row)


def _assert_folder_name_free(cursor, user_uuid: str, goal_id: int, name: str, exclude_id: int = None) -> None:
    sql = "SELECT 1 FROM goal_folders WHERE user_uuid = %s AND goal_id = %s AND LOWER(name) = LOWER(%s)"
    params = [user_uuid, goal_id, name]
    if exclude_id is not None:
        sql += " AND id <> %s"
        params.append(exclude_id)
    cursor.execute(sql + " LIMIT 1;", tuple(params))
    if cursor.fetchone():
        raise HTTPException(status_code=409, detail=f'This goal already has a folder called "{name}".')


@router.post("/goals/{id}/folders")
def create_goal_folder(id: int, name: str = Form(...), username: str = Depends(require_account_access)):
    """Creates a folder inside a goal. Folders hold materials of that goal, one level deep."""
    clean = _clean_folder_name(name)
    conn = database.get_db_connection(username)
    try:
        user_uuid = conn.user_uuid
        cursor = conn.cursor()
        cursor.execute("SELECT 1 FROM goals WHERE id = %s AND user_uuid = %s;", (id, user_uuid))
        if cursor.fetchone() is None:
            raise HTTPException(status_code=404, detail="Goal not found")
        cursor.execute("SELECT COUNT(*) AS c FROM goal_folders WHERE goal_id = %s AND user_uuid = %s;", (id, user_uuid))
        if (cursor.fetchone() or {}).get("c", 0) >= MAX_FOLDERS_PER_GOAL:
            raise HTTPException(status_code=409, detail=f"A goal can have up to {MAX_FOLDERS_PER_GOAL} folders.")
        _assert_folder_name_free(cursor, user_uuid, id, clean)
        cursor.execute(
            "INSERT INTO goal_folders (user_uuid, goal_id, name) VALUES (%s, %s, %s) RETURNING id;",
            (user_uuid, id, clean),
        )
        folder_id = cursor.fetchone()["id"]
        conn.commit()
        return {"status": "success", "folder_id": folder_id, "name": clean}
    finally:
        conn.close()


@router.post("/goals/{id}/folders/{folder_id}/rename")
def rename_goal_folder(id: int, folder_id: int, name: str = Form(...), username: str = Depends(require_account_access)):
    clean = _clean_folder_name(name)
    conn = database.get_db_connection(username)
    try:
        user_uuid = conn.user_uuid
        cursor = conn.cursor()
        _owned_folder(cursor, user_uuid, id, folder_id)
        _assert_folder_name_free(cursor, user_uuid, id, clean, exclude_id=folder_id)
        cursor.execute("UPDATE goal_folders SET name = %s WHERE id = %s AND user_uuid = %s;", (clean, folder_id, user_uuid))
        conn.commit()
        return {"status": "success", "name": clean}
    finally:
        conn.close()


@router.delete("/goals/{id}/folders/{folder_id}")
def delete_goal_folder(id: int, folder_id: int, username: str = Depends(require_account_access)):
    """Deletes a folder only. Its materials stay in the goal, outside any folder."""
    conn = database.get_db_connection(username)
    try:
        user_uuid = conn.user_uuid
        cursor = conn.cursor()
        _owned_folder(cursor, user_uuid, id, folder_id)
        cursor.execute("UPDATE videos SET folder_id = NULL WHERE folder_id = %s AND user_uuid = %s;", (folder_id, user_uuid))
        cursor.execute("DELETE FROM goal_folders WHERE id = %s AND user_uuid = %s;", (folder_id, user_uuid))
        conn.commit()
        return {"status": "success"}
    finally:
        conn.close()


@router.post("/goals/{id}/materials/{video_id}/folder")
def move_material_to_folder(
    id: int,
    video_id: int,
    folder_id: Optional[int] = Form(None),
    username: str = Depends(require_account_access),
):
    """Moves one of the goal's materials into a folder of the same goal, or out of any folder when
    folder_id is empty. Both the material and the folder must be this account's and in this goal."""
    conn = database.get_db_connection(username)
    try:
        user_uuid = conn.user_uuid
        cursor = conn.cursor()
        cursor.execute(
            "SELECT 1 FROM videos WHERE id = %s AND learning_goal_id = %s AND user_uuid = %s;",
            (video_id, id, user_uuid),
        )
        if cursor.fetchone() is None:
            raise HTTPException(status_code=404, detail="Material not found in this goal")
        if folder_id:
            _owned_folder(cursor, user_uuid, id, folder_id)
        cursor.execute(
            "UPDATE videos SET folder_id = %s WHERE id = %s AND user_uuid = %s;",
            (folder_id or None, video_id, user_uuid),
        )
        conn.commit()
        return {"status": "success"}
    finally:
        conn.close()


@router.delete("/goals/{id}")
def delete_goal(
    id: int,
    delete_materials: bool = Query(False),
    username: str = Depends(require_account_access)
):
    """Deletes a learning goal and optionally deletes associated videos and quizzes."""
    conn = database.get_db_connection(username)
    try:
        user_uuid = conn.user_uuid
        cursor = conn.cursor()

        cursor.execute("SELECT id FROM goals WHERE id = %s AND user_uuid = %s;", (id, user_uuid))
        if not cursor.fetchone():
            conn.close()
            raise HTTPException(status_code=404, detail="Goal not found")

        if delete_materials:
            cursor.execute("SELECT id FROM videos WHERE learning_goal_id = %s AND user_uuid = %s;", (id, user_uuid))
            video_rows = cursor.fetchall()
            for v in video_rows:
                v_id = v["id"]
                cursor.execute("DELETE FROM quiz_attempts WHERE video_id = %s AND user_uuid = %s;", (v_id, user_uuid))
                cursor.execute("DELETE FROM quizzes WHERE video_id = %s AND user_uuid = %s;", (v_id, user_uuid))
                cursor.execute("DELETE FROM videos WHERE id = %s AND user_uuid = %s;", (v_id, user_uuid))
                storage.delete_video_document(v_id, username=username)
        else:
            cursor.execute("UPDATE videos SET learning_goal_id = NULL, folder_id = NULL WHERE learning_goal_id = %s AND user_uuid = %s;", (id, user_uuid))
        
        cursor.execute("DELETE FROM goal_folders WHERE goal_id = %s AND user_uuid = %s;", (id, user_uuid))
        cursor.execute("DELETE FROM goals WHERE id = %s AND user_uuid = %s;", (id, user_uuid))
        conn.commit()
        conn.close()
        return {"status": "success", "message": "Learning goal deleted successfully"}
    finally:
        conn.close()


@router.post("/goals/{id}/archive")
def archive_goal(id: int, username: str = Depends(require_account_access)):
    """Toggles archived status for a learning goal."""
    conn = database.get_db_connection(username)
    try:
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
    finally:
        conn.close()


@router.get("/goals/{id}/recommendations")
async def get_goal_recommendations(id: int, username: str = Depends(require_ai_access)):
    """Generates AI search queries & scraped YouTube video recommendations for a specific goal."""
    saved = storage.get_saved_goal_recommendations(id, username=username)
    if saved and saved.get("videos"):
        # Videos imported or dismissed since the blob was cached are no longer worth offering.
        owned = storage.get_excluded_youtube_ids(username=username)
        saved["videos"] = [v for v in saved["videos"] if v.get("youtube_id") not in owned]
    if saved and saved.get("videos"):
        # The cached blob predates any later edit of the goal's concepts.
        current = _current_goal_concepts(id, username)
        if not current:
            # Recommendations loaded before concepts lived on the goal: adopt the cached ones,
            # so the Edit dialog shows exactly what the drawer shows.
            current = _store_generated_concepts(id, saved.get("key_concepts", []), username)
        saved["key_concepts"] = current or saved.get("key_concepts", [])
        return saved

    conn = database.get_db_connection(username)
    try:
        user_uuid = conn.user_uuid
        cursor = conn.cursor()
        cursor.execute("SELECT title, description, key_concepts FROM goals WHERE id = %s AND user_uuid = %s;", (id, user_uuid))
        row = cursor.fetchone()
        conn.close()
        if not row:
            raise HTTPException(status_code=404, detail="Goal not found")
        
        try:
            recs = await asyncio.to_thread(ai.generate_goal_recommendations, row["title"], row["description"], username, parse_concepts(row.get("key_concepts")))
        except ai.UsageLimitExceeded as e:
            raise ai.usage_http_exception(e)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"AI recommendations generation failed: {e}")

        queries = recs.get("search_queries", [])
        key_concepts = _store_generated_concepts(id, recs.get("key_concepts", []), username) or parse_concepts(recs.get("key_concepts", []))

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
        
        # No "queries" key: nothing reads it. The search strings above are an implementation
        # detail of picking the four videos, and reload_all_goal_recommendations, which writes
        # to the same cached blob, never included them, so the key already vanished the first
        # time a user reloaded a goal's recommendations.
        result = {
            "key_concepts": key_concepts,
            "videos": videos[:4],
            "youtube_api_key_missing": not youtube.is_configured()
        }
        storage.save_goal_recommendations(id, result, username=username)
        return result
    finally:
        conn.close()


@router.post("/goals/{id}/recommendations/replace_one")
async def replace_one_goal_recommendation(
    id: int,
    dismissed_yt_id: str = Form(...),
    username: str = Depends(require_ai_access)
):
    """Dismisses 1 recommendation and returns 1 replacement video not previously excluded."""
    storage.add_dismissed_recommendation(dismissed_yt_id, username=username)

    conn = database.get_db_connection(username)
    try:
        user_uuid = conn.user_uuid
        cursor = conn.cursor()
        cursor.execute("SELECT title, description, key_concepts FROM goals WHERE id = %s AND user_uuid = %s;", (id, user_uuid))
        row = cursor.fetchone()
        conn.close()
        if not row:
            raise HTTPException(status_code=404, detail="Goal not found")

        try:
            recs = await asyncio.to_thread(ai.generate_goal_recommendations, row["title"], row["description"], username, parse_concepts(row.get("key_concepts")))
        except Exception as e:
            logger.warning(f"Goal recommendations failed for goal {id}, using the title as the search query: {e}")
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
    finally:
        conn.close()


@router.post("/goals/{id}/recommendations/reload_all")
async def reload_all_goal_recommendations(
    id: int,
    username: str = Depends(require_ai_access)
):
    """Forces fresh 4 video recommendations for a goal excluding all dismissed videos."""
    conn = database.get_db_connection(username)
    try:
        user_uuid = conn.user_uuid
        cursor = conn.cursor()
        cursor.execute("SELECT title, description, key_concepts FROM goals WHERE id = %s AND user_uuid = %s;", (id, user_uuid))
        row = cursor.fetchone()
        conn.close()
        if not row:
            raise HTTPException(status_code=404, detail="Goal not found")

        try:
            recs = await asyncio.to_thread(ai.generate_goal_recommendations, row["title"], row["description"], username, parse_concepts(row.get("key_concepts")))
        except ai.UsageLimitExceeded as e:
            raise ai.usage_http_exception(e)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"AI recommendations generation failed: {e}")

        queries = recs.get("search_queries", [])
        key_concepts = _store_generated_concepts(id, recs.get("key_concepts", []), username) or parse_concepts(recs.get("key_concepts", []))
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
    finally:
        conn.close()




@router.get("/daily-recommendations")
def get_daily_recommendations(username: str = Depends(require_account_access)):
    """Retrieves or generates daily video recommendations for active user, cached in local DB.

    For an account without a plan this answers 200 with an empty list and requires_plan set
    instead of the 402 the other AI routes give: the Home tab loads it on every visit, and an
    error toast each time would punish the account for opening the app. The Home tab shows its
    plan card from the flag."""
    if config.IS_CLOUD and plans.get_plan(username) == plans.PLAN_FREE:
        return {"recommendations": [], "requires_plan": True, "date": datetime.now().strftime("%B %d, %Y")}
    today_str = datetime.now().strftime("%Y-%m-%d")
    conn = database.get_db_connection(username)
    try:
        user_uuid = conn.user_uuid
        cursor = conn.cursor()

        cursor.execute("""
            SELECT dr.id, dr.youtube_id, dr.title, dr.thumbnail_url AS thumbnail, dr.url, dr.goal_id, dr.goal_title, dr.duration, dr.views, dr.channel,
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
                # No summary column: the recommendations come from
                # youtube.search_youtube_recommendations, whose result shape has no summary
                # key, so this always wrote the literal "[]" and the two SELECTs above always
                # read it back. Nothing on the card renders it either. The column stays in the
                # table, since schema.py can only add.
                cursor.execute("""
                    INSERT INTO daily_recommendations
                    (user_uuid, youtube_id, title, thumbnail_url, url, goal_id, goal_title, duration, views, channel, created_date)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s);
                """, (
                    user_uuid,
                    r.get("youtube_id", "dQw4w9WgXcQ"),
                    r.get("title", ""),
                    r.get("thumbnail", ""),
                    r.get("url", ""),
                    r.get("goal_id"),
                    r.get("goal_title", ""),
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
            SELECT dr.id, dr.youtube_id, dr.title, dr.thumbnail_url AS thumbnail, dr.url, dr.goal_id, dr.goal_title, dr.duration, dr.views, dr.channel,
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
    finally:
        conn.close()


@router.post("/daily-recommendations/dismiss")
def dismiss_daily_recommendation(
    youtube_id: str = Form(...),
    delete_notes: Optional[str] = Form(None),
    username: str = Depends(require_account_access)
):
    """Dismisses a recommended video so it won't show again today.

    Playing or queueing a recommendation leaves a temporary preview of it among the account's
    materials. Dismissing the recommendation removes that preview too, unless it holds notes:
    then nothing is changed and {"status": "confirm"} comes back, and the same request with
    delete_notes=true removes the preview together with its notes. A video the account has
    imported for real (not temporary) is never touched."""
    conn = database.get_db_connection(username)
    try:
        user_uuid = conn.user_uuid
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, custom_notes FROM videos WHERE youtube_id = %s AND user_uuid = %s AND is_temporary = 1;",
            (youtube_id, user_uuid),
        )
        preview = cursor.fetchone()
        removed = False
        if preview:
            has_notes = bool((preview["custom_notes"] or "").strip())
            if has_notes and str(delete_notes).lower() not in ("1", "true", "yes"):
                return {"status": "confirm", "has_notes": True}
            storage.delete_video_document(preview["id"], username=username)
            cursor.execute("DELETE FROM quiz_attempts WHERE video_id = %s AND user_uuid = %s;", (preview["id"], user_uuid))
            cursor.execute("DELETE FROM quizzes WHERE video_id = %s AND user_uuid = %s;", (preview["id"], user_uuid))
            cursor.execute("DELETE FROM videos WHERE id = %s AND user_uuid = %s;", (preview["id"], user_uuid))
            conn.commit()
            removed = True
    finally:
        conn.close()
    storage.add_dismissed_recommendation(youtube_id, username=username)
    return {"status": "success", "preview_removed": removed}


@router.post("/daily-recommendations/refresh")
def refresh_daily_recommendations(username: str = Depends(require_ai_access)):
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
            # Same column list as the INSERT in get_daily_recommendations, which reads back
            # through the same two SELECTs. This one was missing channel, so a refreshed
            # batch persisted with no channel name: the response below returns recs
            # directly and looked right, and the name only disappeared on the next reload.
            cursor.execute("""
                INSERT INTO daily_recommendations
                (user_uuid, youtube_id, title, thumbnail_url, url, goal_id, goal_title, duration, views, channel, created_date)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s);
            """, (
                user_uuid,
                r.get("youtube_id", "dQw4w9WgXcQ"),
                r.get("title", ""),
                r.get("thumbnail", ""),
                r.get("url", ""),
                r.get("goal_id"),
                r.get("goal_title", ""),
                r.get("duration", "N/A"),
                r.get("views", "N/A"),
                r.get("channel", ""),
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
def generate_goal_practice_quiz(
    id: int,
    question_count: int = Form(5),
    username: str = Depends(require_ai_access)
):
    """Generates an active recall quiz from transcripts of all videos associated with a goal."""
    conn = database.get_db_connection(username)
    try:
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


        intervals = get_srs_intervals(cursor, user_uuid=user_uuid)
        multipliers = get_srs_multipliers(username)
        multiplier = multipliers.get(3, 1.5)
        review_delay_days = intervals[0] * multiplier
        next_review = local_days.schedule_review(review_delay_days, get_user_timezone(cursor, user_uuid)).isoformat()

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
            logger.warning(f"Goal practice quiz generation failed for goal {id}: {e}")
            ai_quiz_data = {"quiz": [], "stages": {}}

        conn.commit()
        conn.close()


        # The INSERT above does not carry questions_json, so this is the write that fills it.
        database.save_quiz_active_questions(quiz_id, ai_quiz_data.get("quiz", []), username=username)
        database.save_quiz_concept_pool(quiz_id, build_concept_pool(ai_quiz_data), username=username)

        return {"status": "success", "quiz_id": quiz_id}
    finally:
        conn.close()
