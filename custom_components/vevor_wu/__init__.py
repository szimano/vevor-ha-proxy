"""Vevor weather station integration: receives readings from the proxy."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime

from aiohttp import web
from homeassistant.components import webhook
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_WEBHOOK_ID, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.util import dt as dt_util

from .const import DOMAIN, signal_update
from .readings import parse_readings, unknown_params

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR]


@dataclass
class VevorWuData:
    values: dict[str, float] = field(default_factory=dict)
    last_seen: datetime | None = None
    seen_unknown: set[str] = field(default_factory=set)


type VevorWuConfigEntry = ConfigEntry[VevorWuData]


def _make_handler(entry: VevorWuConfigEntry):
    async def _handle(
        hass: HomeAssistant, webhook_id: str, request: web.Request
    ) -> web.Response:
        try:
            payload = await request.json()
        except ValueError:
            return web.Response(status=400, text="invalid json")
        if not isinstance(payload, dict):
            return web.Response(status=400, text="expected a json object")

        data = entry.runtime_data
        new_unknown = unknown_params(payload) - data.seen_unknown
        if new_unknown:
            data.seen_unknown |= new_unknown
            _LOGGER.debug("Ignoring unknown station parameters: %s", sorted(new_unknown))

        readings = parse_readings(payload)
        if readings:
            data.values.update(readings)
            data.last_seen = dt_util.utcnow()
            async_dispatcher_send(hass, signal_update(entry.entry_id))
        return web.Response(text="ok")

    return _handle


async def async_setup_entry(hass: HomeAssistant, entry: VevorWuConfigEntry) -> bool:
    entry.runtime_data = VevorWuData()
    webhook.async_register(
        hass,
        DOMAIN,
        entry.title,
        entry.data[CONF_WEBHOOK_ID],
        _make_handler(entry),
        local_only=True,
        allowed_methods=["POST"],
    )
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: VevorWuConfigEntry) -> bool:
    webhook.async_unregister(hass, entry.data[CONF_WEBHOOK_ID])
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
