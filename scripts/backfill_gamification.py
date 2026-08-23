"""
Admin tool: seed the xp_events ledger and repair streaks broken by the old 24 hour reset.

Run: python scripts/backfill_gamification.py           # dry run, shows what would change
     python scripts/backfill_gamification.py --apply   # actually write

One-off catch-up to run once, right after deploying the code that introduced app/gamification.py
and the xp_events table. From then on both are maintained as it happens by routers/quizzes.py.

Two phases, both inside a single transaction so a failure leaves nothing half-applied:

1. xp_events. The weekly leaderboard now sums this table instead of quiz_attempts. Without a
   seed every account's weekly XP would read 0 on the first page load after deploy, so one
   event is written per existing attempt, carrying the attempt's own created_at.

   Attempts are deleted along with their video, so summing them recovers less XP than
   user_profile.xp records: 1206 vs 1115 on the largest production account. That gap is real
   history the ledger cannot reconstruct, and letting the totals disagree from the start would
   defeat the point. Each account whose profile total exceeds its recovered events therefore
   gets one adjustment event for the difference, dated at signup so it lands outside every
   live weekly window. Nobody's lifetime XP or level moves.

2. Streaks. The dashboard used to expire a streak after 24 rolling hours and write the zero
   back on every app boot, which beat the grading path's own rule and left even daily users on
   0. The true streak is recomputed here from the distinct days an account has attempts on.
   That is best-effort by nature: days whose only attempts were deleted with their video
   cannot be recovered. The value written is the run that ended on the account's last active
   day; whether it is still alive is decided at read time by gamification.effective_streak, so
   an account that has genuinely lapsed still displays 0 and restarts at 1 on its next quiz.

   Accounts with attempts but a NULL last_quiz_at (the old dashboard could write XP without
   ever stamping it) also get the column filled from their last attempt, otherwise nothing
   downstream can date their streak at all.
"""
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from psycopg2.extras import RealDictCursor

from app import database


def streak_from_dates(dates) -> int:
    """Returns the run of consecutive days ending on the last date. Expects ascending unique dates."""
    if not dates:
        return 0
    run = 1
    for previous, current in zip(dates, dates[1:]):
        run = run + 1 if (current - previous).days == 1 else 1
    return run


