"""Nanoleaf Remote integration setup and BLE listener."""

from __future__ import annotations

import asyncio
import base64
import logging
import time
from contextlib import suppress
from typing import TypeAlias

from bleak import BleakClient
from bleak_retry_connector import BleakClientWithServiceCache, establish_connection
from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.dispatcher import async_dispatcher_send

from .const import (
    CONF_ADDRESS,
    CONF_FACE_MAP,
    CONF_PAIRING,
    PLATFORMS,
    POLL_INTERVAL,
    RECONNECT_MAX_DELAY,
    RECONNECT_MIN_DELAY,
    VERIFY_TIMEOUT,
    signal_event,
    signal_state,
)
from .discovery import find_service_info, normalize_device_id
from .hapble import facemap, pair_verify
from .hapble.ble_session import BleSecureSession
from .hapble.pairing import PairingResult
from .hapble.transport import HapBleAccessory

_LOGGER = logging.getLogger(__name__)

NanoleafConfigEntry: TypeAlias = "ConfigEntry[NanoleafRuntime]"


def decode_pairing(data: dict[str, str]) -> PairingResult:
    """Decode pairing material stored in the config entry."""
    return PairingResult(
        **{key: base64.b64decode(value) for key, value in data.items()}
    )


class NanoleafRuntime:
    """Keep one Remote connected and turn its switch reads into HA events."""

    def __init__(self, hass: HomeAssistant, entry: NanoleafConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.address: str = entry.data[CONF_ADDRESS]
        self.connected = False
        # Last raw position detected: (0-based index, time.monotonic()).
        self.last_position: tuple[int, float] | None = None
        # Rotation events are not forwarded to automations until then
        # (set while the options dialog runs a calibration).
        self.suppress_events_until = 0.0
        self._face_map = facemap.parse_face_map(entry.options.get(CONF_FACE_MAP))
        self._pairing = decode_pairing(entry.data[CONF_PAIRING])
        self._device_id = normalize_device_id(self._pairing.accessory_pairing_id)
        self._task: asyncio.Task | None = None
        self._stopping = False

    def start(self) -> None:
        """Start the background listener."""
        self._task = self.entry.async_create_background_task(
            self.hass, self._run(), name=f"nanoleaf_remote_{self.address}"
        )

    async def async_stop(self) -> None:
        """Stop the listener and wait for the connection to be released."""
        self._stopping = True
        if self._task:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    def _set_connected(self, connected: bool) -> None:
        if self.connected != connected:
            self.connected = connected
            async_dispatcher_send(self.hass, signal_state(self.entry.entry_id))

    def ble_device(self):
        """Current BLEDevice: by stored address, else by HomeKit device ID."""
        device = bluetooth.async_ble_device_from_address(
            self.hass, self.address, connectable=True
        )
        if device is None:
            info = find_service_info(self.hass, None, self._device_id)
            if info is not None:
                device = info.device
                if info.address != self.address:
                    _LOGGER.info(
                        "Nanoleaf Remote now advertises as %s (was %s)",
                        info.address,
                        self.address,
                    )
                    self.address = info.address
        return device

    async def _run(self) -> None:
        """Connect, authenticate and poll, reconnecting with backoff."""
        delay = RECONNECT_MIN_DELAY
        last_failure: str | None = None
        while not self._stopping:
            try:
                await self._session()
                # A session that ran and then ended (the Remote dropped us)
                # is not a failure: reconnect quickly.
                delay = RECONNECT_MIN_DELAY
                if last_failure is not None:
                    _LOGGER.info("Nanoleaf Remote %s reconnected", self.address)
                    last_failure = None
            except asyncio.CancelledError:
                raise
            except Exception as err:  # noqa: BLE001 - keep the listener alive
                failure = f"{type(err).__name__}: {err}"
                # Warn once per distinct failure, then drop to DEBUG so an
                # absent Remote does not flood the log.
                level = logging.WARNING if failure != last_failure else logging.DEBUG
                _LOGGER.log(
                    level,
                    "Nanoleaf Remote %s unavailable (%s); retrying in %.0f s",
                    self.address,
                    failure,
                    delay,
                )
                last_failure = failure
                delay = min(delay * 2, RECONNECT_MAX_DELAY)
            finally:
                self._set_connected(False)
            await asyncio.sleep(delay)

    async def _session(self) -> None:
        """One connection: verify the pairing, then poll until it drops."""
        device = self.ble_device()
        if device is None:
            raise RuntimeError("not seen by any Home Assistant Bluetooth adapter")

        client: BleakClient = await establish_connection(
            BleakClientWithServiceCache,
            device,
            self.entry.title,
            ble_device_callback=lambda: self.ble_device() or device,
        )
        try:
            accessory = HapBleAccessory(device, client=client)
            async with asyncio.timeout(VERIFY_TIMEOUT):
                keys = await pair_verify.pair_verify(
                    accessory.pair_verify_characteristic(), self._pairing
                )
            session = BleSecureSession(read_key=keys.read_key, write_key=keys.write_key)
            chars = accessory.programmable_switch_event_characteristics(session=session)
            if not chars:
                raise RuntimeError("no ProgrammableSwitchEvent characteristic found")

            _LOGGER.info(
                "Connected to Nanoleaf Remote %s (%d positions)",
                self.address,
                len(chars),
            )
            self._set_connected(True)
            while not self._stopping and client.is_connected:
                for index, char in enumerate(chars):
                    value = await char.read_value()
                    # An armed instance reads 0x00; the others read "null".
                    if value and value != b"null":
                        now = time.monotonic()
                        self.last_position = (index, now)
                        if now < self.suppress_events_until:
                            continue
                        face = facemap.face_for_index(self._face_map, index)
                        async_dispatcher_send(
                            self.hass,
                            signal_event(self.entry.entry_id),
                            f"face_{face}",
                            {"face": face},
                        )
                await asyncio.sleep(POLL_INTERVAL)
        finally:
            with suppress(Exception):
                await client.disconnect()


async def async_setup_entry(hass: HomeAssistant, entry: NanoleafConfigEntry) -> bool:
    """Set up a configured remote."""
    runtime = NanoleafRuntime(hass, entry)
    if runtime.ble_device() is None:
        raise ConfigEntryNotReady(
            f"Nanoleaf Remote {runtime.address} is not visible to Home Assistant Bluetooth"
        )
    entry.runtime_data = runtime
    entry.async_on_unload(runtime.async_stop)
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    runtime.start()
    return True


async def async_unload_entry(hass: HomeAssistant, entry: NanoleafConfigEntry) -> bool:
    """Unload a configured remote."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_options_updated(
    hass: HomeAssistant, entry: NanoleafConfigEntry
) -> None:
    """Reload the entry when its options (face map) change."""
    await hass.config_entries.async_reload(entry.entry_id)
