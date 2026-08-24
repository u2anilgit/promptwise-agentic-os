from core.diagnostics.redact import redact_secrets


def test_redacts_an_api_key_looking_string():
    text = "ANTHROPIC_API_KEY=sk-ant-api03-abcdef1234567890ABCDEF1234567890"
    redacted = redact_secrets(text)
    assert "sk-ant-api03" not in redacted
    assert "REDACTED" in redacted


def test_redacts_a_generic_password_assignment():
    text = 'password: "hunter2superSecret"'
    redacted = redact_secrets(text)
    assert "hunter2superSecret" not in redacted


def test_leaves_ordinary_text_untouched():
    text = "this is a normal log line about a test passing"
    assert redact_secrets(text) == text


def test_redacts_a_bearer_token():
    text = "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.abc.def"
    redacted = redact_secrets(text)
    assert "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9" not in redacted


from core.diagnostics.redact import contains_pii


def test_contains_pii_detects_an_email_address():
    assert contains_pii("contact me at jane.doe@example.com") is True


def test_contains_pii_detects_a_phone_number():
    assert contains_pii("call 555-123-4567 for details") is True


def test_contains_pii_detects_an_existing_secret_pattern():
    assert contains_pii("api_key: sk-ant-abcdefghijklmnopqrstuvwx") is True


def test_contains_pii_false_for_ordinary_text():
    assert contains_pii("user prefers pytest over unittest") is False
