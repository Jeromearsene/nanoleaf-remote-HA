"""Event entity exposing Nanoleaf Remote face rotations."""

from __future__ import annotations

from homeassistant.components.event import EventEntity, EventEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, EVENT_SIGNAL, EVENT_TYPES

DESCRIPTION = EventEntityDescription(
    key="position", name="Position", icon="mdi:rotate-3d-variant"
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the remote event entity."""
    async_add_entities([NanoleafRemoteEvent(entry)])


class NanoleafRemoteEvent(EventEntity):
    """Represent rotations as Home Assistant event entity events."""

    entity_description = DESCRIPTION
    _attr_has_entity_name = True

    def __init__(self, entry: ConfigEntry) -> None:
        """Initialize the event entity."""
        self._attr_unique_id = f"{entry.entry_id}_position"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": "Nanoleaf Remote",
            "manufacturer": "Nanoleaf",
            "model": "Remote",
        }

    @property
    def event_types(self) -> list[str]:
        """Return supported face event types."""
        return EVENT_TYPES

    async def async_added_to_hass(self) -> None:
        """Subscribe to remote events when the entity is added."""
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(self.hass, EVENT_SIGNAL, self._handle_event)
        )

    @callback
    def _handle_event(self, event_type: str, attributes: dict) -> None:
        """Forward a rotation to the event entity."""
        self._trigger_event(event_type, attributes)
