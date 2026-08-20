from google import genai
from google.genai import types
from datetime import datetime, timedelta, timezone
import logging
import os
import random
import re
import struct
import subprocess
import tempfile
import json
import time
from app.config import get_config, IS_CLOUD
from app.database import get_db_connection, get_app_setting
from app import youtube

logger = logging.getLogger("studiamo")

# Videos longer than this are clipped to just the opening portion before being sent
# to Gemini (see analyze_youtube_video) to bound worst-case per-video cost.
MAX_VIDEO_ANALYSIS_SECONDS = 30 * 60


# --- AI usage limits: rate limit + monthly budget enforcement ---
#
# Only enforced in cloud mode: self-hosted deployments use their own GEMINI_API_KEY (see
# config.get_config), so there's no shared Studiamo budget for them to threaten. Cloud mode
# uses one central key, so this exists to bound worst-case spend from a bug or a runaway
# loop, not to police normal usage.
#
# All thresholds are operator-configured via the app_settings table (database.get_app_setting
# / set_app_setting) rather than hardcoded.

class UsageLimitExceeded(Exception):
    """Raised before an AI call when a user has hit the rate limit or monthly budget."""

    def __init__(self, kind: str, message: str):
        self.kind = kind  # "rate_limit" or "budget"
        super().__init__(message)


# USD price per 1M tokens: (input, output). Source: Google's published Gemini API pricing.
# Overridable via app_settings['ai_model_pricing'] (JSON: {"model": [input, output]}).
_FALLBACK_MODEL_PRICING = {
    "gemini-3.5-flash-lite": (0.30, 2.50),
    # Retired from the fallback_models list below, but KEEP this entry: get_monthly_cost_usd
    # prices historical ai_usage_logs rows by model name, so dropping it would re-cost past
    # usage at _FALLBACK_DEFAULT_PRICING and could push a user over their monthly cap for
    # spending they never did.
    "gemini-2.5-flash": (0.30, 2.50),
    "gemini-3.6-flash": (1.50, 7.50),
    "gemini-3.1-flash-tts": (1.00, 20.00),
}
# Conservative fallback for any model name not in the table above (e.g. a new fallback rung
# added later and forgotten here), so cost is never silently undercounted.
_FALLBACK_DEFAULT_PRICING = (1.50, 20.00)

# Deliberately a fail-closed floor (blocking AI spend until an operator configures
# the actual budget in app_settings), not a usable default.
_FALLBACK_MONTHLY_BUDGET_USD = 0.01
_FALLBACK_TESTER_MONTHLY_BUDGET_USD = 0.01
_FALLBACK_WARNING_REMAINING_PCT = 10
_FALLBACK_RATE_LIMIT_WINDOW_MINUTES = 60
_FALLBACK_RATE_LIMIT_MAX_CALLS = 40


def _get_app_setting_float(key: str, default: float) -> float:
    raw = get_app_setting(key, "")
    try:
        return float(raw) if raw else default
    except (TypeError, ValueError):
        return default


def _get_app_setting_int(key: str, default: int) -> int:
    raw = get_app_setting(key, "")
    try:
        return int(raw) if raw else default
    except (TypeError, ValueError):
        return default


def get_model_pricing() -> dict:
    """USD price per 1M tokens per model: {model: (input, output)}.

    Reads app_settings['ai_model_pricing'] (JSON object mapping model name to a [input,
    output] pair) and layers it over the built-in fallback table, so an override can add or
    reprice a model without a deploy while every other model keeps its fallback price."""
    pricing = dict(_FALLBACK_MODEL_PRICING)
    raw = get_app_setting("ai_model_pricing", "")
    if raw:
        try:
            override = json.loads(raw)
            for model, prices in override.items():
                if isinstance(prices, (list, tuple)) and len(prices) == 2:
                    pricing[model] = (float(prices[0]), float(prices[1]))
        except (TypeError, ValueError, json.JSONDecodeError):
            pass
    return pricing


def _row_cost_usd(pricing: dict, model: str, prompt_tokens: int, completion_tokens: int) -> float:
    in_price, out_price = pricing.get(model or "", _FALLBACK_DEFAULT_PRICING)
    return (prompt_tokens * in_price + completion_tokens * out_price) / 1_000_000


def get_monthly_budget_usd(username: str) -> float:
    """Returns this user's monthly ceiling, in USD.

    Resolution order: a per-user override in user_profile.monthly_budget_usd, then the
    tester budget (app_settings['ai_tester_monthly_budget_usd']) if user_profile.is_tester
    is set, otherwise the standard budget (app_settings['ai_monthly_budget_usd']). Falls back
    to the fallback constants above on any lookup failure or unset setting."""
    conn = get_db_connection(username)
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT is_tester, monthly_budget_usd FROM user_profile WHERE user_uuid = %s LIMIT 1;",
            (conn.user_uuid,)
        )
        row = cursor.fetchone()
    finally:
        conn.close()

    override = row.get("monthly_budget_usd") if row else None
    if override is not None:
        return float(override)

    is_tester = bool(row.get("is_tester")) if row else False
    if is_tester:
        return _get_app_setting_float("ai_tester_monthly_budget_usd", _FALLBACK_TESTER_MONTHLY_BUDGET_USD)
    return _get_app_setting_float("ai_monthly_budget_usd", _FALLBACK_MONTHLY_BUDGET_USD)


