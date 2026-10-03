import pytest

from wu_proxy.config import DEFAULT_UPSTREAM_URL, Settings


def test_from_env_defaults():
    s = Settings.from_env({"HA_WEBHOOK_URL": "http://h:8123/api/webhook/abc"})
    assert s.ha_webhook_url == "http://h:8123/api/webhook/abc"
    assert s.upstream_url == DEFAULT_UPSTREAM_URL
    assert s.relay_enabled is True
    assert s.host == "0.0.0.0"
    assert s.port == 80
    assert s.max_query_bytes == 4096
    assert s.ha_timeout == 5.0
    assert s.upstream_timeout == 10.0


def test_from_env_overrides():
    s = Settings.from_env(
        {
            "HA_WEBHOOK_URL": "http://h/x",
            "UPSTREAM_URL": "http://localhost:9/",
            "RELAY_ENABLED": "false",
            "PORT": "8080",
            "BIND_HOST": "192.168.1.60",
        }
    )
    assert s.upstream_url == "http://localhost:9"
    assert s.relay_enabled is False
    assert s.port == 8080
    assert s.host == "192.168.1.60"


def test_missing_webhook_url_raises():
    with pytest.raises(ValueError, match="HA_WEBHOOK_URL"):
        Settings.from_env({})


def test_relay_enabled_is_whitespace_and_case_tolerant():
    s = Settings.from_env({"HA_WEBHOOK_URL": "http://h/x", "RELAY_ENABLED": " TRUE "})
    assert s.relay_enabled is True


def test_repr_hides_webhook_url():
    s = Settings(ha_webhook_url="http://h/api/webhook/SECRETID")
    assert "SECRETID" not in repr(s)
