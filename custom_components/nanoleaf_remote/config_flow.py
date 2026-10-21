"""Config flow for Nanoleaf Remote."""

from __future__ import annotations

import asyncio
import base64
import binascii
import json
import logging
import uuid
from typing import Any

import voluptuous as vol
from bleak_retry_connector import BleakClientWithServiceCache, establish_connection
from homeassistant.components import bluetooth
from homeassistant.components.bluetooth import BluetoothServiceInfoBleak
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    TextSelector,
    TextSelectorConfig,
)

from .const import (
    CONF_ADDRESS,
    CONF_PAIRING,
    CONF_PAIRING_JSON,
    CONF_SETUP_CODE,
    DOMAIN,
    LOCAL_NAME_PREFIX,
    PAIRING_TIMEOUT,
    VERIFY_TIMEOUT,
)
from .hapble import pair_verify, pairing, uuids
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

    # -- helpers ---------------------------------------------------------

    def _address_selector(self) -> SelectSelector:
        """Dropdown of nearby Remotes that also accepts a typed address."""
        current = self._async_current_ids()
        options = [
            SelectOptionDict(value=info.address, label=f"{info.name} ({info.address})")
            for info in bluetooth.async_discovered_service_info(self.hass, False)
            if _is_nanoleaf_remote(info) and info.address not in current
        ]
        return SelectSelector(
            SelectSelectorConfig(options=options, custom_value=True, sort=True)
        )

    def _device(self, address: str):
        device = bluetooth.async_ble_device_from_address(
            self.hass, address, connectable=True
        )
        if device is None:
            raise FlowError("device_not_found")
        return device

    async def _async_pair(self, address: str, setup_code: str) -> dict[str, str]:
        """Run HomeKit Pair-Setup and return the keys to store."""
        device = self._device(address)
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

    async def _async_verify(self, address: str, pairing_data: dict[str, str]) -> None:
        """Check that an existing pairing is still accepted by the Remote."""
        device = self._device(address)
        stored = pairing.PairingResult(
            **{key: base64.b64decode(value) for key, value in pairing_data.items()}
        )
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
            address = (fixed or user_input[CONF_ADDRESS]).strip().upper()
            await self.async_set_unique_id(address)
            self._abort_if_unique_id_configured()
            try:
                data = _parse_pairing_json(user_input[CONF_PAIRING_JSON])
                await self._async_verify(address, data)
            except FlowError as err:
                errors["base"] = err.reason
            else:
                name = (self._discovery.name if self._discovery else None) or (
                    LOCAL_NAME_PREFIX
                )
                return self._entry(address, name, data)

        schema: dict[Any, Any] = {}
        if fixed is None:
            schema[vol.Required(CONF_ADDRESS)] = self._address_selector()
        schema[vol.Required(CONF_PAIRING_JSON)] = TextSelector(
            TextSelectorConfig(multiline=True)
        )
        return self.async_show_form(
            step_id="import_pairing",
            data_schema=vol.Schema(schema),
            errors=errors,
        )
