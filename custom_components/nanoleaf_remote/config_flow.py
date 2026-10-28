"""Config flow for Nanoleaf Remote."""

from __future__ import annotations

import asyncio
import base64
import binascii
import json
import logging
import time
import uuid
from typing import Any

import voluptuous as vol
from bleak_retry_connector import BleakClientWithServiceCache, establish_connection
from homeassistant.components import bluetooth
from homeassistant.components.bluetooth import BluetoothServiceInfoBleak
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    TextSelector,
    TextSelectorConfig,
)

from .calibration import CalibrationSession
from .const import (
    CONF_ADDRESS,
    CONF_FACE_MAP,
    CONF_PAIRING,
    CONF_PAIRING_JSON,
    CONF_POWER_SAVING,
    CONF_SETUP_CODE,
    DOMAIN,
    LOCAL_NAME_PREFIX,
    PAIRING_TIMEOUT,
    VERIFY_TIMEOUT,
    WAIT_FOR_REMOTE,
)
from .discovery import (
    async_wait_for_service_info,
    homekit_device_id,
    normalize_device_id,
)
from .hapble import facemap, pair_verify, pairing, uuids
from .hapble.srp import SrpAuthenticationError
from .hapble.transport import HapBleAccessory

_LOGGER = logging.getLogger(__name__)

PAIRING_KEYS = (
    "controller_pairing_id",
    "controller_ltsk",
    "controller_ltpk",
    "accessory_pairing_id",
    "accessory_ltpk",
)


