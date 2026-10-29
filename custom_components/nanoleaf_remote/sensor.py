"""Sensor entity exposing the Nanoleaf Remote's battery level."""

from __future__ import annotations

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import NanoleafConfigEntry, NanoleafRuntime
from .const import DOMAIN, signal_battery

DESCRIPTION = SensorEntityDescription(
    key="battery",
    device_class=SensorDeviceClass.BATTERY,
    state_class=SensorStateClass.MEASUREMENT,
    native_unit_of_measurement=PERCENTAGE,
    entity_category=EntityCategory.DIAGNOSTIC,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NanoleafConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the remote's battery sensor."""
    async_add_entities([NanoleafRemoteBattery(entry, entry.runtime_data)])


class NanoleafRemoteBattery(SensorEntity):
    """Report the Remote's battery level, read from its Battery service.

    Not every HomeKit accessory exposes a Battery service, so this entity
    stays unavailable until the first successful read rather than assuming
    one will ever come (see NanoleafRuntime._read_battery)."""

    entity_description = DESCRIPTION
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, entry: NanoleafConfigEntry, runtime: NanoleafRuntime) -> None:
        """Initialize the battery sensor."""
        self._entry_id = entry.entry_id
        self._runtime = runtime
        self._attr_unique_id = f"{entry.unique_id or entry.entry_id}_battery"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.unique_id or entry.entry_id)},
            name=entry.title,
            manufacturer="Nanoleaf",
            model="Remote",
        )

    @property
    def available(self) -> bool:
        """Only meaningful once a Battery Level read has actually succeeded."""
        return self._runtime.battery_level is not None

    @property
    def native_value(self) -> int | None:
        """Last battery percentage read (0-100)."""
        return self._runtime.battery_level

    async def async_added_to_hass(self) -> None:
        """Subscribe to this remote's battery updates."""
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, signal_battery(self._entry_id), self._handle_battery
            )
        )

    @callback
    def _handle_battery(self) -> None:
        """Refresh after a new Battery Level read."""
        self.async_write_ha_state()