def get_monthly_cost_usd(username: str) -> float:
    """Sums this calendar month's AI spend for a user in USD, weighted by per-model pricing."""
    month_start = datetime.now(timezone.utc).replace(
        day=1, hour=0, minute=0, second=0, microsecond=0, tzinfo=None
    )
    conn = get_db_connection(username)
    try:
        cursor = conn.cursor()
        cursor.execute(
            """SELECT model, prompt_tokens, completion_tokens FROM ai_usage_logs
               WHERE user_uuid = %s AND timestamp >= %s;""",
            (conn.user_uuid, month_start)
        )
        rows = cursor.fetchall()
    finally:
        conn.close()
    pricing = get_model_pricing()
    return sum(
        _row_cost_usd(pricing, r.get("model"), r.get("prompt_tokens") or 0, r.get("completion_tokens") or 0)
        for r in rows
    )


def get_recent_call_count(username: str, minutes: int = None) -> int:
    if minutes is None:
        minutes = _get_app_setting_int("ai_rate_limit_window_minutes", _FALLBACK_RATE_LIMIT_WINDOW_MINUTES)
    since = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=minutes)
    conn = get_db_connection(username)
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT COUNT(*) AS c FROM ai_usage_logs WHERE user_uuid = %s AND timestamp >= %s;",
            (conn.user_uuid, since)
        )
        row = cursor.fetchone()
    finally:
        conn.close()
    return (row.get("c") if row else 0) or 0


def enforce_usage_limits(username: str) -> None:
    """Raises UsageLimitExceeded before an AI call if the user is over budget or firing calls unusually fast.

    No-op outside cloud mode (self-hosted users own their key and their own cost)."""
    if not IS_CLOUD:
        return

    max_calls = _get_app_setting_int("ai_rate_limit_max_calls", _FALLBACK_RATE_LIMIT_MAX_CALLS)
    if get_recent_call_count(username) >= max_calls:
        raise UsageLimitExceeded(
            "rate_limit",
            "You're making AI requests unusually fast, so new ones are paused briefly to protect your "
            "account. This resets within the hour. If this seems wrong, contact hello@studiamo.cloud."
        )

    budget = get_monthly_budget_usd(username)
    spent = get_monthly_cost_usd(username)
    if spent >= budget:
        raise UsageLimitExceeded(
            "budget",
            "You've reached this month's AI usage allowance. It resets at the start of next month. "
            "If you think this was caused by a bug, please contact hello@studiamo.cloud and we'll look into it."
        )


def get_usage_status(username: str) -> dict:
    """Current-month spend/percent-remaining, used to drive the low-balance UI warning."""
    budget = get_monthly_budget_usd(username)
    spent = get_monthly_cost_usd(username)
    pct_used = min(100.0, (spent / budget) * 100) if budget > 0 else 0.0
    pct_remaining = max(0.0, 100.0 - pct_used)
    warning_pct = _get_app_setting_float("ai_warning_remaining_pct", _FALLBACK_WARNING_REMAINING_PCT)
    return {
        "spent_usd": round(spent, 4),
        "budget_usd": budget,
        "percent_used": round(pct_used, 1),
        "percent_remaining": round(pct_remaining, 1),
        "show_warning": pct_remaining <= warning_pct,
    }

def get_gemini_client(username: str = "default_user") -> genai.Client:
    """Returns a GenAI client using the configured API key for a specific user."""
    api_key = get_config("GEMINI_API_KEY", username=username)
    if not api_key:
        raise ValueError("Gemini API key is not configured. Please set GEMINI_API_KEY in settings.")
    return genai.Client(api_key=api_key)

def log_ai_usage(model: str, prompt_tokens: int, completion_tokens: int, action_type: str, username: str = "default_user"):
    """Saves API token usage into Supabase PostgreSQL."""
    try:
        conn = get_db_connection(username)
        user_uuid = conn.user_uuid
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO ai_usage_logs (user_uuid, model, prompt_tokens, completion_tokens, action_type) VALUES (%s, %s, %s, %s, %s);",
            (user_uuid, model, prompt_tokens, completion_tokens, action_type)
        )
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Error logging AI usage for user {username}: {e}")


class AIServiceUnavailable(Exception):
    """Raised when Gemini could not be reached, carrying copy that is safe to show a user.

    Import failures write str(exception) straight into videos.status_error, which the
    dashboard renders (see import_manager's failure handler). Raising this instead of the
    provider's exception is what keeps a raw
    `429 RESOURCE_EXHAUSTED {'error': {'code': 429, ...}}` blob off the user's screen.
    """

    def __init__(self, kind: str, message: str, original: Exception = None):
        self.kind = kind
        self.original = original
        super().__init__(message)


# Attempts per model for errors that a plain retry can actually fix (server-side overload).
_MAX_OVERLOAD_RETRIES = 3
# Never block an import worker longer than this on a single provider-supplied backoff.
_MAX_RETRY_SLEEP_SECONDS = 90
# Used when Google reports a per-minute limit without saying how long to wait. Sized to clear
# a whole minute window rather than to feel responsive: this workload is token-bound, not
# request-bound (a video import is 50k-400k tokens against a 15 requests-per-minute ceiling),
# so an unlabelled 429 here is far more likely a token limit than a request one. Waiting out
# the window on the cheap tier beats escalating to one that costs several times more.
_DEFAULT_RATE_LIMIT_SLEEP_SECONDS = 60

