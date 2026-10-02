"""HTTP front end: accepts the station's Wunderground upload and fans it out."""
from __future__ import annotations

import logging

from aiohttp import web

from .config import Settings

_LOGGER = logging.getLogger("wu_proxy")

WU_PATH = "/weatherstation/updateweatherstation.php"
SETTINGS_KEY = web.AppKey("settings", Settings)
TASKS_KEY = web.AppKey("tasks", set)


async def handle_update(request: web.Request) -> web.Response:
    settings = request.app[SETTINGS_KEY]
    raw_query = request.rel_url.raw_query_string
    if len(raw_query.encode()) > settings.max_query_bytes:
        return web.Response(status=414, text="query too long\n")
    return web.Response(text="success\n")


async def handle_healthz(request: web.Request) -> web.Response:
    return web.Response(text="ok\n")


async def handle_unknown(request: web.Request) -> web.Response:
    # Log the path only: the query string may contain the station password.
    _LOGGER.warning(
        "Unexpected request: %s %s (host=%s)",
        request.method,
        request.path,
        request.host,
    )
    return web.Response(status=404, text="not found\n")


def create_app(settings: Settings) -> web.Application:
    app = web.Application()
    app[SETTINGS_KEY] = settings
    app[TASKS_KEY] = set()
    app.router.add_get(WU_PATH, handle_update)
    app.router.add_get("/healthz", handle_healthz)
    app.router.add_route("*", "/{tail:.*}", handle_unknown)
    return app
