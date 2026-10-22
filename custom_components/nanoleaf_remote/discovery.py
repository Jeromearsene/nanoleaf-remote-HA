"""Find the Remote in Home Assistant's Bluetooth stack.

A HomeKit BLE accessory advertises Apple manufacturer data of the form
`06 <subtype/len> <status flags> <device id: 6 bytes> <category: 2 bytes> ...`
(HAP specification, BLE advertisement format). The 6-byte device ID is the
accessory's pairing identifier, which Pair-Setup also returns, so it identifies
the Remote even when its Bluetooth address is random or changes.
"""

from __future__ import annotations

from homeassistant.components import bluetooth
from homeassistant.components.bluetooth import BluetoothServiceInfoBleak
from homeassistant.core import HomeAssistant

APPLE_COMPANY_ID = 0x004C
HOMEKIT_ADV_TYPE = 0x06


def homekit_device_id(info: BluetoothServiceInfoBleak) -> str | None:
    """Return the advertised HomeKit device ID ("AA:BB:CC:DD:EE:FF"), if any."""
    data = info.manufacturer_data.get(APPLE_COMPANY_ID)
    if not data or len(data) < 9 or data[0] != HOMEKIT_ADV_TYPE:
        return None
    return ":".join(f"{byte:02X}" for byte in data[3:9])


def normalize_device_id(raw: bytes | str | None) -> str | None:
    """Normalise a pairing identifier to "AA:BB:CC:DD:EE:FF", else None."""
    if raw is None:
        return None
    if isinstance(raw, bytes):
        try:
            raw = raw.decode("ascii")
        except UnicodeDecodeError:
            return None
    parts = raw.strip().upper().split(":")
    if len(parts) != 6 or any(len(p) != 2 for p in parts):
        return None
    try:
        for part in parts:
            int(part, 16)
    except ValueError:
        return None
    return ":".join(parts)


def find_service_info(
    hass: HomeAssistant, address: str | None, device_id: str | None
) -> BluetoothServiceInfoBleak | None:
    """Look the Remote up by address first, then by its HomeKit device ID."""
    if address:
        for info in bluetooth.async_discovered_service_info(hass, True):
            if info.address.upper() == address.upper():
                return info
    if device_id:
        for info in bluetooth.async_discovered_service_info(hass, True):
            if homekit_device_id(info) == device_id:
                return info
    return None