_RETRY_DELAY_PATTERN = re.compile(r"retrydelay['\"]?\s*[:=]\s*['\"]?(\d+(?:\.\d+)?)s", re.IGNORECASE)


def _normalise_err(err) -> str:
    """Lowercases an exception and strips separators, so quota identifiers match regardless of
    whether Google spells them GenerateContentInputTokensPerModelPerMinute or
    generate_content_input_tokens_per_model_per_minute."""
    return re.sub(r"[\s\-_]", "", str(err).lower())


def _parse_retry_delay(err) -> float:
    """Returns the retryDelay Google attached to a 429, in seconds, or None.

    Honouring the provider's own number beats guessing: it knows when the window rolls over."""
    match = _RETRY_DELAY_PATTERN.search(str(err))
    if not match:
        return None
    try:
        return min(float(match.group(1)), _MAX_RETRY_SLEEP_SECONDS)
    except (TypeError, ValueError):
        return None


def _classify_api_error(err) -> str:
    """Buckets a Gemini exception so the caller can pick a recovery that can actually work.

    'overloaded'  , 503/UNAVAILABLE. Server-side and short lived, a plain retry usually wins.
    'rate_limit'  , 429 against a per-minute *request* quota. A short wait clears it.
    'token_quota' , 429 against a per-minute *token* quota. Retrying the same payload cannot
                    succeed until the window rolls over, and every attempt spends more of the
                    very quota that is exhausted. This is the case that must never be hammered:
                    three blind retries of a 120k-token video is 360k tokens against a 250k
                    per-minute ceiling, which turns one recoverable failure into a guaranteed
                    outage for the rest of the minute.
    'quota_daily' , 429 against a per-day quota. Nothing clears within this request.
    'model_error' , the model name was rejected. Worth trying the next one in the cascade.
    'fatal'       , bad schema, safety block, auth. Identical on a retry, so stop.
    """
    s = _normalise_err(err)

    if any(x in s for x in ("503", "unavailable", "overloaded", "highdemand", "temporary", "busy")):
        return "overloaded"

    if any(x in s for x in ("429", "resourceexhausted", "quota", "ratelimit")):
        if "perday" in s:
            return "quota_daily"
        if "inputtokens" in s or "tokencount" in s or "tokensperminute" in s:
            return "token_quota"
        return "rate_limit"

    if any(x in s for x in ("notfound", "404", "isnotsupported", "unsupportedmodel")):
        return "model_error"

    return "fatal"


_USER_FACING_AI_ERRORS = {
    "token_quota": (
        "The AI service hit its per-minute token limit for this account. Wait about a minute "
        "and try again. If it keeps happening, the API key's quota needs raising."
    ),
    "quota_daily": (
        "This API key has used up its daily AI quota. It resets tomorrow, or you can raise the "
        "limit in Google AI Studio."
    ),
    "rate_limit": (
        "The AI service is rate limiting this account right now. Wait a moment and try again."
    ),
    "overloaded": (
        "The AI service is temporarily overloaded. Please try again in a few minutes."
    ),
}
_GENERIC_AI_ERROR = "The AI service could not process this request. Please try again."


def _build_generation_config(response_schema, temperature: float):
    return types.GenerateContentConfig(
        response_mime_type="application/json",
        response_schema=response_schema,
        temperature=temperature,
        # Pins low media resolution (~66 tokens/frame). This is a cost *guard*, not a
        # cost *cut*: measured 2026-08-10 against gemini-3.5-flash-lite, native YouTube
        # ingestion already defaults to low, so LOW and MEDIUM both measure identical
        # to sending nothing (19,388 prompt tokens for a 3:33 video) while HIGH costs
        # 61,562 (+217%). Setting it explicitly means a change to that undocumented
        # default can't silently triple our per-video bill. Harmless on the text-only
        # callers of this helper. Requires google-genai >= 1.x: 0.3.0 hardcoded a
        # "not supported in Google AI" rejection in its Gemini-Developer-API path,
        # which is what broke every video import the last time this was tried.
        media_resolution="MEDIA_RESOLUTION_LOW"
    )


