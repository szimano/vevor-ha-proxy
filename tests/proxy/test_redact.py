from wu_proxy.redact import REDACTED, redact_query, strip_secrets


def test_strip_secrets_removes_password():
    params = {"ID": "IWARSA474", "PASSWORD": "hunter2", "tempf": "50.0"}
    assert strip_secrets(params) == {"ID": "IWARSA474", "tempf": "50.0"}


def test_strip_secrets_is_case_insensitive():
    assert strip_secrets({"Password": "x", "a": "1"}) == {"a": "1"}


def test_redact_query_masks_password_value():
    out = redact_query("ID=IWARSA474&PASSWORD=hunter2&tempf=50.0")
    assert "hunter2" not in out
    assert f"PASSWORD={REDACTED}" in out
    assert "tempf=50.0" in out


def test_redact_query_handles_empty_and_blank_values():
    assert redact_query("") == ""
    assert redact_query("a=&b=1") == "a=&b=1"
