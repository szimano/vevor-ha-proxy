from datetime import timedelta
from unittest.mock import patch

import pytest
from homeassistant.const import CONF_WEBHOOK_ID, STATE_UNAVAILABLE
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.vevor_wu.const import DOMAIN

WEBHOOK_ID = "test-webhook-id"
URL = f"/api/webhook/{WEBHOOK_ID}"
FULL = {
    "ID": "X",
    "tempf": "50.0",
    "dewptf": "41.0",
    "humidity": "60",
    "baromin": "29.92",
    "windspeedmph": "10",
    "windgustmph": "15",
    "winddir": "270",
    "rainin": "0.1",
    "dailyrainin": "0.25",
    "UV": "3",
    "solarRadiation": "500.5",
}


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


def _state(hass, name):
    return hass.states.get(f"sensor.vevor_weather_station_{name}")


async def test_sensors_unavailable_before_first_reading(hass, entry):
    assert _state(hass, "temperature").state == STATE_UNAVAILABLE
    assert _state(hass, "last_update").state == STATE_UNAVAILABLE


async def test_sensors_show_metric_values_after_post(hass, hass_client_no_auth, entry):
    client = await hass_client_no_auth()
    await client.post(URL, json=FULL)
    await hass.async_block_till_done()

    expected = {
        "temperature": ("10.0", "°C"),
        "dew_point": ("5.0", "°C"),
        "humidity": ("60.0", "%"),
        "pressure": ("1013.2", "hPa"),
        "wind_speed": ("16.1", "km/h"),
        "wind_gust": ("24.1", "km/h"),
        "wind_direction": ("270.0", "°"),
        "rain_last_hour": ("2.54", "mm"),
        "rain_today": ("6.35", "mm"),
        "uv_index": ("3.0", "UV index"),
        "solar_radiation": ("500.5", "W/m²"),
    }
    for name, (value, unit) in expected.items():
        state = _state(hass, name)
        assert state.state == value, name
        assert state.attributes["unit_of_measurement"] == unit, name
    assert _state(hass, "last_update").state != STATE_UNAVAILABLE


async def test_field_missing_from_later_post_is_unknown_until_reported(
    hass, hass_client_no_auth, entry
):
    client = await hass_client_no_auth()
    await client.post(URL, json={"tempf": "50.0"})
    await hass.async_block_till_done()
    assert _state(hass, "temperature").state == "10.0"
    assert _state(hass, "humidity").state == "unknown"


async def test_sensors_become_unavailable_after_silence(
    hass, hass_client_no_auth, entry
):
    client = await hass_client_no_auth()
    await client.post(URL, json=FULL)
    await hass.async_block_till_done()
    assert _state(hass, "temperature").state == "10.0"

    future = dt_util.utcnow() + timedelta(minutes=11)
    with patch("custom_components.vevor_wu.sensor.dt_util.utcnow", return_value=future):
        async_fire_time_changed(hass, future)
        await hass.async_block_till_done()
    assert _state(hass, "temperature").state == STATE_UNAVAILABLE