def generate_content_with_retry(client: genai.Client, model: str, contents, response_schema, temperature: float, action_type: str, username: str = "default_user") -> str:
    """Calls Gemini, retrying only where a retry can actually help, then falling back a tier.

    Retrying is not free here: `contents` usually carries a whole video, so every attempt
    re-uploads it and re-spends the per-minute token quota. The recovery is therefore chosen
    from the error class (see _classify_api_error) rather than applied blindly to anything
    that looks transient.

    Note that failed attempts never reach log_ai_usage, because there is no usage metadata to
    record and Google does not bill them. They do consume quota though, so ai_usage_logs will
    always understate what Google counted. That gap is why a burst of retries could exhaust a
    quota while the usage table showed a single call.
    """
    enforce_usage_limits(username)

    # Current-generation tiers, cheapest first. A different model has its own quota bucket, so
    # falling back can clear a rate limit, but 3.6-flash costs 5x the input and 3x the output
    # of 3.5-flash-lite (see _FALLBACK_MODEL_PRICING), so it is a last resort and is logged.
    cascade = [model] + [m for m in ("gemini-3.5-flash-lite", "gemini-3.6-flash") if m != model]

    last_error = None
    last_kind = "fatal"

    for model_index, candidate in enumerate(cascade):
        if model_index > 0:
            logger.warning(
                f"[AI Fallback] Escalating '{action_type}' from {cascade[model_index - 1]} to "
                f"{candidate} after {last_kind}. This tier may cost several times more per token."
            )

        for attempt in range(_MAX_OVERLOAD_RETRIES):
            try:
                response = client.models.generate_content(
                    model=candidate,
                    contents=contents,
                    config=_build_generation_config(response_schema, temperature)
                )

                usage = response.usage_metadata
                prompt_tokens = usage.prompt_token_count if usage else 0
                completion_tokens = usage.candidates_token_count if usage else 0
                log_ai_usage(candidate, prompt_tokens, completion_tokens, action_type, username=username)

                return response.text

            except Exception as e:
                last_error = e
                last_kind = _classify_api_error(e)

                if last_kind == "fatal":
                    # Same request, same rejection. Re-sending it to another tier would just
                    # buy a second identical failure at a higher price.
                    logger.error(f"[AI] '{action_type}' failed on {candidate}, not retryable: {e}")
                    raise AIServiceUnavailable("fatal", _GENERIC_AI_ERROR, original=e) from e

                if last_kind == "overloaded" and attempt < _MAX_OVERLOAD_RETRIES - 1:
                    sleep_for = min(2 ** (attempt + 1) + random.uniform(0, 1), _MAX_RETRY_SLEEP_SECONDS)
                    logger.warning(
                        f"[AI] {candidate} overloaded on '{action_type}' "
                        f"(attempt {attempt + 1}/{_MAX_OVERLOAD_RETRIES}), retrying in {sleep_for:.1f}s."
                    )
                    time.sleep(sleep_for)
                    continue

                if last_kind in ("rate_limit", "token_quota") and attempt == 0:
                    # Per-minute limits clear on their own. Wait the window out and try this
                    # model exactly once more, honouring the delay Google supplied when it gave
                    # one, since it knows when the window rolls over. One retry, not three: each
                    # attempt re-spends the quota that is already exhausted, and the point of
                    # waiting is to stop stacking attempts inside the same minute.
                    sleep_for = _parse_retry_delay(e) or _DEFAULT_RATE_LIMIT_SLEEP_SECONDS
                    logger.warning(
                        f"[AI] {candidate} hit a {last_kind} on '{action_type}', waiting "
                        f"{sleep_for:.1f}s before a single retry."
                    )
                    time.sleep(sleep_for)
                    continue

                # quota_daily, model_error, or the single retry above already used: stop hitting
                # this model. A daily quota will not clear within this request at all, so waiting
                # for it would only stall the import.
                logger.warning(f"[AI] {candidate} gave up on '{action_type}' ({last_kind}): {e}")
                break

    logger.error(f"[AI] '{action_type}' exhausted every model tier. Last error: {last_error}")
    raise AIServiceUnavailable(
        last_kind,
        _USER_FACING_AI_ERRORS.get(last_kind, _GENERIC_AI_ERROR),
        original=last_error
    ) from last_error

# --- Raw JSON Schemas to bypass all Pydantic v2 and SDK serialization bugs ---

quiz_item_schema = {
    "type": "OBJECT",
    "properties": {
        "question": { "type": "STRING", "description": "An open-ended active recall question." },
        "answer": { "type": "STRING", "description": "A concise correct answer." },
        "explanation": { "type": "STRING", "description": "A brief memory hook or explanation." },
        "timestamp_seconds": { "type": "INTEGER", "description": "Timestamp in seconds where this topic is explained in the video." }
    },
    "required": ["question", "answer", "explanation", "timestamp_seconds"]
}

stages_schema = {
    "type": "OBJECT",
    "properties": {
        "stage_0": { "type": "ARRAY", "items": quiz_item_schema, "description": "Stage 0 (Immediate Review): Core definitions, foundational key facts, and basic comprehension." },
        "stage_1": { "type": "ARRAY", "items": quiz_item_schema, "description": "Stage 1 (1 Day Later): Main concepts, core mechanics, and key structural relationships." },
        "stage_2": { "type": "ARRAY", "items": quiz_item_schema, "description": "Stage 2 (3 Days Later): Cause-and-effect reasoning, practical logic, and 'how/why' analysis." },
        "stage_3": { "type": "ARRAY", "items": quiz_item_schema, "description": "Stage 3 (7 Days Later): Complex scenario synthesis, edge cases, and comparative evaluation." },
        "stage_4": { "type": "ARRAY", "items": quiz_item_schema, "description": "Stage 4 (14-30 Days Later): High-level mastery transfer, critical judgment, and real-world application." }
    },
    "required": ["stage_0", "stage_1", "stage_2", "stage_3", "stage_4"]
}

outline_item_schema = {
    "type": "OBJECT",
    "properties": {
        "section_title": { "type": "STRING", "description": "Title of the chapter or section." },
        "timestamp_seconds": { "type": "INTEGER", "description": "Start timestamp in seconds of this section." },
        "section_summary": { "type": "STRING", "description": "Brief 1-2 sentence overview of what is covered in this section." }
    },
    "required": ["section_title", "timestamp_seconds", "section_summary"]
}