def seed_xp_events(cursor, apply_it: bool) -> None:
    print("1. xp_events ledger")

    cursor.execute(
        """
        SELECT COUNT(*) AS pending
          FROM quiz_attempts a
          JOIN user_profile p ON p.user_uuid::text = a.user_uuid
         WHERE NOT EXISTS (SELECT 1 FROM xp_events e WHERE e.quiz_attempt_id = a.id);
        """
    )
    pending = cursor.fetchone()["pending"]
    print(f"   {pending} attempt(s) not yet in the ledger.")

    if apply_it and pending:
        cursor.execute(
            """
            INSERT INTO xp_events (user_uuid, xp, source, quiz_attempt_id, created_at)
            SELECT p.user_uuid, COALESCE(a.xp_gained, 0), 'quiz', a.id, a.created_at
              FROM quiz_attempts a
              JOIN user_profile p ON p.user_uuid::text = a.user_uuid
             WHERE NOT EXISTS (SELECT 1 FROM xp_events e WHERE e.quiz_attempt_id = a.id);
            """
        )
        print(f"   inserted {cursor.rowcount} quiz event(s).")

    # Anything the profile total records that surviving attempts no longer account for.
    #
    # The ledger total counts events already stored PLUS the attempts phase 1 seeds, so the
    # figure is the same whether or not those inserts have run yet. Reading only the stored
    # events would make a dry run compare against an empty ledger and report the whole profile
    # total as the adjustment, which is precisely the number someone would be approving.
    cursor.execute(
        """
        SELECT p.user_uuid, p.username, p.xp AS profile_xp, p.created_at,
               COALESCE((SELECT SUM(e.xp) FROM xp_events e
                          WHERE e.user_uuid = p.user_uuid), 0)
             + COALESCE((SELECT SUM(COALESCE(a.xp_gained, 0)) FROM quiz_attempts a
                          WHERE a.user_uuid = p.user_uuid::text
                            AND NOT EXISTS (SELECT 1 FROM xp_events e2
                                             WHERE e2.quiz_attempt_id = a.id)), 0) AS ledger_xp
          FROM user_profile p
         WHERE p.xp > 0
         ORDER BY p.xp DESC;
        """
    )
    rows = cursor.fetchall()
    adjustments = [r for r in rows if r["profile_xp"] > r["ledger_xp"]]

    if not adjustments:
        print("   every account's ledger already matches its profile total.")
    for r in adjustments:
        gap = r["profile_xp"] - r["ledger_xp"]
        print(f"   {r['username']}: profile {r['profile_xp']} vs ledger {r['ledger_xp']}, adjustment +{gap}")
        if apply_it:
            cursor.execute(
                """
                INSERT INTO xp_events (user_uuid, xp, source, quiz_attempt_id, created_at)
                VALUES (%s, %s, 'backfill_adjustment', NULL, %s);
                """,
                (r["user_uuid"], gap, r["created_at"]),
            )

    # Ledger above profile means the profile total is stale, not that the ledger is wrong.
    # The dashboard's self-healing lifts it on the owner's next visit; never lower it here.
    for r in rows:
        if r["ledger_xp"] > r["profile_xp"]:
            print(f"   note: {r['username']} ledger {r['ledger_xp']} exceeds profile {r['profile_xp']}, "
                  "left alone for the dashboard to lift.")


def repair_streaks(cursor, apply_it: bool) -> None:
    print("\n2. streaks")

    cursor.execute(
        """
        SELECT p.user_uuid, p.username, p.streak, p.last_quiz_at,
               (SELECT MAX(a.created_at) FROM quiz_attempts a WHERE a.user_uuid = p.user_uuid::text) AS last_attempt
          FROM user_profile p
         ORDER BY p.username;
        """
    )
    profiles = cursor.fetchall()
    changed = 0

    for p in profiles:
        cursor.execute(
            """
            SELECT DISTINCT (created_at AT TIME ZONE 'UTC')::date AS day
              FROM quiz_attempts
             WHERE user_uuid = %s
             ORDER BY day;
            """,
            (str(p["user_uuid"]),),
        )
        days = [r["day"] for r in cursor.fetchall()]
        true_streak = streak_from_dates(days)

        stamp_last_quiz = p["last_quiz_at"] is None and p["last_attempt"] is not None
        if true_streak == (p["streak"] or 0) and not stamp_last_quiz:
            continue

        changed += 1
        note = f"   {p['username']}: streak {p['streak']} -> {true_streak} ({len(days)} active day(s))"
        if stamp_last_quiz:
            note += f", last_quiz_at stamped {p['last_attempt']:%Y-%m-%d}"
        print(note)

        if apply_it:
            cursor.execute(
                """
                UPDATE user_profile
                   SET streak = %s,
                       last_quiz_at = COALESCE(last_quiz_at, %s)
                 WHERE user_uuid = %s;
                """,
                (true_streak, p["last_attempt"], p["user_uuid"]),
            )

    if not changed:
        print("   every account's stored streak already matches its attempt history.")


def main():
    apply_it = "--apply" in sys.argv[1:]

    conn = database.get_pooled_raw_connection()
    conn.autocommit = False
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        seed_xp_events(cursor, apply_it)
        repair_streaks(cursor, apply_it)

        if apply_it:
            conn.commit()
            print("\nApplied.")
        else:
            conn.rollback()
            print("\nDry run. Re-run with --apply to write these changes.")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.autocommit = True
        database.release_pooled_connection(conn)


if __name__ == "__main__":
    main()
