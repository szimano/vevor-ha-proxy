"""HTTP front end: accepts the station's Wunderground upload and fans it out."""
from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Coroutine
from typing import Any

import aiohttp
from aiohttp import web
from yarl import URL

from .config import Settings
from .redact import redact_query, strip_secrets

_LOGGER = logging.getLogger("wu_proxy")

WU_PATH = "/weatherstation/updateweatherstation.php"
SETTINGS_KEY = web.AppKey("settings", Settings)
SESSION_KEY = web.AppKey("session", aiohttp.ClientSession)
TASKS_KEY = web.AppKey("tasks", set)


async def forward_to_ha(
    session: aiohttp.ClientSession, settings: Settings, params: dict[str, str]
) -> None:
    """POST the readings (without secrets) to the HA webhook. Never raises."""
    payload = strip_secrets(params)
    try:
        async with session.post(
            settings.ha_webhook_url,
            json=payload,
            timeout=aiohttp.ClientTimeout(total=settings.ha_timeout),
        ) as resp:
            if resp.status >= 400:
                _LOGGER.warning("HA webhook returned HTTP %s", resp.status)
    except Exception as err:  # noqa: BLE001 - a background task must never raise
        # Log the class only: messages can embed the secret webhook URL.
        _LOGGER.warning("HA webhook delivery failed: %s", type(err).__name__)


async def relay_to_wunderground(
    session: aiohttp.ClientSession, settings: Settings, raw_query: str
) -> None:
    """Replay the station's original request upstream. Never raises."""
    url = URL(f"{settings.upstream_url}{WU_PATH}?{raw_query}", encoded=True)
    try:
        async with session.get(
            url, timeout=aiohttp.ClientTimeout(total=settings.upstream_timeout)
        ) as resp:
            if resp.status >= 400:
                _LOGGER.warning(
                    "Wunderground returned HTTP %s for %s",
                    resp.status,
                    redact_query(raw_query),
                )
            else:
                _LOGGER.debug("Wunderground relay HTTP %s", resp.status)
    except Exception as err:  # noqa: BLE001 - a background task must never raise
        _LOGGER.warning("Wunderground relay failed: %s", type(err).__name__)


def _spawn(app: web.Application, coro: Coroutine[Any, Any, None]) -> None:
    task = asyncio.create_task(coro)
    app[TASKS_KEY].add(task)
    task.add_done_callback(app[TASKS_KEY].discard)


async def handle_update(request: web.Request) -> web.Response:
    app = request.app
    settings = app[SETTINGS_KEY]
    raw_query = request.rel_url.raw_query_string
    if len(raw_query.encode()) > settings.max_query_bytes:
        return web.Response(status=414, text="query too long\n")
    session = app[SESSION_KEY]
    _spawn(app, forward_to_ha(session, settings, dict(request.query)))
    if settings.relay_enabled:
        _spawn(app, relay_to_wunderground(session, settings, raw_query))
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


async def _client_session(app: web.Application) -> AsyncIterator[None]:
    async with aiohttp.ClientSession() as session:
        app[SESSION_KEY] = session
        yield
        pending = list(app[TASKS_KEY])
        if pending:
            await asyncio.wait(pending, timeout=5)


def create_app(settings: Settings) -> web.Application:
    app = web.Application()
    app[SETTINGS_KEY] = settings
    app[TASKS_KEY] = set()
    app.cleanup_ctx.append(_client_session)
    app.router.add_get(WU_PATH, handle_update)
    app.router.add_get("/healthz", handle_healthz)
    app.router.add_route("*", "/{tail:.*}", handle_unknown)
    return app