fact_check_schema = {
    "type": "OBJECT",
    "properties": {
        "overall_verdict": {
            "type": "STRING",
            "description": "General status of the video's accuracy (e.g. Factual & Accurate, Partially Disputed, Contains Outright Falsehoods)."
        },
        "disputed_claims": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "claim": { "type": "STRING", "description": "The specific claim made in the video." },
                    "actual_consensus": { "type": "STRING", "description": "The scientifically or historically accepted consensus fact." },
                    "severity": { "type": "STRING", "description": "Severity: Minor oversight, Major contradiction, or Falsehood." },
                    "source_citation": { "type": "STRING", "description": "Standard authority, domain reference, or publication source for consensus if applicable." }
                },
                "required": ["claim", "actual_consensus", "severity"]
            },
            "description": "List of specific claims that contradict general knowledge or consensus."
        },
        "verified_claims": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "claim": { "type": "STRING", "description": "Key claim made in the video that was verified to be correct/accurate." },
                    "evidence": { "type": "STRING", "description": "Supporting evidence or explanation of why it is factually correct." }
                },
                "required": ["claim", "evidence"]
            },
            "description": "List of key claims that were checked and confirmed as factually accurate."
        }
    },
    "required": ["overall_verdict", "disputed_claims", "verified_claims"]
}

video_analysis_schema = {
    "type": "OBJECT",
    "properties": {
        "category": {
            "type": "STRING",
            "description": "A single-word broad category (e.g. Economics, Tech, Health, History, Coding)."
        },
        "summary": {
            "type": "ARRAY",
            "items": { "type": "STRING" },
            "description": "Dynamic summary bullet points summarizing key takeaways. Scale quantity appropriately to video duration (3-5 for short videos, 6-10 for long videos)."
        },
        "outline": {
            "type": "ARRAY",
            "items": outline_item_schema,
            "description": "Structural chapters/outline of the video with start timestamps."
        },
        "quiz": {
            "type": "ARRAY",
            "items": quiz_item_schema,
            "description": "Primary active recall questions (Stage 0 set)."
        },
        "stages": stages_schema,
        "fact_check": fact_check_schema
    },
    "required": ["category", "summary", "outline", "quiz", "stages", "fact_check"]
}

topic_quiz_schema = {
    "type": "OBJECT",
    "properties": {
        "category": { "type": "STRING", "description": "Broad category of the topic." },
        "quiz": {
            "type": "ARRAY",
            "items": quiz_item_schema,
            "description": "Primary active recall questions."
        },
        "stages": stages_schema
    },
    "required": ["category", "quiz", "stages"]
}

goal_recs_schema = {
    "type": "OBJECT",
    "properties": {
        "search_queries": {
            "type": "ARRAY",
            "items": { "type": "STRING" },
            "description": "3-5 optimized YouTube search queries."
        },
        "key_concepts": {
            "type": "ARRAY",
            "items": { "type": "STRING" },
            "description": "3-5 core concepts to master this goal."
        }
    },
    "required": ["search_queries", "key_concepts"]
}

quiz_verification_schema = {
    "type": "OBJECT",
    "properties": {
        "is_correct": {
            "type": "BOOLEAN",
            "description": "True if the user's guess is conceptually correct and shows understanding of the answer."
        },
        "feedback": {
            "type": "STRING",
            "description": "A kind, constructive explanation. If correct, confirm and highlight why. If incorrect or partially correct, kindly explain what they got wrong/missed, and state the correct/corrected explanation."
        }
    },
    "required": ["is_correct", "feedback"]
}

# --- AI Methods ---

def analyze_youtube_video(youtube_url: str, question_count: int, username: str = "default_user") -> dict:
    """Uses Gemini's native YouTube multimodal URI integration (Part.from_uri) to process
    the YouTube video directly using Gemini 3.5 Flash-Lite without downloading any transcripts.
    Runs at low media resolution (see generate_content_with_retry) to keep the visual-frame
    cost down; there is no officially supported audio-only mode for native YouTube ingestion."""
    client = get_gemini_client(username=username)

    video_part = types.Part.from_uri(
        file_uri=youtube_url,
        mime_type="video/mp4"
    )

    # Bound worst-case cost from a single very long video: clip to the first
    # MAX_VIDEO_ANALYSIS_SECONDS when we can determine the video is longer than that via
    # the official YouTube Data API. If no API key is configured duration is unknown, so
    # we don't clip (better to process the full video than to guess wrong and cut a short one).
    video_id = youtube.extract_video_id(youtube_url)
    duration_seconds = youtube.get_video_duration_seconds(video_id) if video_id else None
    video_truncated = bool(duration_seconds and duration_seconds > MAX_VIDEO_ANALYSIS_SECONDS)
    if video_truncated:
        video_part.video_metadata = types.VideoMetadata(end_offset=f"{MAX_VIDEO_ANALYSIS_SECONDS}s")

    truncation_note = (
        f"\n    NOTE: Only the first {MAX_VIDEO_ANALYSIS_SECONDS // 60} minutes of this video were provided "
        ",  base your analysis strictly on that portion.\n"
        if video_truncated else ""
    )

    prompt = f"""{truncation_note}
    Analyze this YouTube video directly.

    Perform the following operations in a single pass:
    1. Categorize it into a broad, single-word category (e.g. Science, Coding, History, Business, Health, Design).
    2. Write a dynamic summary tailored to the video's content length (short content: 3-5 concise bullets, longer content: 6-10 structured key takeaways).
    3. Extract the video's structural outline/chapters with start timestamps in seconds, section titles, and brief summaries.
    4. Generate multi-stage active recall quiz sets for all 5 Spaced Repetition (SRS) stages AT ONCE:
       - Generate EXACTLY {question_count} questions for EACH stage (stage_0, stage_1, stage_2, stage_3, stage_4).
       - 'stage_0' (Immediate Review): Core definitions, foundational key facts, and basic term comprehension.
       - 'stage_1' (1 Day Later): Main concepts, core mechanics, and key structural relationships.
       - 'stage_2' (3 Days Later): Cause-and-effect reasoning, practical logic, and 'how/why' analysis.
       - 'stage_3' (7 Days Later): Complex scenario synthesis, edge cases, and comparative evaluation.
       - 'stage_4' (14-30 Days Later): High-level mastery transfer, critical judgment, and real-world application.
       - Populates 'quiz' with the stage_0 questions for backward compatibility.
       CRITICAL: Every question must focus on applicable knowledge and conceptual understanding based strictly on the video content. Each question MUST include `timestamp_seconds` indicating where in the video this topic is explained.
    5. Perform a detail-oriented fact-check comparison against scientific, historical, or domain consensus. Include standard consensus sources or reference citations for disputed claims if applicable.
    """
    
    model_name = "gemini-3.5-flash-lite"

    response_text = generate_content_with_retry(
        client=client,
        model=model_name,
        contents=[video_part, prompt],
        response_schema=video_analysis_schema,
        temperature=0.2,
        action_type="video_analysis",
        username=username
    )

    result = json.loads(response_text)
    result["video_truncated"] = video_truncated
    result["duration_seconds"] = duration_seconds
    return result

