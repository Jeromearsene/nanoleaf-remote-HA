"""Event entity exposing Nanoleaf Remote face rotations."""

from __future__ import annotations

from homeassistant.components.event import EventEntity, EventEntityDescription
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import NanoleafConfigEntry, NanoleafRuntime
from .const import DOMAIN, EVENT_TYPES, signal_event, signal_state

DESCRIPTION = EventEntityDescription(
    key="position",
    translation_key="position",
    icon="mdi:rotate-3d-variant",
    event_types=EVENT_TYPES,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NanoleafConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the remote event entity."""
    async_add_entities([NanoleafRemoteEvent(entry, entry.runtime_data)])


class NanoleafRemoteEvent(EventEntity):
    """Represent rotations as Home Assistant event entity events."""

    entity_description = DESCRIPTION
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, entry: NanoleafConfigEntry, runtime: NanoleafRuntime) -> None:
        """Initialize the event entity."""
        self._entry_id = entry.entry_id
        self._runtime = runtime
        self._attr_unique_id = f"{entry.unique_id or entry.entry_id}_position"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.unique_id or entry.entry_id)},
            name=entry.title,
            manufacturer="Nanoleaf",
            model="Remote",
        )

    @property
    def available(self) -> bool:
        """The entity is available while the Remote is connected."""
        return self._runtime.connected

    async def async_added_to_hass(self) -> None:
        """Subscribe to this remote's events and connection state."""
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, signal_event(self._entry_id), self._handle_event
            )
        )
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, signal_state(self._entry_id), self._handle_state
            )
        )

    @callback
    def _handle_event(self, event_type: str, attributes: dict) -> None:
        """Forward a rotation to the event entity."""
        self._trigger_event(event_type, attributes)
        self.async_write_ha_state()

    @callback
    def _handle_state(self) -> None:
        """Refresh availability after a connect or disconnect."""
        self.async_write_ha_state()
