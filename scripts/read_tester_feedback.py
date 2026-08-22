"""
Admin tool: read what testers said on their way out, and how many of them stayed.

Run:
    python scripts/read_tester_feedback.py            # recent feedback plus the headline stats
    python scripts/read_tester_feedback.py --stats    # just the numbers
    python scripts/read_tester_feedback.py --limit 50

A script rather than a page in the admin cockpit on purpose: that cockpit lives in
karl-privat/, which is gitignored and therefore does not exist on the production
deployment. This does, so the feedback can be read where it is actually collected.
"""
import argparse
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from psycopg2.extras import RealDictCursor

from app import database


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--limit", type=int, default=25, help="How many entries to show.")
    parser.add_argument("--stats", action="store_true", help="Show only the conversion numbers.")
    args = parser.parse_args()

    stats = database.get_tester_conversion_stats()
    rate = stats["conversion_rate"]
    print("Tester programme")
    print(f"  grants made     {stats['grants']}")
    print(f"  still running   {stats['still_running']}")
    print(f"  finished        {stats['finished']}")
    print(f"  converted       {stats['converted']}")
    # None rather than 0% when nothing has finished: no completed periods means the
    # question has not been asked yet, which is different from having been answered badly.
    print(f"  conversion      {f'{rate}%' if rate is not None else 'no finished periods yet'}")

    if args.stats:
        return

    conn = database.get_pooled_raw_connection()
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute(
            """SELECT f.username, f.message, f.created_at, t.period_days, t.converted_at
                 FROM tester_feedback f
                 LEFT JOIN tester_access t ON t.id = f.grant_id
                ORDER BY f.created_at DESC
                LIMIT %s;""",
            (args.limit,),
        )
        rows = cursor.fetchall()
    finally:
        database.release_pooled_connection(conn)

    print(f"\nFeedback ({len(rows)} shown)")
    if not rows:
        print("  Nothing yet.")
        return
    for r in rows:
        stayed = "converted" if r["converted_at"] else "did not subscribe"
        period = f"{r['period_days']}d" if r["period_days"] else "unlimited"
        print(f"\n  {r['username']}  ({r['created_at']:%Y-%m-%d}, {period}, {stayed})")
        for line in str(r["message"]).splitlines():
            print(f"    {line}")


if __name__ == "__main__":
    main()