def truncate_transcript(text: str, max_words: int = 999999) -> str:
    """Returns the complete transcript text without truncation to ensure full video context is sent."""
    return text

def analyze_video_transcript(transcript_text: str, question_count: int, active_goals: list = None, username: str = "default_user") -> dict:
    """Fallback function for document text processing."""
    client = get_gemini_client(username=username)
    
    transcript_text = truncate_transcript(transcript_text)
    
    prompt = f"""
    Analyze this text content. Perform the following operations:
    1. Categorize it into a broad, single-word category.
    2. Write a dynamic summary tailored to the text length (3-8 key takeaway bullets).
    3. Extract a structural outline with section titles, timestamps (set to 0 if text has no timing), and summaries.
    4. Generate multi-stage active recall quiz sets for all 5 Spaced Repetition (SRS) stages AT ONCE:
       - Generate EXACTLY {question_count} questions for EACH stage (stage_0 through stage_4).
       - Each question MUST include `timestamp_seconds` (set to 0 for text documents).
    5. Perform a fact-check comparison against general knowledge consensus.
    
    Content:
    {transcript_text}
    """
    
    model_name = "gemini-3.5-flash-lite"
    response_text = generate_content_with_retry(
        client=client,
        model=model_name,
        contents=prompt,
        response_schema=video_analysis_schema,
        temperature=0.2,
        action_type="video_analysis",
        username=username
    )
    
    return json.loads(response_text)

def generate_topic_quiz(topic: str, description: str, question_count: int, username: str = "default_user") -> dict:
    client = get_gemini_client(username=username)
    
    prompt = f"""
    Generate an active recall quiz on the following topic across all 5 Spaced Repetition (SRS) review stages AT ONCE.
    Topic: {topic}
    Description/Context: {description}
    
    Required: Generate EXACTLY {question_count} quiz items for EACH stage (stage_0 through stage_4).
    - 'stage_0': Foundational terms & direct definitions.
    - 'stage_1': Conceptual mechanisms & structural logic.
    - 'stage_2': Cause-and-effect reasoning & practical scenarios.
    - 'stage_3': Synthesis & edge-case problem solving.
    - 'stage_4': Real-world mastery transfer & critical judgment.
    - Populate 'quiz' with stage_0 questions for backward compatibility.
    """
    
    model_name = "gemini-3.5-flash-lite"
    response_text = generate_content_with_retry(
        client=client,
        model=model_name,
        contents=prompt,
        response_schema=topic_quiz_schema,
        temperature=0.3,
        action_type="topic_quiz",
        username=username
    )
    
    return json.loads(response_text)


import struct

