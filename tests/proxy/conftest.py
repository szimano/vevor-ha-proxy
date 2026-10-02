import asyncio

import pytest
from aiohttp import web

from wu_proxy.app import TASKS_KEY, create_app
from wu_proxy.config import Settings


class Recorder:
    def __init__(self):
        self.requests = []
        self.status = 200
        self.url = ""


@pytest.fixture
async def fake_ha(aiohttp_server):
    rec = Recorder()

    async def handler(request):
        rec.requests.append({"json": await request.json()})
        return web.Response(status=rec.status, text="ok")

    app = web.Application()
    app.router.add_post("/api/webhook/abc", handler)
    server = await aiohttp_server(app)
    rec.url = str(server.make_url("/api/webhook/abc"))
    return rec


@pytest.fixture
async def fake_wu(aiohttp_server):
    rec = Recorder()

    async def handler(request):
        rec.requests.append({"raw_query": request.rel_url.raw_query_string})
        return web.Response(status=rec.status, text="success\n")

    app = web.Application()
    app.router.add_get("/weatherstation/updateweatherstation.php", handler)
    server = await aiohttp_server(app)
    rec.url = str(server.make_url("")).rstrip("/")
    return rec


@pytest.fixture
async def proxy(aiohttp_client, fake_ha, fake_wu):
    settings = Settings(
        ha_webhook_url=fake_ha.url,
        upstream_url=fake_wu.url,
        ha_timeout=2,
        upstream_timeout=2,
    )
    return await aiohttp_client(create_app(settings))


@pytest.fixture
def drain():
    async def _drain(app):
        await asyncio.gather(*list(app[TASKS_KEY]), return_exceptions=True)

    return _drain