class FlowError(Exception):
    """A step failed; `reason` is a key of `config.error` in strings.json."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _is_nanoleaf_remote(info: BluetoothServiceInfoBleak) -> bool:
    return bool(info.name and info.name.startswith(LOCAL_NAME_PREFIX))


def _parse_pairing_json(raw: str) -> dict[str, str]:
    """Validate a pairing.json produced by the hapble command-line tools."""
    try:
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("not an object")
        parsed = {key: str(data[key]) for key in PAIRING_KEYS}
        for value in parsed.values():
            base64.b64decode(value, validate=True)
    except (ValueError, KeyError, binascii.Error) as err:
        raise FlowError("invalid_pairing_json") from err
    return parsed


class NanoleafRemoteConfigFlow(ConfigFlow, domain=DOMAIN):
    """Configure a Nanoleaf Remote."""

    VERSION = 1

    def __init__(self) -> None:
        self._discovery: BluetoothServiceInfoBleak | None = None

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Options: the face numbering table."""
        return NanoleafOptionsFlow()

    # -- helpers ---------------------------------------------------------

    def _address_selector(self) -> SelectSelector:
        """Dropdown of nearby candidates that also accepts a typed address.

        Lists devices named "Nanoleaf Remote" and every HomeKit BLE accessory
        in range, labelled with its HomeKit device ID (the ID of the Remote is
        printed by the hapble tools and stored in pairing.json).
        """
        current = self._async_current_ids()
        options = []
        for info in bluetooth.async_discovered_service_info(self.hass, False):
            device_id = homekit_device_id(info)
            if info.address in current or not (_is_nanoleaf_remote(info) or device_id):
                continue
            label = info.name or "HomeKit accessory"
            if device_id:
                label += f" - ID {device_id}"
            options.append(
                SelectOptionDict(value=info.address, label=f"{label} ({info.address})")
            )
        return SelectSelector(
            SelectSelectorConfig(options=options, custom_value=True, sort=True)
        )

    async def _async_find(self, address: str | None, device_id: str | None = None):
        """Resolve the BLEDevice, waiting for the Remote to wake and advertise."""
        info = await async_wait_for_service_info(
            self.hass, address, device_id, WAIT_FOR_REMOTE
        )
        if info is None:
            raise FlowError("device_not_found")
        return info

    async def _async_pair(self, address: str, setup_code: str) -> dict[str, str]:
        """Run HomeKit Pair-Setup and return the keys to store."""
        device = (await self._async_find(address)).device
        client = None
        try:
            client = await establish_connection(
                BleakClientWithServiceCache, device, "Nanoleaf Remote setup"
            )
            accessory = HapBleAccessory(device, client=client)
            async with asyncio.timeout(PAIRING_TIMEOUT):
                result = await pairing.pair_setup(
                    accessory.pair_setup_characteristic(),
                    setup_code,
                    str(uuid.uuid4()).encode("ascii"),
                )
        except ValueError as err:
            # Malformed setup code (not 8 digits).
            raise FlowError("invalid_setup_code") from err
        except SrpAuthenticationError as err:
            raise FlowError("invalid_auth") from err
        except pairing.PairSetupError as err:
            raise FlowError(self._reason_for_tlv_error(err.tlv_error)) from err
        except TimeoutError as err:
            raise FlowError("timeout") from err
        except Exception as err:
            # Never log or persist the submitted setup code or private keys.
            _LOGGER.warning("Nanoleaf Remote pairing failed (%s)", type(err).__name__)
            raise FlowError("cannot_connect") from err
        finally:
            await self._async_disconnect(client)

        return {
            key: base64.b64encode(getattr(result, key)).decode("ascii")
            for key in PAIRING_KEYS
        }

    async def _async_verify(
        self, address: str | None, pairing_data: dict[str, str]
    ) -> str:
        """Check that an existing pairing is still accepted; return the address."""
        stored = pairing.PairingResult(
            **{key: base64.b64decode(value) for key, value in pairing_data.items()}
        )
        info = await self._async_find(
            address, normalize_device_id(stored.accessory_pairing_id)
        )
        device = info.device
        client = None
        try:
            client = await establish_connection(
                BleakClientWithServiceCache, device, "Nanoleaf Remote setup"
            )
            accessory = HapBleAccessory(device, client=client)
            async with asyncio.timeout(VERIFY_TIMEOUT):
                await pair_verify.pair_verify(
                    accessory.pair_verify_characteristic(), stored
                )
        except pair_verify.PairVerifyError as err:
            _LOGGER.warning("Nanoleaf Remote rejected the imported pairing: %s", err)
            raise FlowError("pairing_rejected") from err
        except TimeoutError as err:
            raise FlowError("timeout") from err
        except Exception as err:
            _LOGGER.warning(
                "Nanoleaf Remote verification failed (%s)", type(err).__name__
            )
            raise FlowError("cannot_connect") from err
        finally:
            await self._async_disconnect(client)
        return info.address

    @staticmethod
    async def _async_disconnect(client) -> None:
        if client is None:
            return
        try:
            await client.disconnect()
        except Exception:  # noqa: BLE001
            _LOGGER.debug("Error while disconnecting during setup")

    @staticmethod
    def _reason_for_tlv_error(code: int | None) -> str:
        if code == uuids.TLVError.UNAVAILABLE:
            # The Remote only accepts one controller: it is still paired
            # with Apple Home (or a previous setup of this integration).
            return "already_paired"
        if code == uuids.TLVError.AUTHENTICATION:
            return "invalid_auth"
        if code in (uuids.TLVError.BACKOFF, uuids.TLVError.MAX_TRIES):
            return "too_many_attempts"
        if code == uuids.TLVError.BUSY:
            return "busy"
        return "pairing_failed"

    def _entry(self, address: str, name: str, pairing_data: dict[str, str]):
        return self.async_create_entry(
            title=name, data={CONF_ADDRESS: address, CONF_PAIRING: pairing_data}
        )

    # -- discovery -------------------------------------------------------

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> ConfigFlowResult:
        """Handle a Remote found by Home Assistant's Bluetooth discovery."""
        await self.async_set_unique_id(discovery_info.address.upper())
        self._abort_if_unique_id_configured()
        self._discovery = discovery_info
        self.context["title_placeholders"] = {
            "name": discovery_info.name or LOCAL_NAME_PREFIX
        }
        return await self.async_step_discovered()

    async def async_step_discovered(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Choose how to link a discovered Remote."""
        return self.async_show_menu(
            step_id="discovered", menu_options=["confirm", "import_pairing"]
        )

    async def async_step_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Pair a discovered Remote with its setup code."""
        assert self._discovery is not None
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                data = await self._async_pair(
                    self._discovery.address, user_input[CONF_SETUP_CODE].strip()
                )
            except FlowError as err:
                errors["base"] = err.reason
            else:
                return self._entry(
                    self._discovery.address,
                    self._discovery.name or LOCAL_NAME_PREFIX,
                    data,
                )
        return self.async_show_form(
            step_id="confirm",
            data_schema=vol.Schema({vol.Required(CONF_SETUP_CODE): str}),
            errors=errors,
        )

    # -- user-initiated --------------------------------------------------

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Choose how to add a Remote."""
        return self.async_show_menu(
            step_id="user", menu_options=["pair", "import_pairing"]
        )

    async def async_step_pair(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Pair a Remote with its 8-digit setup code."""
        errors: dict[str, str] = {}
        if user_input is not None:
            address = user_input[CONF_ADDRESS].strip().upper()
            await self.async_set_unique_id(address)
            self._abort_if_unique_id_configured()
            try:
                data = await self._async_pair(
                    address, user_input[CONF_SETUP_CODE].strip()
                )
            except FlowError as err:
                errors["base"] = err.reason
            else:
                return self._entry(address, LOCAL_NAME_PREFIX, data)
        return self.async_show_form(
            step_id="pair",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_ADDRESS): self._address_selector(),
                    vol.Required(CONF_SETUP_CODE): str,
                }
            ),
            errors=errors,
        )

    async def async_step_import_pairing(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Reuse a pairing created earlier with the hapble tools (pairing.json)."""
        errors: dict[str, str] = {}
        fixed = self._discovery.address if self._discovery else None
        if user_input is not None:
            typed = (fixed or user_input.get(CONF_ADDRESS) or "").strip().upper()
            try:
                data = _parse_pairing_json(user_input[CONF_PAIRING_JSON])
                # The address is optional: the Remote is found by the device
                # ID stored in the pairing when none is given.
                address = await self._async_verify(typed or None, data)
            except FlowError as err:
                errors["base"] = err.reason
            else:
                await self.async_set_unique_id(address.upper())
                self._abort_if_unique_id_configured()
                name = (self._discovery.name if self._discovery else None) or (
                    LOCAL_NAME_PREFIX
                )
                return self._entry(address, name, data)

        schema: dict[Any, Any] = {}
        if fixed is None:
            schema[vol.Optional(CONF_ADDRESS)] = self._address_selector()
        schema[vol.Required(CONF_PAIRING_JSON)] = TextSelector(
            TextSelectorConfig(multiline=True)
        )
        return self.async_show_form(
            step_id="import_pairing",
            data_schema=vol.Schema(schema),
            errors=errors,
        )


class NanoleafOptionsFlow(OptionsFlow):
    """Face numbering (by hand or calibrated) and the battery saving mode."""

    def __init__(self) -> None:
        self._session: CalibrationSession | None = None
        self._shown_at = 0.0

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return self.async_show_menu(
            step_id="init", menu_options=["calibrate", "manual", "power_saving"]
        )

    async def async_step_power_saving(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Choose between the permanent connection and the battery saving mode."""
        if user_input is not None:
            return self.async_create_entry(
                data={
                    **self.config_entry.options,
                    CONF_POWER_SAVING: user_input[CONF_POWER_SAVING],
                }
            )
        current = self.config_entry.options.get(CONF_POWER_SAVING, False)
        return self.async_show_form(
            step_id="power_saving",
            data_schema=vol.Schema(
                {vol.Required(CONF_POWER_SAVING, default=current): bool}
            ),
        )

    async def async_step_manual(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Paste a table (for example one printed by `poetry run calibrate`)."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                parsed = facemap.parse_face_map(user_input.get(CONF_FACE_MAP))
            except ValueError:
                errors["base"] = "invalid_face_map"
            else:
                return self.async_create_entry(
                    data={
                        **self.config_entry.options,
                        CONF_FACE_MAP: facemap.format_face_map(parsed),
                    }
                )
        current = self.config_entry.options.get(
            CONF_FACE_MAP, facemap.format_face_map(facemap.IDENTITY)
        )
        return self.async_show_form(
            step_id="manual",
            data_schema=vol.Schema({vol.Required(CONF_FACE_MAP, default=current): str}),
            errors=errors,
        )

    async def async_step_calibrate(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Start a calibration: the Remote must be connected."""
        runtime = getattr(self.config_entry, "runtime_data", None)
        # In battery saving mode the Remote connects when it is turned, so a
        # calibration needs no connection beforehand.
        if runtime is None or not (runtime.connected or runtime.power_saving):
            return self.async_abort(reason="not_connected")
        self._session = CalibrationSession()
        return await self.async_step_calibrate_face()

    async def async_step_calibrate_face(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """One face: the user turns the Remote onto it, then submits."""
        assert self._session is not None
        runtime = self.config_entry.runtime_data
        errors: dict[str, str] = {}

        if user_input is not None:
            position = runtime.last_position
            if position is None or position[1] < self._shown_at:
                errors["base"] = "no_rotation"
            else:
                try:
                    self._session.record(position[0])
                except ValueError:
                    errors["base"] = "position_reused"
            if not errors and self._session.done:
                runtime.suppress_events_until = 0.0
                face_map, _notes = self._session.table()
                if face_map is None:
                    return self.async_abort(reason="calibration_failed")
                return self.async_create_entry(
                    data={
                        **self.config_entry.options,
                        CONF_FACE_MAP: facemap.format_face_map(face_map),
                    }
                )

        self._shown_at = time.monotonic()
        # Keep automations quiet while the user turns the Remote around.
        runtime.suppress_events_until = self._shown_at + 300
        return self.async_show_form(
            step_id="calibrate_face",
            data_schema=vol.Schema({}),
            description_placeholders={
                "face": str(self._session.face),
                "total": str(self._session.face_count),
            },
            errors=errors,
        )