def pcm_to_wav(pcm_data: bytes, sample_rate: int = 24000, num_channels: int = 1, bits_per_sample: int = 16) -> bytes:
    """Wraps raw 16-bit PCM audio data with a standard RIFF WAV header."""
    byte_rate = sample_rate * num_channels * (bits_per_sample // 8)
    block_align = num_channels * (bits_per_sample // 8)
    data_size = len(pcm_data)
    chunk_size = 36 + data_size
    
    header = struct.pack(
        '<4sI4s4sIHHIIHH4sI',
        b'RIFF',
        chunk_size,
        b'WAVE',
        b'fmt ',
        16,                # Subchunk1Size for PCM
        1,                 # AudioFormat 1 = PCM
        num_channels,
        sample_rate,
        byte_rate,
        block_align,
        bits_per_sample,
        b'data',
        data_size
    )
    return header + pcm_data


def detect_text_language(text: str) -> str:
    """Detects primary language code for TTS generation."""
    clean = text.lower()
    german_chars = set("äöüß")
    spanish_chars = set("áéíóúñ¿¡")
    french_chars = set("éèêëàâùûç")
    italian_chars = set("àèéìòù")
    
    if any(c in clean for c in german_chars):
        return "de"
    if any(c in clean for c in spanish_chars):
        return "es"
    if any(c in clean for c in french_chars):
        return "fr"
    if any(c in clean for c in italian_chars):
        return "it"
    return "en"

_tts_audio_cache = {}

def generate_speech_audio(text: str, speed: float = 1.0) -> tuple[bytes, str]:
    """Generates audio via Edge-TTS with in-memory caching for zero latency."""
    clean_text = text.replace('<', ' ').replace('>', ' ').replace('&', 'and').strip()
    cache_key = f"{clean_text[:600]}_{speed:.2f}"
    if cache_key in _tts_audio_cache:
        return _tts_audio_cache[cache_key]

    lang = detect_text_language(text)

    voice_map = {
        "en": "en-US-GuyNeural",
        "de": "de-DE-KillianNeural",
        "es": "es-ES-AlvaroNeural",
        "fr": "fr-FR-HenriNeural",
        "it": "it-IT-DiegoNeural"
    }
    chosen_voice = voice_map.get(lang, "en-US-GuyNeural")
    speed_pct = int(round((speed - 1.0) * 100))
    rate_str = f"+{speed_pct}%" if speed_pct >= 0 else f"{speed_pct}%"

    # Primary: Edge-TTS (natural neural voice)
    try:

        import asyncio
        import concurrent.futures
        import edge_tts

        async def _gen_edge_audio():
            communicate = edge_tts.Communicate(clean_text[:600], chosen_voice, rate=rate_str)
            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp_f:
                tmp_p = tmp_f.name
            await communicate.save(tmp_p)
            with open(tmp_p, "rb") as f:
                data = f.read()
            if os.path.exists(tmp_p):
                try:
                    os.unlink(tmp_p)
                except Exception:
                    pass
            return data

        def _run_in_thread():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                return loop.run_until_complete(_gen_edge_audio())
            finally:
                loop.close()

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            mp3_bytes = pool.submit(_run_in_thread).result()

        if mp3_bytes and len(mp3_bytes) > 100:
            edge_res = (mp3_bytes, "audio/mp3")
            _tts_audio_cache[cache_key] = edge_res
            return edge_res
    except Exception as edge_err:
        logger.warning(f"Edge-TTS audio generation failed: {edge_err}")

    raise ValueError("TTS audio generation failed.")

def fact_check_transcript(transcript_text: str, username: str = "default_user") -> dict:
    """Compares the transcript content against general knowledge/scientific consensus to detect contradictions."""
    client = get_gemini_client(username=username)
    
    # Cap transcript length to control token costs
    transcript_text = truncate_transcript(transcript_text)
    
    prompt = f"""
    Analyze this transcript. Perform a detail-oriented fact-check comparison against generally accepted scientific consensus, historical consensus, or common factual knowledge.
    
    Identify:
    1. An overall verdict summarizing the video's accuracy (e.g. Factual & Accurate, Partially Disputed, Contains Outright Falsehoods).
    2. A list of specific claims made in the video that are incorrect, misleading, or highly disputed, explaining the actual consensus and severity of the contradiction.
    3. A list of key factual claims made in the video that you explicitly verified and found to be correct/accurate, explaining why they are correct.
    
    Transcript:
    {transcript_text}
    """
    
    model_name = "gemini-3.5-flash-lite"
    response_text = generate_content_with_retry(
        client=client,
        model=model_name,
        contents=prompt,
        response_schema=fact_check_schema,
        temperature=0.1,
        action_type="fact_check",
        username=username
    )
    
    return json.loads(response_text)

def generate_fact_check(title: str, transcript_text: str, username: str = "default_user") -> dict:
    """Alias for fact_check_transcript."""
    return fact_check_transcript(transcript_text, username=username)


def verify_user_guess(question: str, correct_answer: str, user_guess: str, username: str = "default_user") -> dict:
    """Uses Gemini Flash to conceptually evaluate a user's guess against the correct answer."""
    client = get_gemini_client(username=username)
    
    prompt = f"""
    Compare the user's typed guess to the correct answer for the given active recall question.
    Evaluate if the guess is conceptually similar or shows correct understanding of the answer.
    
    Question: {question}
    Correct Answer: {correct_answer}
    User's Guess: {user_guess}
    
    CRITICAL RULES FOR EVALUATION:
    1. Focus on conceptual understanding and applicable knowledge. Ignore spelling mistakes, exact wording, and grammatical errors.
    2. Be kind and generous: if they got the main idea right, mark it correct (is_correct = true).
    3. If they are mostly correct or missed minor details, still be encouraging: you can count it as correct (is_correct = true) but note the details in the feedback.
    4. If the guess is fundamentally incorrect, wrong, or completely unrelated, mark it incorrect (is_correct = false).
    5. In the 'feedback' field, provide a kind, encouraging response. If they are correct, congratulate/validate them. If incorrect, kindly explain what they missed and state the correct/corrected answer clearly so they can learn.
    """
    
    model_name = "gemini-3.5-flash-lite"
    response_text = generate_content_with_retry(
        client=client,
        model=model_name,
        contents=prompt,
        response_schema=quiz_verification_schema,
        temperature=0.1,
        action_type="quiz_verification",
        username=username
    )
    
    return json.loads(response_text)


def generate_daily_recommendations(goals: list, force_refresh: bool = False, username: str = "default_user") -> list:
    """Generates up to 6 daily curated video recommendations based on user's active learning goals, title, and description."""
    if not goals:
        return []

    from app import youtube, storage
    import random

    excluded_yt_ids = storage.get_excluded_youtube_ids(username=username)

    # 1. Distribute goals: Top 3 goals vs Remaining goals
    top_goals = goals[:3]
    remaining_goals = goals[3:]

    selected_goals = []
    if remaining_goals:
        sample_size = min(2, len(remaining_goals))
        sec_goals = random.sample(remaining_goals, sample_size)
        top_target = 4
        sec_target = 2
        for i, g in enumerate(top_goals):
            cnt = (top_target // len(top_goals)) + (1 if i < (top_target % len(top_goals)) else 0)
            selected_goals.append((g, cnt))
        for i, g in enumerate(sec_goals):
            cnt = (sec_target // len(sec_goals)) + (1 if i < (sec_target % len(sec_goals)) else 0)
            selected_goals.append((g, cnt))
    else:
        total_target = 6
        for i, g in enumerate(top_goals):
            cnt = (total_target // len(top_goals)) + (1 if i < (total_target % len(top_goals)) else 0)
            selected_goals.append((g, cnt))

    # 2. Use Gemini Flash to generate tailored search queries considering title + description
    client = get_gemini_client(username=username)
    goals_payload = [
        {
            "id": g.get("id"),
            "title": g.get("title", ""),
            "description": g.get("description", "") or "No additional description",
            "requested_count": count
        }
        for g, count in selected_goals if g.get("title")
    ]

    prompt = f"""
    You are an expert tutor curation assistant.
    For each of the following learning goals, generate targeted YouTube search queries to find the best educational video tutorials.
    CRITICAL: Carefully incorporate details, topics, frameworks, or focus areas mentioned in the user's goal description.

    {"Variation note: Provide alternative search queries and specific subtopic angles because the user requested a fresh batch of recommendations." if force_refresh else ""}

    Goals:
    {json.dumps(goals_payload, indent=2)}

    Output a JSON object containing an array 'queries' where each element has 'goal_id' (integer) and 'search_queries' (array of 2-3 specific search strings).
    """

    queries_by_goal = {}
    try:
        query_schema = {
            "type": "OBJECT",
            "properties": {
                "queries": {
                    "type": "ARRAY",
                    "items": {
                        "type": "OBJECT",
                        "properties": {
                            "goal_id": {"type": "INTEGER"},
                            "search_queries": {"type": "ARRAY", "items": {"type": "STRING"}}
                        },
                        "required": ["goal_id", "search_queries"]
                    }
                }
            },
            "required": ["queries"]
        }

        response_text = generate_content_with_retry(
            client=client,
            model="gemini-3.5-flash-lite",
            contents=prompt,
            response_schema=query_schema,
            temperature=0.8 if force_refresh else 0.4,
            action_type="daily_recommendation_queries",
            username=username
        )
        parsed = json.loads(response_text)
        for item in parsed.get("queries", []):
            queries_by_goal[item["goal_id"]] = item.get("search_queries", [])
    except Exception as e:
        logger.warning(f"AI daily recommendation queries generation failed: {e}")

    recommendations = []
    seen_yt_ids = set(excluded_yt_ids)

    # 3. Fetch YouTube videos per goal using AI queries
    for g, count in selected_goals:
        goal_id = g.get("id")
        goal_title = g.get("title", "")
        goal_desc = g.get("description", "")
        if not goal_title:
            continue

        ai_queries = queries_by_goal.get(goal_id, [])
        if not ai_queries:
            clean_desc = f" {goal_desc[:40]}" if goal_desc else ""
            ai_queries = [f"best tutorial {goal_title}{clean_desc}"]

        collected_for_goal = 0
        for q in ai_queries:
            if collected_for_goal >= count:
                break
            v_list = youtube.search_youtube_recommendations(q, max_results=4)
            for v in v_list:
                yt_id = v.get("youtube_id")
                if yt_id and yt_id not in seen_yt_ids and youtube.is_valid_duration(v.get("duration")):
                    seen_yt_ids.add(yt_id)
                    v["goal_id"] = goal_id
                    v["goal_title"] = goal_title
                    v["channel"] = v.get("views", "YouTube")
                    recommendations.append(v)
                    collected_for_goal += 1
                    if collected_for_goal >= count:
                        break

    return recommendations[:6]


def generate_goal_recommendations(goal_title: str, goal_description: str = "", username: str = "default_user") -> dict:
    """Generates key concepts, search queries, and video suggestions for a specific learning goal using Gemini."""
    client = get_gemini_client(username=username)

    prompt = f"""
    You are an expert tutor. For the following learning goal, output:
    1. 3-4 search queries to find top YouTube tutorials on this topic.
    2. 4-5 key concepts to master for this goal.

    Goal Title: {goal_title}
    Goal Description: {goal_description or 'No extra description'}
    """

    rec_schema = {
        "type": "OBJECT",
        "properties": {
            "search_queries": { "type": "ARRAY", "items": { "type": "STRING" } },
            "key_concepts": { "type": "ARRAY", "items": { "type": "STRING" } }
        },
        "required": ["search_queries", "key_concepts"]
    }

    try:
        response_text = generate_content_with_retry(
            client=client,
            model="gemini-3.5-flash-lite",
            contents=prompt,
            response_schema=rec_schema,
            temperature=0.3,
            action_type="goal_recommendations",
            username=username
        )
        return json.loads(response_text)
    except Exception as e:
        logger.warning(f"AI goal recommendations failed: {e}")
        return {
            "search_queries": [f"{goal_title} tutorial", f"learn {goal_title} basics"],
            "key_concepts": [f"Understand fundamentals of {goal_title}", f"Practical applications of {goal_title}"]
        }

