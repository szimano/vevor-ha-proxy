import asyncio
import logging

from wu_proxy.app import TASKS_KEY, create_app
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


async def test_relay_does_not_follow_redirects(
    aiohttp_client, aiohttp_server, fake_ha, drain, caplog
):
    from aiohttp import web

    other_hits = []

    async def other(request):
        other_hits.append(request.rel_url.raw_query_string)
        return web.Response(text="success\n")

    other_app = web.Application()
    other_app.router.add_get("/{tail:.*}", other)
    other_server = await aiohttp_server(other_app)
    target = str(other_server.make_url("/elsewhere"))

    async def redirect(request):
        return web.Response(status=302, headers={"Location": target})

    up_app = web.Application()
    up_app.router.add_get(WU_PATH, redirect)
    up_server = await aiohttp_server(up_app)

    settings = Settings(
        ha_webhook_url=fake_ha.url,
        upstream_url=str(up_server.make_url("")).rstrip("/"),
        ha_timeout=2,
        upstream_timeout=2,
    )
    client = await aiohttp_client(create_app(settings))
    with caplog.at_level(logging.DEBUG):
        resp = await client.get(f"{WU_PATH}?{QUERY}")
        await drain(client.app)
    assert (await resp.text()).strip() == "success"
    assert other_hits == []
    assert "HTTP 302" in caplog.text
    assert "hunter2" not in caplog.text


async def test_malformed_upstream_url_does_not_raise(
    aiohttp_client, fake_ha, caplog, monkeypatch
):
    import wu_proxy.app as app_mod

    spawned = []
    real_spawn = app_mod._spawn

    def recording_spawn(app, coro):
        before = set(app[TASKS_KEY])
        real_spawn(app, coro)
        spawned.extend(set(app[TASKS_KEY]) - before)

    monkeypatch.setattr(app_mod, "_spawn", recording_spawn)
    settings = Settings(
        ha_webhook_url=fake_ha.url, upstream_url="http://[bad", ha_timeout=2
    )
    client = await aiohttp_client(create_app(settings))
    with caplog.at_level(logging.DEBUG):
        resp = await client.get(f"{WU_PATH}?{QUERY}")
        results = await asyncio.gather(*spawned, return_exceptions=True)
    assert (await resp.text()).strip() == "success"
    assert len(spawned) == 2
    assert not any(isinstance(r, BaseException) for r in results)
    assert len(fake_ha.requests) == 1
    assert "hunter2" not in caplog.text


async def test_encoded_dateutc_relayed_byte_identical(proxy, fake_wu, drain):
    query = "ID=X&PASSWORD=hunter2&dateutc=2026-10-02+12%3A00%3A00&tempf=50.0"
    # Raw socket: HTTP clients normalize %XX escapes in the request target.
    reader, writer = await asyncio.open_connection(
        proxy.server.host, proxy.server.port
    )
    request_line = f"GET {WU_PATH}?{query} HTTP/1.1"
    writer.write(f"{request_line}\r\nHost: x\r\nConnection: close\r\n\r\n".encode())
    await writer.drain()
    await reader.read()
    writer.close()
    await drain(proxy.app)
    assert fake_wu.requests[0]["raw_query"] == query
