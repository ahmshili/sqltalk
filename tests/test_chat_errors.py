"""User-facing error mapping for LLM/provider failures."""

from app.ui.chat import _friendly_error


def test_daily_free_quota_message():
    msg = _friendly_error(
        Exception("Error code: 429 - Rate limit exceeded: free-models-per-day. "
                  "Add 10 credits to unlock 1000 free model requests per day")
    )
    assert "daily" in msg.lower()
    assert "fallback" in msg.lower()


def test_402_missing_credits_message():
    msg = _friendly_error(
        Exception("Error code: 402 - This request requires more credits, "
                  "or fewer max_tokens. You requested up to 131072 tokens, "
                  "but can only afford 3139.")
    )
    assert "credits" in msg.lower()
    assert "paid-only" in msg.lower()


def test_404_retired_model_message():
    msg = _friendly_error(
        Exception("Error code: 404 - {'error': {'message': "
                  "'No endpoints found for meta-llama/llama-3.1-405b-instruct:free.'}}")
    )
    assert "no longer exists" in msg.lower()
    assert "openrouter_model" in msg.lower()


def test_generic_rate_limit_message():
    msg = _friendly_error(Exception("Error code: 429 - rate limit exceeded"))
    assert "rate-limited" in msg.lower()


def test_interpreter_shutdown_maps_to_restart_message():
    # Streamlit tears down the interpreter mid-run (script rerun/restart);
    # the ThreadPoolExecutor then rejects new work with this RuntimeError.
    msg = _friendly_error(
        RuntimeError("cannot schedule new futures after interpreter shutdown")
    )
    assert "restarted" in msg.lower()
    assert "send it again" in msg.lower()


def test_daily_quota_takes_precedence_over_generic_429():
    # The per-day message also contains "429"/"rate limit"; the specific
    # daily-quota guidance must win.
    msg = _friendly_error(Exception("429 free-models-per-day rate limit"))
    assert "daily" in msg.lower()
