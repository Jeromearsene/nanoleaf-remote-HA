"""Nanoleaf Remote integration setup and BLE listener."""

from __future__ import annotations

import asyncio
import base64
import logging
from contextlib import suppress

from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_send

from .const import (
    CONF_ADDRESS,
    CONF_PAIRING,
    DOMAIN,
    EVENT_SIGNAL,
    PLATFORMS,
    POLL_INTERVAL,
)
from .hapble import pair_verify
from .hapble.ble_session import BleSecureSession
from .hapble.pairing import PairingResult
from .hapble.transport import HapBleAccessory

_LOGGER = logging.getLogger(__name__)


def _decode_pairing(data: dict) -> PairingResult:
    """Decode pairing material stored in the config entry."""
    return PairingResult(
        **{key: base64.b64decode(value) for key, value in data.items()}
    )


class NanoleafRuntime:
    """Manage the remote's Bluetooth connection and event polling."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self._task: asyncio.Task | None = None
        self._stopping = False

    def start(self) -> None:
        """Start the background listener."""
        self._task = self.hass.async_create_task(
            self._run(), name="nanoleaf_remote_listener"
        )

    async def stop(self) -> None:
        """Stop the background listener."""
        self._stopping = True
        if self._task:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task

    async def _run(self) -> None:
        """Connect, authenticate, and poll switch characteristics."""
        pairing = _decode_pairing(self.entry.data[CONF_PAIRING])
        address = self.entry.data[CONF_ADDRESS]
        while not self._stopping:
            try:
                device = bluetooth.async_ble_device_from_address(
                    self.hass, address, connectable=True
                )
                if device is None:
                    raise RuntimeError("Remote not found by Home Assistant Bluetooth")
                async with bluetooth.async_bleak_client(
                    self.hass, device, name="Nanoleaf Remote"
                ) as client:
                    accessory = HapBleAccessory(device, client=client)
                    keys = await pair_verify.pair_verify(
                        accessory.pair_verify_characteristic(), pairing
                    )
                    session = BleSecureSession(
                        read_key=keys.read_key, write_key=keys.write_key
                    )
                    chars = accessory.programmable_switch_event_characteristics(
                        session=session
                    )
                    if not chars:
                        raise RuntimeError(
                            "No ProgrammableSwitchEvent characteristics found"
                        )
                    _LOGGER.info(
                        "Connected to Nanoleaf Remote (%d switch characteristics)",
                        len(chars),
                    )
                    while not self._stopping and client.is_connected:
                        for index, char in enumerate(chars):
                            value = await char.read_value()
                            if value and value != b"null":
                                face = index + 1
                                async_dispatcher_send(
                                    self.hass,
                                    EVENT_SIGNAL,
                                    f"face_{face}",
                                    {"face": face},
                                )
                        await asyncio.sleep(POLL_INTERVAL)
            except asyncio.CancelledError:
                raise
            except Exception as err:
                _LOGGER.debug(
                    "Nanoleaf Remote disconnected; retrying (%s)", type(err).__name__
                )
                await asyncio.sleep(3)


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the integration domain."""
    hass.data.setdefault(DOMAIN, {})
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up a configured remote."""
    runtime = NanoleafRuntime(hass, entry)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = runtime
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    runtime.start()
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a configured remote."""
    if not await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        return False
    runtime = hass.data[DOMAIN].pop(entry.entry_id)
    await runtime.stop()
    return True
