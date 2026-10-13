"""
Admin tool: capture one imported YouTube video as a starter set entry.

Run: python scripts/snapshot_starter_set.py <username> <video_id>            # dry run
     python scripts/snapshot_starter_set.py <username> <video_id> --apply    # write it
     add --position N to order the sets (lower first, default 0)

Reads the video's summary, outline and full card pool from the given account (a real import
that finished) and stores them in starter_sets, from where app.starter copies them into every
free-plan account. Only an ordinary YouTube import qualifies. Cards the account's owner wrote or
edited are left out of the snapshot (a starter set is not that person's study notes).

Import the video with NO learning goal first: the import prompt weights the summary and the
questions toward the goal it is given, and a starter set should read the same for everyone.
The script warns when the video has a goal.

Run it once per example video, deliberately. It writes to the database of the checkout it is run
from, so run it from staging, check the result there, then from prod with the maintainer's go-ahead.
"""
import json
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from app import database  # noqa: E402


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if len(args) != 2:
        print(__doc__)
        sys.exit(1)
    username, video_id = args[0], int(args[1])
    apply_it = "--apply" in sys.argv[1:]
    position = 0
    if "--position" in sys.argv:
        position = int(sys.argv[sys.argv.index("--position") + 1])

    conn = database.get_db_connection(username)
    try:
        cursor = conn.cursor()
        cursor.execute(
            """SELECT v.youtube_id, v.title, v.category, v.thumbnail_url, v.duration_seconds, v.summary, v.outline,
                      v.learning_goal_id, v.status, q.concept_pool
                 FROM videos v LEFT JOIN quizzes q ON q.video_id = v.id AND q.user_uuid = v.user_uuid AND q.quiz_type = 'video'
                WHERE v.id = %s AND v.user_uuid = %s;""",
            (video_id, conn.user_uuid),
        )
        row = cursor.fetchone()
        if not row:
            sys.exit(f"No video {video_id} in {username}'s account.")
        if not row["youtube_id"] or str(row["youtube_id"]).startswith("doc_") or row["status"] != "ready":
            sys.exit("Only a finished YouTube import can be a starter set.")
        pool = [dict(c) for c in (row["concept_pool"] or []) if isinstance(c, dict) and c.get("origin") != "human"]
        if not pool:
            sys.exit("The video has no card pool to capture.")
        if row["learning_goal_id"]:
            print("WARNING: this video was imported into a goal, so its summary and questions lean toward it.")

        print(f"{row['title']} ({row['youtube_id']}): {len(pool)} cards, {len(row['summary'] or [])} summary points")
        if not apply_it:
            print("Dry run. Re-run with --apply to store it.")
            return
        cursor.execute(
            """INSERT INTO starter_sets (position, youtube_id, title, category, thumbnail_url, duration_seconds,
                                         summary, outline, concept_pool)
               VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s::jsonb)
               ON CONFLICT (youtube_id) DO UPDATE SET position = EXCLUDED.position, title = EXCLUDED.title,
                   category = EXCLUDED.category, thumbnail_url = EXCLUDED.thumbnail_url,
                   duration_seconds = EXCLUDED.duration_seconds, summary = EXCLUDED.summary,
                   outline = EXCLUDED.outline, concept_pool = EXCLUDED.concept_pool,
                   analyzed_at = CURRENT_TIMESTAMP, active = TRUE;""",
            (position, row["youtube_id"], row["title"], row["category"], row["thumbnail_url"],
             row["duration_seconds"] or 0, json.dumps(row["summary"] or []), json.dumps(row["outline"] or []),
             json.dumps(pool)),
        )
        conn.commit()
        print("Stored. Accounts on the free plan get it on their next visit (once each).")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
