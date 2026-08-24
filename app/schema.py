"""
The application's Postgres schema, as a list of statements safe to re-run.

This is the single source of truth for tables/columns/indexes: both
scripts/init_supabase_schema.py (for pointing a fresh Supabase project at
this schema, e.g. a new staging project) and the app's own startup
(app.main.lifespan) call ensure_schema_up_to_date() against it.

Every statement here MUST be purely additive and idempotent: CREATE TABLE
IF NOT EXISTS, ADD COLUMN IF NOT EXISTS, CREATE INDEX IF NOT EXISTS. Never
DROP or destructively ALTER a column here. Anything that could touch
existing data needs a deliberate one-off migration, not an unattended
statement that runs on every server restart.
"""
import logging

logger = logging.getLogger("studiamo")

TABLES_SQL = [
    """
    CREATE TABLE IF NOT EXISTS user_profile (
        id SERIAL PRIMARY KEY,
        user_uuid UUID UNIQUE NOT NULL,
        username TEXT NOT NULL,
        display_name TEXT,
        xp INTEGER DEFAULT 0,
        level INTEGER DEFAULT 1,
        streak INTEGER DEFAULT 0,
        last_quiz_at TIMESTAMPTZ,
        badges TEXT DEFAULT '[]',
        review_mode TEXT DEFAULT 'video',
        theme TEXT DEFAULT 'cream',
        has_seen_onboarding INTEGER DEFAULT 0,
        has_seen_updates INTEGER DEFAULT 0,
        storage_used_bytes BIGINT DEFAULT 0,
        google_id TEXT,
        google_email TEXT,
        email TEXT,
        password_hash TEXT,
        gemini_api_key TEXT,
        telegram_bot_token TEXT,
        telegram_chat_id TEXT,
        base_url TEXT,
        youtube_api_key TEXT,
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );
    """,
    """
    ALTER TABLE user_profile ADD COLUMN IF NOT EXISTS display_name TEXT;
    ALTER TABLE user_profile ADD COLUMN IF NOT EXISTS review_mode TEXT DEFAULT 'video';
    ALTER TABLE user_profile ADD COLUMN IF NOT EXISTS theme TEXT DEFAULT 'cream';
    ALTER TABLE user_profile ADD COLUMN IF NOT EXISTS google_id TEXT;
    ALTER TABLE user_profile ADD COLUMN IF NOT EXISTS google_email TEXT;
    ALTER TABLE user_profile ADD COLUMN IF NOT EXISTS email TEXT;
    ALTER TABLE user_profile ADD COLUMN IF NOT EXISTS password_hash TEXT;
    ALTER TABLE user_profile ADD COLUMN IF NOT EXISTS gemini_api_key TEXT;
    ALTER TABLE user_profile ADD COLUMN IF NOT EXISTS telegram_bot_token TEXT;
    ALTER TABLE user_profile ADD COLUMN IF NOT EXISTS telegram_chat_id TEXT;
    ALTER TABLE user_profile ADD COLUMN IF NOT EXISTS base_url TEXT;
    ALTER TABLE user_profile ADD COLUMN IF NOT EXISTS youtube_api_key TEXT;
    ALTER TABLE user_profile ADD COLUMN IF NOT EXISTS preferred_hour INTEGER DEFAULT -1;
    ALTER TABLE user_profile ADD COLUMN IF NOT EXISTS notification_channel TEXT DEFAULT 'both';
    ALTER TABLE user_profile ADD COLUMN IF NOT EXISTS notifications_enabled INTEGER DEFAULT 1;
    ALTER TABLE user_profile ADD COLUMN IF NOT EXISTS leaderboard_hidden INTEGER DEFAULT 0;
    ALTER TABLE user_profile ADD COLUMN IF NOT EXISTS voice_engine TEXT DEFAULT 'browser';
    ALTER TABLE user_profile ADD COLUMN IF NOT EXISTS voice_speed REAL DEFAULT 1.0;

    -- Per-channel notification toggles, read by routers/settings.py.
    -- The defaults are asymmetric and that is deliberate, not an oversight: a channel is
    -- OFF until the user connects it (nothing can be delivered to an unconfigured Telegram
    -- chat or an unsubscribed browser), while the category filters are ON so that a user
    -- who does connect a channel receives everything rather than silence. Copied from the
    -- live database; inverting either group would quietly change behaviour for every new
    -- account.
    ALTER TABLE user_profile ADD COLUMN IF NOT EXISTS notify_telegram BOOLEAN DEFAULT FALSE;
    ALTER TABLE user_profile ADD COLUMN IF NOT EXISTS notify_push BOOLEAN DEFAULT FALSE;
    ALTER TABLE user_profile ADD COLUMN IF NOT EXISTS notify_email BOOLEAN DEFAULT FALSE;
    ALTER TABLE user_profile ADD COLUMN IF NOT EXISTS notify_cat_quizzes BOOLEAN DEFAULT TRUE;
    ALTER TABLE user_profile ADD COLUMN IF NOT EXISTS notify_cat_streak BOOLEAN DEFAULT TRUE;
    ALTER TABLE user_profile ADD COLUMN IF NOT EXISTS notify_cat_inactivity BOOLEAN DEFAULT TRUE;
    ALTER TABLE user_profile ADD COLUMN IF NOT EXISTS last_inactivity_notified_at TIMESTAMPTZ;

    -- Referral system (see routers/auth.py's signup path and database.py's code generation).
    ALTER TABLE user_profile ADD COLUMN IF NOT EXISTS referral_code VARCHAR;
    ALTER TABLE user_profile ADD COLUMN IF NOT EXISTS referral_count INTEGER NOT NULL DEFAULT 0;
    ALTER TABLE user_profile ADD COLUMN IF NOT EXISTS referred_by UUID REFERENCES user_profile(user_uuid);

    -- Referral codes are looked up directly (database.find_user_by_referral_code) and must
    -- not collide. Expressed as a DO block because ALTER TABLE ... ADD CONSTRAINT has no
    -- IF NOT EXISTS form, and this file must stay safe to re-run on every startup. A plain
    -- CREATE UNIQUE INDEX would enforce the same thing but leaves a rebuilt database
    -- holding an index where production holds a constraint, so the two would not compare
    -- equal.
    DO $$
    BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM pg_constraint
             WHERE conname = 'user_profile_referral_code_key'
               AND conrelid = 'user_profile'::regclass
        ) THEN
            ALTER TABLE user_profile
                ADD CONSTRAINT user_profile_referral_code_key UNIQUE (referral_code);
        END IF;
    END $$;

    -- Account waitlist gate. 'waitlist' accounts never receive a session cookie at all
    -- (see google_callback in routers/auth.py), so this is the gate that decides whether a
    -- new signup can log in when the app is at capacity. Distinct from subscription_status,
    -- which decides whether a logged-in account has paid.
    ALTER TABLE user_profile ADD COLUMN IF NOT EXISTS status VARCHAR NOT NULL DEFAULT 'active';
    ALTER TABLE user_profile DROP CONSTRAINT IF EXISTS user_profile_status_check;
    ALTER TABLE user_profile ADD CONSTRAINT user_profile_status_check
        CHECK (status IN ('active', 'waitlist'));

    -- Subscription / billing (Lemon Squeezy).
    -- subscription_status holds the RAW Lemon Squeezy status string, not a home-made one:
    -- 'active', 'on_trial', 'past_due', 'paused', 'unpaid', 'cancelled', 'expired', and
    -- 'inactive' for accounts that never subscribed. Mapping status -> access lives in
    -- database.has_app_access(); note 'cancelled' means "will not renew" in Lemon Squeezy
    -- and still grants access until ls_ends_at.
    -- NOT NULL matters here beyond tidiness: the CHECK below is `subscription_status IN
    -- (...)`, and a NULL would satisfy it, because NULL IN (...) evaluates to NULL rather
    -- than FALSE. A nullable column would therefore let an unconstrained value through the
    -- very constraint meant to catch it.
    ALTER TABLE user_profile ADD COLUMN IF NOT EXISTS subscription_status TEXT NOT NULL DEFAULT 'inactive';
    ALTER TABLE user_profile ADD COLUMN IF NOT EXISTS is_tester BOOLEAN NOT NULL DEFAULT FALSE;
    -- Per-account override for the AI monthly spend ceiling enforced in app.ai. NULL means
    -- "use the standard/tester default from app_settings"; set this to grant one account a
    -- custom ceiling without changing the default for everyone else.
    ALTER TABLE user_profile ADD COLUMN IF NOT EXISTS monthly_budget_usd NUMERIC(10, 2);
    ALTER TABLE user_profile ADD COLUMN IF NOT EXISTS ls_customer_id TEXT;
    ALTER TABLE user_profile ADD COLUMN IF NOT EXISTS ls_subscription_id TEXT;
    ALTER TABLE user_profile ADD COLUMN IF NOT EXISTS ls_variant_id TEXT;
    ALTER TABLE user_profile ADD COLUMN IF NOT EXISTS ls_renews_at TIMESTAMPTZ;
    ALTER TABLE user_profile ADD COLUMN IF NOT EXISTS ls_ends_at TIMESTAMPTZ;
    ALTER TABLE user_profile ADD COLUMN IF NOT EXISTS ls_customer_portal_url TEXT;

    -- Constrain subscription_status to the values Lemon Squeezy actually reports.
    -- An earlier version of this constraint allowed only ('inactive','active'), which
    -- rejected every other LS status on write and would have silently dropped
    -- cancellations and failed payments. DROP first so this block stays re-runnable.
    ALTER TABLE user_profile DROP CONSTRAINT IF EXISTS user_profile_subscription_status_check;
    ALTER TABLE user_profile ADD CONSTRAINT user_profile_subscription_status_check
        CHECK (subscription_status IN (
            'inactive', 'on_trial', 'active', 'paused',
            'past_due', 'unpaid', 'cancelled', 'expired'
        ));
    """,

    """
    CREATE TABLE IF NOT EXISTS goals (
        id SERIAL PRIMARY KEY,
        user_uuid TEXT NOT NULL,
        title TEXT NOT NULL,
        description TEXT,
        order_index INTEGER DEFAULT 0,
        is_archived INTEGER DEFAULT 0,
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS videos (
        id SERIAL PRIMARY KEY,
        user_uuid TEXT NOT NULL,
        youtube_id TEXT,
        title TEXT NOT NULL,
        category TEXT NOT NULL,
        thumbnail_url TEXT,
        importance_rating INTEGER DEFAULT 3,
        learning_goal_id INTEGER REFERENCES goals(id) ON DELETE SET NULL,
        is_archived INTEGER DEFAULT 0,
        is_paused INTEGER DEFAULT 0,
        is_watchlist INTEGER DEFAULT 0,
        custom_notes TEXT,
        status TEXT DEFAULT 'ready',
        status_error TEXT,
        goal_order_index INTEGER DEFAULT 0,
        is_temporary INTEGER DEFAULT 0,
        expires_at TEXT,
        last_position_seconds REAL DEFAULT 0,
        duration_seconds INTEGER DEFAULT 0,
        summary JSONB DEFAULT '[]'::jsonb,
        outline JSONB DEFAULT '[]'::jsonb,
        fact_check JSONB DEFAULT '{}'::jsonb,
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );
    """,
    """
    ALTER TABLE videos ADD COLUMN IF NOT EXISTS summary JSONB DEFAULT '[]'::jsonb;
    ALTER TABLE videos ADD COLUMN IF NOT EXISTS outline JSONB DEFAULT '[]'::jsonb;
    ALTER TABLE videos ADD COLUMN IF NOT EXISTS fact_check JSONB DEFAULT '{}'::jsonb;
    ALTER TABLE videos DROP COLUMN IF EXISTS transcript;
    """,
    """
    CREATE TABLE IF NOT EXISTS quizzes (
        id SERIAL PRIMARY KEY,
        user_uuid TEXT NOT NULL,
        video_id INTEGER REFERENCES videos(id) ON DELETE CASCADE,
        goal_id INTEGER REFERENCES goals(id) ON DELETE CASCADE,
        quiz_type TEXT DEFAULT 'video',
        srs_stage INTEGER DEFAULT 0,
        next_review_at TIMESTAMPTZ NOT NULL,
        notified INTEGER DEFAULT 0,
        importance_level INTEGER DEFAULT 3,
        in_progress_index INTEGER DEFAULT NULL,
        questions_json JSONB DEFAULT '[]'::jsonb,
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );
    """,
    """
    ALTER TABLE quizzes ADD COLUMN IF NOT EXISTS questions_json JSONB DEFAULT '[]'::jsonb;
    ALTER TABLE quizzes DROP COLUMN IF EXISTS json_path;
    ALTER TABLE quizzes DROP COLUMN IF EXISTS user_id;

    -- Every question the AI extracted, across all SRS stages, as a flat array of items
    -- carrying their own `stage`. questions_json holds only the questions active for the
    -- current stage; this holds the pool they are drawn from.
    --
    -- Before this column existed, ai.analyze_youtube_video generated all five stage sets on
    -- every import (see its prompt) and storage.save_quiz_json persisted only the stage-0
    -- ones, so four fifths of the generated questions were paid for and discarded, and every
    -- SRS stage re-served the same stage-0 questions.
    ALTER TABLE quizzes ADD COLUMN IF NOT EXISTS concept_pool JSONB DEFAULT '[]'::jsonb;

    -- Per-stage topic selection made by the user in the Focus overlay, shaped
    -- {"stage_0": ["topic a", "topic b"], ...}. Empty means "use what the AI recommended",
    -- which is what every pre-existing quiz row reads as.
    ALTER TABLE quizzes ADD COLUMN IF NOT EXISTS focus_topics JSONB DEFAULT '{}'::jsonb;
    """,
    """
    CREATE TABLE IF NOT EXISTS ai_usage_logs (
        id SERIAL PRIMARY KEY,
        user_uuid TEXT NOT NULL,
        timestamp TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        model TEXT NOT NULL,
        prompt_tokens INTEGER DEFAULT 0,
        completion_tokens INTEGER DEFAULT 0,
        action_type TEXT NOT NULL,
        cached_tokens INTEGER DEFAULT 0,
        duration_ms INTEGER,
        video_id INTEGER,
        quiz_id INTEGER,
        status TEXT DEFAULT 'success',
        error_kind TEXT,
        attempts INTEGER DEFAULT 1
    );

    ALTER TABLE ai_usage_logs ADD COLUMN IF NOT EXISTS cached_tokens INTEGER DEFAULT 0;
    ALTER TABLE ai_usage_logs ADD COLUMN IF NOT EXISTS duration_ms INTEGER;
    ALTER TABLE ai_usage_logs ADD COLUMN IF NOT EXISTS video_id INTEGER;
    ALTER TABLE ai_usage_logs ADD COLUMN IF NOT EXISTS quiz_id INTEGER;
    ALTER TABLE ai_usage_logs ADD COLUMN IF NOT EXISTS status TEXT DEFAULT 'success';
    ALTER TABLE ai_usage_logs ADD COLUMN IF NOT EXISTS error_kind TEXT;
    ALTER TABLE ai_usage_logs ADD COLUMN IF NOT EXISTS attempts INTEGER DEFAULT 1;
    """,
    """
    CREATE TABLE IF NOT EXISTS srs_settings (
        id SERIAL PRIMARY KEY,
        user_uuid TEXT UNIQUE NOT NULL,
        stage_1_days INTEGER DEFAULT 1,
        stage_2_days INTEGER DEFAULT 3,
        stage_3_days INTEGER DEFAULT 7,
        stage_4_days INTEGER DEFAULT 14,
        stage_5_days INTEGER DEFAULT 30
    );

    -- Stage-5 repetition, read by routers/settings.py alongside the stage intervals above.
    -- Added as ALTERs rather than table columns so existing databases pick them up too.
    ALTER TABLE srs_settings ADD COLUMN IF NOT EXISTS enable_stage_5_repetition BOOLEAN DEFAULT FALSE;
    ALTER TABLE srs_settings ADD COLUMN IF NOT EXISTS stage_5_repeat_interval INTEGER DEFAULT 30;
    """,
    """
    CREATE TABLE IF NOT EXISTS quiz_attempts (
        id SERIAL PRIMARY KEY,
        user_uuid TEXT NOT NULL,
        quiz_id INTEGER REFERENCES quizzes(id) ON DELETE CASCADE,
        video_id INTEGER REFERENCES videos(id) ON DELETE CASCADE,
        goal_id INTEGER REFERENCES goals(id) ON DELETE CASCADE,
        question_index INTEGER,
        question TEXT,
        given_answer TEXT,
        correct_answer TEXT,
        grade TEXT,
        xp_gained INTEGER,
        explanation TEXT,
        feedback TEXT,
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS daily_recommendations (
        id SERIAL PRIMARY KEY,
        user_uuid TEXT NOT NULL,
        youtube_id TEXT NOT NULL,
        title TEXT NOT NULL,
        thumbnail_url TEXT,
        url TEXT,
        goal_id INTEGER REFERENCES goals(id) ON DELETE CASCADE,
        goal_title TEXT,
        summary TEXT,
        duration TEXT,
        views TEXT,
        channel TEXT,
        created_date TEXT NOT NULL
    );
    """,
    """
    ALTER TABLE daily_recommendations ADD COLUMN IF NOT EXISTS channel TEXT;
    """,
    """
    CREATE TABLE IF NOT EXISTS dismissed_recommendations (
        id SERIAL PRIMARY KEY,
        user_uuid TEXT NOT NULL,
        youtube_id TEXT NOT NULL,
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS goal_recommendations (
        id SERIAL PRIMARY KEY,
        user_uuid TEXT NOT NULL,
        goal_id INTEGER NOT NULL REFERENCES goals(id) ON DELETE CASCADE,
        recommendations_json TEXT NOT NULL,
        updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(user_uuid, goal_id)
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS import_tasks (
        id SERIAL PRIMARY KEY,
        user_uuid TEXT NOT NULL,
        video_id INTEGER REFERENCES videos(id) ON DELETE CASCADE,
        task_type TEXT NOT NULL,
        title TEXT NOT NULL,
        payload_json TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending',
        progress_stage TEXT NOT NULL DEFAULT 'queued',
        error_message TEXT,
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS push_subscriptions (
        id SERIAL PRIMARY KEY,
        user_uuid TEXT NOT NULL,
        endpoint TEXT NOT NULL,
        subscription_json JSONB NOT NULL,
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(user_uuid, endpoint)
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS app_settings (
        key VARCHAR(100) PRIMARY KEY,
        value TEXT NOT NULL
    );
    """,
    """
    -- One-time payloads for the managed Telegram bot's /start deep link. A payload
    -- travels through a URL and is handed to Telegram, so it is stored rather than
    -- derived: single use, short lived, and worthless once redeemed or expired.
    CREATE TABLE IF NOT EXISTS telegram_link_token (
        token VARCHAR(64) PRIMARY KEY,
        username TEXT NOT NULL,
        expires_at TIMESTAMPTZ NOT NULL,
        used_at TIMESTAMPTZ
    );
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_telegram_link_token_expires
        ON telegram_link_token (expires_at);
    """,
    """
    CREATE TABLE IF NOT EXISTS bugs (
        id TEXT PRIMARY KEY,
        username TEXT NOT NULL,
        area TEXT NOT NULL DEFAULT 'General / Other',
        description TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'open',
        is_anonymous BOOLEAN NOT NULL DEFAULT FALSE,
        created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    """,
    """
    -- Ambient triage context (device/browser/referring page/connection), captured at
    -- submission time unless the reporter opts out. Never geolocation/IP-derived data.
    ALTER TABLE bugs ADD COLUMN IF NOT EXISTS context JSONB NOT NULL DEFAULT '{}'::jsonb;
    """,
    """
    CREATE TABLE IF NOT EXISTS import_timings (
        id SERIAL PRIMARY KEY,
        created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        task_type TEXT NOT NULL,
        video_url TEXT,
        duration_seconds INTEGER,
        processing_time_sec REAL NOT NULL
    );
    """,
    """
    -- Public pre-launch landing-page email capture (marketing list, no account
    -- linkage). Not to be confused with user_profile.status = 'waitlist', which
    -- gates real Google-SSO signups once the registered-user cap is reached.
    CREATE TABLE IF NOT EXISTS landing_waitlist (
        id SERIAL PRIMARY KEY,
        uuid TEXT UNIQUE,
        email TEXT UNIQUE NOT NULL,
        preference TEXT DEFAULT 'cloud',
        referrer TEXT,
        country TEXT,
        user_agent TEXT,
        email_sent BOOLEAN NOT NULL DEFAULT FALSE,
        confirmation_sent_at TIMESTAMPTZ,
        spot_ready_sent_at TIMESTAMPTZ,
        reminder_1_sent_at TIMESTAMPTZ,
        reminder_2_sent_at TIMESTAMPTZ,
        emails_sent_count INTEGER DEFAULT 0,
        unsubscribed BOOLEAN NOT NULL DEFAULT FALSE,
        created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    ALTER TABLE landing_waitlist ADD COLUMN IF NOT EXISTS referrer TEXT;
    ALTER TABLE landing_waitlist ADD COLUMN IF NOT EXISTS country TEXT;
    ALTER TABLE landing_waitlist ADD COLUMN IF NOT EXISTS user_agent TEXT;
    ALTER TABLE landing_waitlist ADD COLUMN IF NOT EXISTS confirmation_sent_at TIMESTAMPTZ;
    ALTER TABLE landing_waitlist ADD COLUMN IF NOT EXISTS spot_ready_sent_at TIMESTAMPTZ;
    ALTER TABLE landing_waitlist ADD COLUMN IF NOT EXISTS reminder_1_sent_at TIMESTAMPTZ;
    ALTER TABLE landing_waitlist ADD COLUMN IF NOT EXISTS reminder_2_sent_at TIMESTAMPTZ;
    ALTER TABLE landing_waitlist ADD COLUMN IF NOT EXISTS emails_sent_count INTEGER DEFAULT 0;
    -- Set once the lead's account is off the waitlist and usable. Deliberately not the same
    -- as spot_ready_sent_at, which records that the promotion email was delivered: a send can
    -- fail while the promotion still happened, and anything mailing this list later has to
    -- exclude people who already have a working account rather than people who got an email.
    ALTER TABLE landing_waitlist ADD COLUMN IF NOT EXISTS converted_at TIMESTAMPTZ;
    """,
    """
    -- Time-boxed tester grants. One row per grant, history kept: the *current* grant for a
    -- user is the newest row by granted_at, revoked or not. Reading the newest row
    -- unconditionally, rather than the newest un-revoked one, is what makes a revocation
    -- stick even if an older un-revoked row is still lying around from a manual edit.
    --
    -- user_profile.is_tester still exists and is still read on hot paths (app.ai reads it
    -- for the per-account AI budget), but it is a cache of "there is a valid grant here",
    -- not the source of truth. database.has_app_access() reads this table.
    CREATE TABLE IF NOT EXISTS tester_access (
        id                  SERIAL PRIMARY KEY,
        user_uuid           UUID NOT NULL,
        username            TEXT,
        granted_at          TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        expires_at          TIMESTAMPTZ,
        period_days         INTEGER NOT NULL,
        granted_by          TEXT,
        note                TEXT,
        extended_count      INTEGER NOT NULL DEFAULT 0,
        last_extended_at    TIMESTAMPTZ,
        revoked_at          TIMESTAMPTZ,
        revoked_reason      TEXT,
        welcome_seen_at     TIMESTAMPTZ,
        reminder_7d_seen_at TIMESTAMPTZ,
        reminder_1d_seen_at TIMESTAMPTZ,
        expiry_seen_at      TIMESTAMPTZ,
        created_at          TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
    );

    -- period_days = 0 means "no end date", and is the only case where expires_at is NULL.
    -- Two columns encoding one fact will drift otherwise: three separate code paths write
    -- this row (grant, extend, backfill), so the invariant is enforced here rather than
    -- trusting all three to keep agreeing. DROP first so this block stays re-runnable.
    -- Set when an account that had a tester grant later starts paying. Distinct from
    -- revoked_reason, which records an admin ending a period: converting is something the
    -- customer did, not something done to them, and conflating the two would make it
    -- impossible to tell "I ended this" from "they subscribed".
    ALTER TABLE tester_access ADD COLUMN IF NOT EXISTS converted_at TIMESTAMPTZ;

    ALTER TABLE tester_access DROP CONSTRAINT IF EXISTS tester_access_period_expiry_check;
    ALTER TABLE tester_access ADD CONSTRAINT tester_access_period_expiry_check
        CHECK (
            (period_days = 0 AND expires_at IS NULL) OR
            (period_days > 0 AND expires_at IS NOT NULL)
        );
    """,
    """
    -- What testers said on their way out. The point of a test phase is finding out what is
    -- wrong, and the expiry screen is the one moment someone has both formed an opinion and
    -- has nothing left to lose by saying it.
    --
    -- grant_id records which test period the answer belongs to, so a second grant to the
    -- same person collects a separate answer rather than overwriting the first. Deliberately
    -- nullable: feedback is worth keeping even if the grant row it came from is later gone.
    CREATE TABLE IF NOT EXISTS tester_feedback (
        id          SERIAL PRIMARY KEY,
        user_uuid   UUID NOT NULL,
        username    TEXT,
        grant_id    INTEGER,
        message     TEXT NOT NULL,
        created_at  TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    """,
    """
    -- Durable XP ledger. user_profile.xp is a lifetime total that only ever grows, but the
    -- weekly leaderboard used to derive its numbers from SUM(quiz_attempts.xp_gained), and
    -- attempt rows are deleted outright when their video or goal is deleted (see
    -- routers/videos.py and routers/goals.py). The two disagreed by 91 XP on the largest
    -- production account, and a user who tidied up their library silently dropped down the
    -- weekly board. This table records the XP as it is earned and nothing deletes from it
    -- except account deletion, so both numbers now come from a source that stays put.
    --
    -- No foreign key to quiz_attempts on purpose: outliving the attempt row is the point.
    -- quiz_attempt_id is kept only so the backfill can be re-run without duplicating rows.
    CREATE TABLE IF NOT EXISTS xp_events (
        id              SERIAL PRIMARY KEY,
        user_uuid       UUID NOT NULL,
        xp              INTEGER NOT NULL,
        source          TEXT NOT NULL DEFAULT 'quiz',
        quiz_attempt_id INTEGER,
        created_at      TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    """,
    """
    ALTER TABLE user_profile ENABLE ROW LEVEL SECURITY;
    ALTER TABLE goals ENABLE ROW LEVEL SECURITY;
    ALTER TABLE videos ENABLE ROW LEVEL SECURITY;
    ALTER TABLE quizzes ENABLE ROW LEVEL SECURITY;
    ALTER TABLE ai_usage_logs ENABLE ROW LEVEL SECURITY;
    ALTER TABLE srs_settings ENABLE ROW LEVEL SECURITY;
    ALTER TABLE quiz_attempts ENABLE ROW LEVEL SECURITY;
    ALTER TABLE daily_recommendations ENABLE ROW LEVEL SECURITY;
    ALTER TABLE dismissed_recommendations ENABLE ROW LEVEL SECURITY;
    ALTER TABLE goal_recommendations ENABLE ROW LEVEL SECURITY;
    ALTER TABLE import_tasks ENABLE ROW LEVEL SECURITY;
    ALTER TABLE push_subscriptions ENABLE ROW LEVEL SECURITY;
    ALTER TABLE app_settings ENABLE ROW LEVEL SECURITY;
    ALTER TABLE telegram_link_token ENABLE ROW LEVEL SECURITY;
    ALTER TABLE bugs ENABLE ROW LEVEL SECURITY;
    ALTER TABLE import_timings ENABLE ROW LEVEL SECURITY;
    ALTER TABLE landing_waitlist ENABLE ROW LEVEL SECURITY;
    ALTER TABLE tester_access ENABLE ROW LEVEL SECURITY;
    ALTER TABLE tester_feedback ENABLE ROW LEVEL SECURITY;
    ALTER TABLE xp_events ENABLE ROW LEVEL SECURITY;
    """,
]

