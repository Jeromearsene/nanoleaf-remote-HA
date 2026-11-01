"""Diagnostics for Nanoleaf Remote (secrets are redacted)."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from . import NanoleafConfigEntry
from .const import CONF_ADDRESS, CONF_PAIRING, CONF_PAIRING_JSON

# The pairing material contains the controller's private key and the
# accessory's identifiers; the address identifies the user's device.
TO_REDACT = {CONF_PAIRING, CONF_PAIRING_JSON, CONF_ADDRESS, "address"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: NanoleafConfigEntry
) -> dict[str, Any]:
    """Return redacted diagnostics for a config entry."""
    runtime = getattr(entry, "runtime_data", None)
    return {
        "entry": {
            "title": entry.title,
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            "options": dict(entry.options),
        },
        "runtime": None
        if runtime is None
        else {
            "connected": runtime.connected,
            "last_position": None
            if runtime.last_position is None
            else runtime.last_position[0],
            "battery_level": runtime.battery_level,
        },
    }
