"""Sensors for the Vevor weather station; state is pushed by the webhook."""
from __future__ import annotations

from datetime import datetime, timedelta

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    DEGREE,
    PERCENTAGE,
    EntityCategory,
    UnitOfIrradiance,
    UnitOfPrecipitationDepth,
    UnitOfPressure,
    UnitOfSpeed,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.util import dt as dt_util

from . import VevorWuConfigEntry
from .const import DOMAIN, STALE_AFTER, signal_update

MEASUREMENT = SensorStateClass.MEASUREMENT

DESCRIPTIONS: tuple[SensorEntityDescription, ...] = (
    SensorEntityDescription(
        key="temperature",
        name="Temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=MEASUREMENT,
    ),
    SensorEntityDescription(
        key="dew_point",
        name="Dew point",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=MEASUREMENT,
    ),
    SensorEntityDescription(
        key="humidity",
        name="Humidity",
        device_class=SensorDeviceClass.HUMIDITY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=MEASUREMENT,
    ),
    SensorEntityDescription(
        key="pressure",
        name="Pressure",
        device_class=SensorDeviceClass.PRESSURE,
        native_unit_of_measurement=UnitOfPressure.HPA,
        state_class=MEASUREMENT,
    ),
    SensorEntityDescription(
        key="wind_speed",
        name="Wind speed",
        device_class=SensorDeviceClass.WIND_SPEED,
        native_unit_of_measurement=UnitOfSpeed.KILOMETERS_PER_HOUR,
        state_class=MEASUREMENT,
    ),
    SensorEntityDescription(
        key="wind_gust",
        name="Wind gust",
        device_class=SensorDeviceClass.WIND_SPEED,
        native_unit_of_measurement=UnitOfSpeed.KILOMETERS_PER_HOUR,
        state_class=MEASUREMENT,
    ),
    SensorEntityDescription(
        key="wind_direction",
        name="Wind direction",
        native_unit_of_measurement=DEGREE,
        state_class=MEASUREMENT,
    ),
    SensorEntityDescription(
        key="rain_last_hour",
        name="Rain last hour",
        device_class=SensorDeviceClass.PRECIPITATION,
        native_unit_of_measurement=UnitOfPrecipitationDepth.MILLIMETERS,
    ),
    SensorEntityDescription(
        key="rain_today",
        name="Rain today",
        device_class=SensorDeviceClass.PRECIPITATION,
        native_unit_of_measurement=UnitOfPrecipitationDepth.MILLIMETERS,
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    SensorEntityDescription(
        key="uv_index",
        name="UV index",
        native_unit_of_measurement="UV index",
        state_class=MEASUREMENT,
    ),
    SensorEntityDescription(
        key="solar_radiation",
        name="Solar radiation",
        device_class=SensorDeviceClass.IRRADIANCE,
        native_unit_of_measurement=UnitOfIrradiance.WATTS_PER_SQUARE_METER,
        state_class=MEASUREMENT,
    ),
)

LAST_UPDATE = SensorEntityDescription(
    key="last_update",
    name="Last update",
    device_class=SensorDeviceClass.TIMESTAMP,
    entity_category=EntityCategory.DIAGNOSTIC,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: VevorWuConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    entities: list[VevorWuSensor] = [VevorWuSensor(entry, d) for d in DESCRIPTIONS]
    entities.append(VevorWuLastUpdateSensor(entry, LAST_UPDATE))
    async_add_entities(entities)


class VevorWuSensor(SensorEntity):
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(
        self, entry: VevorWuConfigEntry, description: SensorEntityDescription
    ) -> None:
        self.entity_description = description
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="Vevor weather station",
            manufacturer="Vevor",
            model="YT60234",
        )

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                signal_update(self._entry.entry_id),
                self.async_write_ha_state,
            )
        )
        # Re-evaluate availability so sensors flip to unavailable during silence.
        self.async_on_remove(
            async_track_time_interval(
                self.hass, self._recheck_availability, timedelta(minutes=1)
            )
        )

    @callback
    def _recheck_availability(self, now: datetime) -> None:
        self.async_write_ha_state()

    @property
    def available(self) -> bool:
        last_seen = self._entry.runtime_data.last_seen
        return last_seen is not None and dt_util.utcnow() - last_seen < STALE_AFTER

    @property
    def native_value(self) -> float | None:
        return self._entry.runtime_data.values.get(self.entity_description.key)


class VevorWuLastUpdateSensor(VevorWuSensor):
    @property
    def native_value(self) -> datetime | None:  # type: ignore[override]
        return self._entry.runtime_data.last_seen
