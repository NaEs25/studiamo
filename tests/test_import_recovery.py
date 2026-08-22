import pytest
from app import ai
from app.import_manager import (
    ImportInputError,
    ImportQueueManager,
    _GENERIC_IMPORT_ERROR,
    _user_facing_error,
)


def test_inflight_tracking():
    mgr = ImportQueueManager.get_instance()
    assert not mgr.is_task_inflight(999999)
    mgr._inflight_task_ids.add(999999)
    try:
        assert mgr.is_task_inflight(999999)
    finally:
        mgr._inflight_task_ids.discard(999999)
    assert not mgr.is_task_inflight(999999)


def test_reset_inflight_empty():
    mgr = ImportQueueManager.get_instance()
    # Should safely no-op without error when empty
    mgr.reset_inflight_tasks_on_shutdown()


@pytest.mark.parametrize("exc", [
    ImportInputError("Invalid YouTube URL."),
    ai.AIServiceUnavailable("rate_limit", "The AI service is rate limiting this account right now."),
    ai.UsageLimitExceeded("budget", "You've reached this month's AI usage allowance."),
])
def test_curated_error_copy_reaches_the_user(exc):
    assert _user_facing_error(exc) == str(exc)


def test_raw_provider_error_is_replaced():
    # The shape that started this: a provider rate-limit body carrying a signed URL and a
    # pointer to file a library issue. None of it may reach the import drawer.
    raw = RuntimeError(
        "Could not retrieve a transcript for the video https://www.youtube.com/watch?v=429 "
        "Client Error: Too Many Requests for url: https://www.youtube.com/api/timedtext?"
        "v=abc&signature=AB033F38913DB5775E24749406DBD6DDF4C6944C! please create an issue at "
        "https://github.com/example/example/issues"
    )
    assert _user_facing_error(raw) == _GENERIC_IMPORT_ERROR


def test_blank_curated_message_falls_back():
    assert _user_facing_error(ImportInputError("   ")) == _GENERIC_IMPORT_ERROR
