import pytest
from homeassistant.const import CONF_WEBHOOK_ID
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.vevor_wu.const import DOMAIN

WEBHOOK_ID = "test-webhook-id"
URL = f"/api/webhook/{WEBHOOK_ID}"


@pytest.fixture
async def entry(hass):
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_WEBHOOK_ID: WEBHOOK_ID},
        title="Vevor weather station",
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_post_stores_metric_readings(hass, hass_client_no_auth, entry):
    client = await hass_client_no_auth()
    resp = await client.post(URL, json={"ID": "X", "tempf": "50.0", "humidity": "60"})
    assert resp.status == 200
    assert entry.runtime_data.values == {"temperature": 10.0, "humidity": 60.0}
    assert entry.runtime_data.last_seen is not None


async def test_later_post_keeps_previous_values_for_missing_fields(
    hass, hass_client_no_auth, entry
):
    client = await hass_client_no_auth()
    await client.post(URL, json={"tempf": "50.0", "humidity": "60"})
    await client.post(URL, json={"tempf": "68.0", "humidity": "--"})
    assert entry.runtime_data.values == {"temperature": 20.0, "humidity": 60.0}


async def test_payload_without_valid_readings_does_not_refresh_last_seen(
    hass, hass_client_no_auth, entry
):
    client = await hass_client_no_auth()
    resp = await client.post(URL, json={"ID": "X", "tempf": "--"})
    assert resp.status == 200
    assert entry.runtime_data.values == {}
    assert entry.runtime_data.last_seen is None


async def test_invalid_json_is_rejected(hass, hass_client_no_auth, entry):
    client = await hass_client_no_auth()
    resp = await client.post(URL, data="not json")
    assert resp.status == 400


async def test_non_object_json_is_rejected(hass, hass_client_no_auth, entry):
    client = await hass_client_no_auth()
    resp = await client.post(URL, json=[1, 2, 3])
    assert resp.status == 400
