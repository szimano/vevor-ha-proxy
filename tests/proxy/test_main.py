from wu_proxy.__main__ import run_kwargs
from wu_proxy.config import Settings


def test_run_kwargs_disables_access_log_and_binds_configured_address():
    settings = Settings(ha_webhook_url="http://h/x", host="192.168.1.60", port=80)
    kwargs = run_kwargs(settings)
    # The access log would print the query string, including the station password.
    assert kwargs["access_log"] is None
    assert kwargs["host"] == "192.168.1.60"
    assert kwargs["port"] == 80
