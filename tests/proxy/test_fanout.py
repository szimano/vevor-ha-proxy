import logging

from wu_proxy.app import create_app
from wu_proxy.config import Settings

WU_PATH = "/weatherstation/updateweatherstation.php"
QUERY = "ID=IWARSA474&PASSWORD=hunter2&dateutc=now&tempf=50.0&humidity=60"


async def test_ha_receives_readings_without_password(proxy, fake_ha, drain):
    await proxy.get(f"{WU_PATH}?{QUERY}")
    await drain(proxy.app)
    assert len(fake_ha.requests) == 1
    assert fake_ha.requests[0]["json"] == {
        "ID": "IWARSA474",
        "dateutc": "now",
        "tempf": "50.0",
        "humidity": "60",
    }


async def test_wunderground_receives_original_query(proxy, fake_wu, drain):
    await proxy.get(f"{WU_PATH}?{QUERY}")
    await drain(proxy.app)
    assert len(fake_wu.requests) == 1
    assert fake_wu.requests[0]["raw_query"] == QUERY


async def test_relay_can_be_disabled(aiohttp_client, fake_ha, fake_wu, drain):
    settings = Settings(
        ha_webhook_url=fake_ha.url, upstream_url=fake_wu.url, relay_enabled=False
    )
    client = await aiohttp_client(create_app(settings))
    await client.get(f"{WU_PATH}?{QUERY}")
    await drain(client.app)
    assert len(fake_ha.requests) == 1
    assert fake_wu.requests == []


async def test_ha_failure_does_not_affect_response_or_relay(
    proxy, fake_ha, fake_wu, drain, caplog
):
    fake_ha.status = 500
    with caplog.at_level(logging.WARNING, logger="wu_proxy"):
        resp = await proxy.get(f"{WU_PATH}?{QUERY}")
        await drain(proxy.app)
    assert (await resp.text()).strip() == "success"
    assert len(fake_wu.requests) == 1
    assert "HTTP 500" in caplog.text
    assert "hunter2" not in caplog.text


async def test_upstream_error_status_is_logged_without_password(
    proxy, fake_wu, drain, caplog
):
    fake_wu.status = 500
    with caplog.at_level(logging.WARNING, logger="wu_proxy"):
        resp = await proxy.get(f"{WU_PATH}?{QUERY}")
        await drain(proxy.app)
    assert (await resp.text()).strip() == "success"
    assert "HTTP 500" in caplog.text
    assert "hunter2" not in caplog.text


async def test_unreachable_upstream_still_succeeds_and_does_not_leak(
    aiohttp_client, fake_ha, drain, caplog
):
    settings = Settings(
        ha_webhook_url=fake_ha.url,
        upstream_url="http://127.0.0.1:1",
        ha_timeout=2,
        upstream_timeout=2,
    )
    client = await aiohttp_client(create_app(settings))
    with caplog.at_level(logging.DEBUG):
        resp = await client.get(f"{WU_PATH}?{QUERY}")
        await drain(client.app)
    assert (await resp.text()).strip() == "success"
    assert len(fake_ha.requests) == 1
    assert "hunter2" not in caplog.text