INDEXES_SQL = [
    "CREATE INDEX IF NOT EXISTS idx_user_profile_username ON user_profile (LOWER(username));",
    "CREATE INDEX IF NOT EXISTS idx_user_profile_uuid ON user_profile (user_uuid);",
    "CREATE INDEX IF NOT EXISTS idx_goals_user_uuid ON goals(user_uuid);",

    # One goal title per user, compared case- and whitespace-insensitively, so "Affinity",
    # "affinity" and " Affinity " cannot coexist. routers/goals.py checks this first to return
    # a readable message; this index is what makes it true under concurrent requests.
    #
    # Guarded rather than a bare CREATE UNIQUE INDEX because this file runs on every boot and
    # raises on failure: a self-hosted database that already contains duplicate titles would
    # stop starting the moment it pulled this change. Skipping with a warning keeps it
    # bootable, and de-duplicating it is a deliberate migration, not an unattended statement
    # (see this module's docstring).
    """
    DO $$
    BEGIN
        IF EXISTS (
            SELECT 1 FROM goals
             GROUP BY user_uuid, LOWER(TRIM(title))
            HAVING COUNT(*) > 1
        ) THEN
            RAISE WARNING 'Skipping uq_goals_user_title_lower: duplicate goal titles already exist. De-duplicate them, then restart to enforce uniqueness.';
        ELSE
            CREATE UNIQUE INDEX IF NOT EXISTS uq_goals_user_title_lower
                ON goals (user_uuid, LOWER(TRIM(title)));
        END IF;
    END $$;
    """,
    "CREATE INDEX IF NOT EXISTS idx_videos_user_uuid ON videos(user_uuid);",
    "CREATE INDEX IF NOT EXISTS idx_videos_youtube_id ON videos(youtube_id);",
    # POST /api/videos already rejects re-adding a YouTube URL the user has (videos.py,
    # the `SELECT ... WHERE youtube_id = %s AND user_uuid = %s` check before insert),
    # this backs that with a DB-level guarantee so it can't be bypassed by another
    # code path or a restored/replayed row.
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_videos_one_per_youtube_id ON videos(user_uuid, youtube_id) WHERE youtube_id IS NOT NULL;",
    "CREATE INDEX IF NOT EXISTS idx_videos_user_goal ON videos(user_uuid, learning_goal_id);",
    "CREATE INDEX IF NOT EXISTS idx_quizzes_user_uuid ON quizzes(user_uuid);",
    "CREATE INDEX IF NOT EXISTS idx_quizzes_next_review ON quizzes(user_uuid, next_review_at);",
    # One 'video' quiz row per video: generate_video_quiz_for_level relies on this to
    # relabel importance_level in place on a star-rating change instead of creating a
    # duplicate "due now" row. Scoped to quiz_type='video' since goal-type quizzes
    # (video_id IS NULL) aren't part of this invariant.
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_quizzes_one_per_video ON quizzes(user_uuid, video_id) WHERE quiz_type = 'video' AND video_id IS NOT NULL;",
    "CREATE INDEX IF NOT EXISTS idx_push_subscriptions_user ON push_subscriptions(user_uuid);",
    "CREATE INDEX IF NOT EXISTS idx_ai_usage_user_uuid ON ai_usage_logs(user_uuid);",
    "CREATE INDEX IF NOT EXISTS idx_quiz_attempts_user ON quiz_attempts(user_uuid);",

    # The weekly leaderboard sums this table per user over a date range, for every ranked
    # account at once. Composite so that scan is index-only on both columns.
    "CREATE INDEX IF NOT EXISTS idx_xp_events_user_created ON xp_events(user_uuid, created_at);",
    # Makes scripts/backfill_gamification.py safe to re-run: a second pass cannot insert a
    # second event for an attempt it already seeded. Partial because the adjustment rows the
    # backfill writes carry no attempt id and there is one per user.
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_xp_events_quiz_attempt ON xp_events(quiz_attempt_id) WHERE quiz_attempt_id IS NOT NULL;",
    "CREATE INDEX IF NOT EXISTS idx_import_tasks_user ON import_tasks(user_uuid, status);",
    "CREATE INDEX IF NOT EXISTS idx_bugs_created_at ON bugs(created_at DESC);",
    "CREATE INDEX IF NOT EXISTS idx_import_timings_type_duration ON import_timings(task_type, duration_seconds);",
    # Lemon Squeezy webhooks arrive keyed by subscription id, not by user. This index is
    # what makes resolving a webhook back to its user_profile row cheap.
    "CREATE INDEX IF NOT EXISTS idx_user_profile_ls_sub ON user_profile(ls_subscription_id);",

    # Load-bearing, not an optimisation. config.get_user_uuid_from_db() and
    # database.has_app_access() both resolve accounts with
    # `WHERE LOWER(username) = LOWER(%s) LIMIT 1`, and
    # scripts/sync_lemonsqueezy_subscription.py attaches *payments* by username. Without
    # uniqueness, two rows could share a username and every one of those LIMIT 1 lookups
    # would silently pick an arbitrary one, including the one deciding whose account a
    # subscription lands on. idx_user_profile_username above covers the same expression but
    # is non-unique, so it does not provide this guarantee.
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_user_profile_username_lower ON user_profile (LOWER(username));",

    # (referral_code uniqueness is a real UNIQUE constraint, declared in TABLES_SQL.)

    # Plain lookup indexes that exist in production. Redundant alongside the unique index
    # above (Postgres can use that one for referral_code equality too), but declared so a
    # rebuilt database is byte-for-byte comparable to production rather than merely
    # equivalent, and the whole point of this module is that the diff comes back empty.
    "CREATE INDEX IF NOT EXISTS idx_user_profile_referral_code ON user_profile(referral_code);",
    "CREATE INDEX IF NOT EXISTS idx_user_profile_status ON user_profile(status);",
    "CREATE INDEX IF NOT EXISTS idx_dismissed_user_youtube ON dismissed_recommendations(user_uuid, youtube_id);",

    # has_app_access() resolves the current grant with
    # `WHERE user_uuid = ... AND revoked_at IS NULL ORDER BY granted_at DESC LIMIT 1`,
    # on every guarded request. This index is what keeps that a single index scan.
    "CREATE INDEX IF NOT EXISTS idx_tester_access_user ON tester_access(user_uuid, granted_at DESC);",
    # Backs the admin panel's "who is expiring soon" list and the optional sweeper. Partial
    # because a revoked grant is never a candidate for either.
    "CREATE INDEX IF NOT EXISTS idx_tester_access_expires ON tester_access(expires_at) WHERE revoked_at IS NULL;",
    # Feedback is read newest-first, per account when looking at one person and across the
    # table when reading the batch after a cohort ends.
    "CREATE INDEX IF NOT EXISTS idx_tester_feedback_created ON tester_feedback(created_at DESC);",
    "CREATE INDEX IF NOT EXISTS idx_tester_feedback_user ON tester_feedback(user_uuid);",
]


def ensure_schema_up_to_date(conn) -> int:
    """Applies every statement in TABLES_SQL and INDEXES_SQL against `conn`.

    Safe to call on every server start: each statement is IF NOT EXISTS /
    ADD COLUMN IF NOT EXISTS, so applying an already-current schema is a
    no-op read of the Postgres catalog, not a rewrite. Raises on failure:
    a schema that doesn't match what the app expects should be loud, not a
    swallowed exception the app quietly runs on top of.

    Returns the number of statements applied, for logging.
    """
    cursor = conn.cursor()
    for sql in TABLES_SQL:
        cursor.execute(sql)
    for sql in INDEXES_SQL:
        cursor.execute(sql)
    if not getattr(conn, "autocommit", False):
        conn.commit()
    cursor.close()
    return len(TABLES_SQL) + len(INDEXES_SQL)
