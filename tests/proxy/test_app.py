import logging

WU_PATH = "/weatherstation/updateweatherstation.php"
QUERY = "ID=IWARSA474&PASSWORD=hunter2&dateutc=now&tempf=50.0&humidity=60"


async def test_valid_update_returns_success(proxy):
    resp = await proxy.get(f"{WU_PATH}?{QUERY}")
    assert resp.status == 200
    assert resp.content_type == "text/plain"
    assert (await resp.text()).strip() == "success"


async def test_healthz(proxy):
    resp = await proxy.get("/healthz")
    assert resp.status == 200


async def test_unknown_path_is_404_and_logged_without_query(proxy, caplog):
    with caplog.at_level(logging.WARNING, logger="wu_proxy"):
        resp = await proxy.get("/something/else?PASSWORD=hunter2")
    assert resp.status == 404
    assert "/something/else" in caplog.text
    assert "hunter2" not in caplog.text


async def test_oversized_query_rejected(proxy):
    resp = await proxy.get(f"{WU_PATH}?x={'a' * 5000}")
    assert resp.status == 414
