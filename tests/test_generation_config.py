from app import ai


def test_generation_config_sends_no_sampling_or_thinking_budget_params():
    """Upcoming Gemini models reject these with 400 INVALID_ARGUMENT, which is classified fatal
    (no retry, no tier fallback), so a regression here would fail every AI call."""
    config = ai._build_generation_config({"type": "object"})
    for field in ("temperature", "top_p", "top_k"):
        assert getattr(config, field) is None
    assert config.thinking_config is None
