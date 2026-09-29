"""Tests for normal-mode display sanitization (app.ui.privacy)."""

from app.ui.privacy import sanitize_for_display


def test_dev_mode_returns_text_unchanged():
    raw = 'password="hunter2" api_key=gsk_123 role "user@ep-1"'
    assert sanitize_for_display(raw, True) == raw


def test_empty_and_none_safe():
    assert sanitize_for_display("", False) == ""
    assert sanitize_for_display("", True) == ""


def test_connection_string_redacted():
    text = 'failed for postgresql://bob:s3cret@ep-x.eu-central-1.aws.neon.tech/db'
    out = sanitize_for_display(text, False)
    assert "s3cret" not in out
    assert "ep-x" not in out
    assert "[connection string removed]" in out


def test_credential_assignment_redacted():
    out = sanitize_for_display('api_key = gsk_live_abc123', False)
    assert "gsk_live_abc123" not in out
    assert "api_key" in out  # the *kind* stays, the value goes


def test_password_token_secret_redacted():
    assert "hunter2" not in sanitize_for_display('password: hunter2', False)
    assert "tok123" not in sanitize_for_display('token=tok123', False)
    assert "s3cr3t" not in sanitize_for_display('Bearer s3cr3t', False)


def test_llm_account_identifier_redacted():
    # The exact leak class reported: LLM error text naming the account.
    out = sanitize_for_display('quota exceeded for account = ahmed-shili-proj', False)
    assert "ahmed-shili-proj" not in out
    assert "account" in out


def test_db_role_identifier_redacted():
    out = sanitize_for_display('role "user@ep-cool-123" does not have permission', False)
    assert "user@ep-cool-123" not in out
    assert "role" in out


def test_error_kind_and_status_codes_survive():
    # The useful parts a reviewer needs must NOT be scrubbed away.
    text = "Error code: 429 - Rate limit reached for model qwen"
    assert sanitize_for_display(text, False) == text
    text2 = "connection timeout after 30s"
    assert sanitize_for_display(text2, False) == text2


def test_app_authored_messages_untouched():
    text = "The LLM provider rate-limited this request. Wait a moment and try again."
    assert sanitize_for_display(text, False) == text


def test_normal_word_user_not_scrubbed_to_garbage():
    # Ordinary prose containing 'user' must stay readable.
    text = "The user asked for the top 10 products."
    out = sanitize_for_display(text, False)
    assert "user asked for the top 10 products" in out
