"""Config flow: generates the webhook the proxy posts readings to."""
from __future__ import annotations

from typing import Any

from homeassistant.components import webhook
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_WEBHOOK_ID

from .const import DOMAIN


class VevorWuConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._webhook_id: str | None = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")
        if self._webhook_id is None:
            self._webhook_id = webhook.async_generate_id()
        if user_input is not None:
            return self.async_create_entry(
                title="Vevor weather station",
                data={CONF_WEBHOOK_ID: self._webhook_id},
            )
        return self.async_show_form(
            step_id="user",
            description_placeholders={"path": f"/api/webhook/{self._webhook_id}"},
        )
