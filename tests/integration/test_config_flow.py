from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import CONF_WEBHOOK_ID
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.vevor_wu.const import DOMAIN


async def test_user_flow_creates_entry_with_webhook(hass):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    path = result["description_placeholders"]["path"]
    assert path.startswith("/api/webhook/")

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Vevor weather station"
    assert path == f"/api/webhook/{result['data'][CONF_WEBHOOK_ID]}"


async def test_only_one_instance_allowed(hass):
    MockConfigEntry(domain=DOMAIN, data={CONF_WEBHOOK_ID: "x"}).add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "single_instance_allowed"
