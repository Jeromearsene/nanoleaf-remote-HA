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
from homeassistant.components.bluetooth import BluetoothScanningMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.dispatcher import async_dispatcher_send

from .const import (
    ACTIVE_WINDOW,
    BASELINE_WINDOW,
    CONF_ADDRESS,
    CONF_FACE_MAP,
    CONF_PAIRING,
    CONF_POWER_SAVING,
    MIN_SESSION_GAP,
    PLATFORMS,
    POLL_INTERVAL,
    POWER_SAVING_ATTEMPTS,
    RECONNECT_MAX_DELAY,
    RECONNECT_MIN_DELAY,
    VERIFY_TIMEOUT,
    signal_event,
    signal_state,
)
from .discovery import (
    APPLE_COMPANY_ID,
    HOMEKIT_ADV_TYPE,
    find_service_info,
    homekit_device_id,
    homekit_gsn,
    normalize_device_id,
)
from .gsn import GsnWatcher
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


class RemoteNotSeen(RuntimeError):
    """No Bluetooth adapter currently hears the Remote (it is probably asleep)."""


class NanoleafRuntime:
    """Turn one Remote's switch reads into HA events.

    Default: stay connected and read every POLL_INTERVAL seconds. Battery
    saving mode: stay disconnected, watch the advertised state counter, and
    connect only when it changes (see gsn.py).
    """

    def __init__(self, hass: HomeAssistant, entry: NanoleafConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.address: str = entry.data[CONF_ADDRESS]
        self.connected = False
        self.power_saving: bool = bool(entry.options.get(CONF_POWER_SAVING, False))
        # Battery saving mode: false once the Remote could not be reached.
        self._reachable = True
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
        self._watcher = GsnWatcher(BASELINE_WINDOW)
        self._wake = asyncio.Event()
        self._unsub_adv = None

    def start(self) -> None:
        """Start the background listener."""
        if self.power_saving:
            self._unsub_adv = bluetooth.async_register_callback(
                self.hass,
                self._on_advertisement,
                {
                    "manufacturer_id": APPLE_COMPANY_ID,
                    "manufacturer_data_start": [HOMEKIT_ADV_TYPE],
                    "connectable": True,
                },
                BluetoothScanningMode.ACTIVE,
            )
            # One session at startup: it also registers for the Remote's events.
            self._wake.set()
        self._task = self.entry.async_create_background_task(
            self.hass,
            self._run_power_saving() if self.power_saving else self._run(),
            name=f"nanoleaf_remote_{self.address}",
        )

    async def async_stop(self) -> None:
        """Stop the listener and wait for the connection to be released."""
        self._stopping = True
        if self._unsub_adv is not None:
            self._unsub_adv()
            self._unsub_adv = None
        if self._task:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    @property
    def available(self) -> bool:
        """Connected, or (battery saving mode) not known to be unreachable."""
        return self.connected or (self.power_saving and self._reachable)

    def _set_connected(self, connected: bool) -> None:
        if self.connected != connected:
            self.connected = connected
            async_dispatcher_send(self.hass, signal_state(self.entry.entry_id))

    def _set_reachable(self, reachable: bool) -> None:
        if self._reachable != reachable:
            self._reachable = reachable
            async_dispatcher_send(self.hass, signal_state(self.entry.entry_id))

    def _on_advertisement(self, info, change) -> None:
        """Battery saving mode: wake the listener when the state counter moves."""
        if homekit_device_id(info) != self._device_id:
            return
        gsn = homekit_gsn(info)
        if gsn is None or self.connected:
            return
        if self._watcher.observe(gsn, time.monotonic()):
            _LOGGER.debug("Nanoleaf Remote state counter is now %d: connecting", gsn)
            self._wake.set()

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

    async def _run_power_saving(self) -> None:
        """Wait for the state counter to move, then do one short session."""
        last_start = 0.0
        last_failure: str | None = None
        while not self._stopping:
            await self._wake.wait()
            pause = last_start + MIN_SESSION_GAP - time.monotonic()
            if pause > 0:
                await asyncio.sleep(pause)
            self._wake.clear()
            last_start = time.monotonic()
            delay = RECONNECT_MIN_DELAY
            for attempt in range(1, POWER_SAVING_ATTEMPTS + 1):
                try:
                    await self._session()
                    self._set_reachable(True)
                    if last_failure is not None:
                        _LOGGER.info("Nanoleaf Remote %s reachable again", self.address)
                        last_failure = None
                    break
                except asyncio.CancelledError:
                    raise
                except RemoteNotSeen:
                    # Asleep: normal in this mode, wait for it to advertise.
                    _LOGGER.debug("Nanoleaf Remote %s is not in range", self.address)
                    break
                except Exception as err:  # noqa: BLE001 - keep the listener alive
                    failure = f"{type(err).__name__}: {err}"
                    _LOGGER.debug(
                        "Nanoleaf Remote %s: attempt %d failed",
                        self.address,
                        attempt,
                        exc_info=True,
                    )
                    if attempt == POWER_SAVING_ATTEMPTS:
                        level = (
                            logging.WARNING
                            if failure != last_failure
                            else logging.DEBUG
                        )
                        _LOGGER.log(
                            level,
                            "Nanoleaf Remote %s could not be reached (%s)",
                            self.address,
                            failure,
                        )
                        last_failure = failure
                        self._set_reachable(False)
                    else:
                        await asyncio.sleep(delay)
                        delay *= 2
                finally:
                    self._set_connected(False)
            self._watcher.session_ended(time.monotonic())

    @staticmethod
    def _ignore_indication(index: int, decoded, raw: bytes) -> None:
        """Indications are ignored: the Remote mirrors every response as one."""

    async def _session(self) -> None:
        """One connection: verify the pairing, then poll until it drops."""
        device = self.ble_device()
        if device is None:
            raise RemoteNotSeen("not seen by any Home Assistant Bluetooth adapter")

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
            # resync_window=1: the Remote may deliver a response twice (as an
            # indication and by read) right after we subscribe to its events.
            session = BleSecureSession(
                read_key=keys.read_key, write_key=keys.write_key, resync_window=1
            )
            chars = accessory.programmable_switch_event_characteristics(session=session)
            if not chars:
                raise RuntimeError("no ProgrammableSwitchEvent characteristic found")

            _LOGGER.info(
                "Connected to Nanoleaf Remote %s (%d positions)",
                self.address,
                len(chars),
            )
            self._set_connected(True)
            if self.power_saving:
                # Registers for the Remote's events, so that it moves its
                # state counter while we are away. Once subscribed it mirrors
                # every response as an indication: ignore them (decode=False
                # keeps the session counters to the reads) and keep polling.
                await accessory.subscribe_switch_events(
                    chars, self._ignore_indication, decode=False
                )
            last_activity = time.monotonic()
            while not self._stopping and client.is_connected:
                for index, char in enumerate(chars):
                    value = await char.read_value()
                    # An armed instance reads 0x00; the others read "null".
                    if value and value != b"null":
                        now = time.monotonic()
                        last_activity = now
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
                if (
                    self.power_saving
                    and time.monotonic() - last_activity > ACTIVE_WINDOW
                ):
                    return  # idle: release the Remote
                await asyncio.sleep(POLL_INTERVAL)
        finally:
            with suppress(Exception):
                await client.disconnect()


async def async_setup_entry(hass: HomeAssistant, entry: NanoleafConfigEntry) -> bool:
    """Set up a configured remote."""
    runtime = NanoleafRuntime(hass, entry)
    # In battery saving mode the Remote is asleep (silent) most of the time.
    if not runtime.power_saving and runtime.ble_device() is None:
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
