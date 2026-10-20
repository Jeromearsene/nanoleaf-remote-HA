"""Config flow for Nanoleaf Remote."""

from __future__ import annotations

import asyncio
import base64
import logging
import uuid
from typing import Any

import voluptuous as vol
from bleak_retry_connector import BleakClientWithServiceCache, establish_connection
from homeassistant.components import bluetooth
from homeassistant.components.bluetooth import BluetoothServiceInfoBleak
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult

from .const import (
    CONF_ADDRESS,
    CONF_PAIRING,
    CONF_SETUP_CODE,
    DOMAIN,
    LOCAL_NAME_PREFIX,
    PAIRING_TIMEOUT,
)
from .hapble import pairing, uuids
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


class PairingFailed(Exception):
    """Pairing failed; `reason` is a key of `config.error` in strings.json."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _is_nanoleaf_remote(info: BluetoothServiceInfoBleak) -> bool:
    return bool(info.name and info.name.startswith(LOCAL_NAME_PREFIX))


class NanoleafRemoteConfigFlow(ConfigFlow, domain=DOMAIN):
    """Configure a Nanoleaf Remote."""

    VERSION = 1

    def __init__(self) -> None:
        self._discovery: BluetoothServiceInfoBleak | None = None
        self._discovered: dict[str, str] = {}

    async def _async_pair(self, address: str, setup_code: str) -> dict[str, str]:
        """Run HomeKit Pair-Setup and return the keys to store."""
        device = bluetooth.async_ble_device_from_address(
            self.hass, address, connectable=True
        )
        if device is None:
            raise PairingFailed("device_not_found")

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
            raise PairingFailed("invalid_setup_code") from err
        except SrpAuthenticationError as err:
            raise PairingFailed("invalid_auth") from err
        except pairing.PairSetupError as err:
            raise PairingFailed(self._reason_for_tlv_error(err.tlv_error)) from err
        except TimeoutError as err:
            raise PairingFailed("timeout") from err
        except Exception as err:
            # Never log or persist the submitted setup code or private keys.
            _LOGGER.warning("Nanoleaf Remote pairing failed (%s)", type(err).__name__)
            raise PairingFailed("cannot_connect") from err
        finally:
            if client is not None:
                try:
                    await client.disconnect()
                except Exception:  # noqa: BLE001
                    _LOGGER.debug("Error while disconnecting after pairing")

        return {
            key: base64.b64encode(getattr(result, key)).decode("ascii")
            for key in PAIRING_KEYS
        }

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

    async def _async_create(self, address: str, setup_code: str, name: str):
        try:
            pairing_data = await self._async_pair(address, setup_code)
        except PairingFailed as err:
            return err.reason
        return self.async_create_entry(
            title=name, data={CONF_ADDRESS: address, CONF_PAIRING: pairing_data}
        )

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> ConfigFlowResult:
        """Handle a Remote found by Home Assistant's Bluetooth discovery."""
        await self.async_set_unique_id(discovery_info.address)
        self._abort_if_unique_id_configured()
        self._discovery = discovery_info
        self.context["title_placeholders"] = {
            "name": discovery_info.name or LOCAL_NAME_PREFIX
        }
        return await self.async_step_confirm()

    async def async_step_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the setup code of a discovered Remote."""
        assert self._discovery is not None
        errors: dict[str, str] = {}
        if user_input is not None:
            outcome = await self._async_create(
                self._discovery.address,
                user_input[CONF_SETUP_CODE].strip(),
                self._discovery.name or LOCAL_NAME_PREFIX,
            )
            if not isinstance(outcome, str):
                return outcome
            errors["base"] = outcome
        return self.async_show_form(
            step_id="confirm",
            data_schema=vol.Schema({vol.Required(CONF_SETUP_CODE): str}),
            description_placeholders={
                "name": self._discovery.name or LOCAL_NAME_PREFIX
            },
            errors=errors,
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle a user-initiated setup (pick a nearby Remote or type its address)."""
        errors: dict[str, str] = {}
        current = self._async_current_ids()
        self._discovered = {
            info.address: f"{info.name} ({info.address})"
            for info in bluetooth.async_discovered_service_info(self.hass, False)
            if _is_nanoleaf_remote(info) and info.address not in current
        }

        if user_input is not None:
            address = user_input[CONF_ADDRESS].strip().upper()
            await self.async_set_unique_id(address)
            self._abort_if_unique_id_configured()
            outcome = await self._async_create(
                address,
                user_input[CONF_SETUP_CODE].strip(),
                LOCAL_NAME_PREFIX,
            )
            if not isinstance(outcome, str):
                return outcome
            errors["base"] = outcome

        address_field = vol.In(self._discovered) if self._discovered else str
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_ADDRESS): address_field,
                    vol.Required(CONF_SETUP_CODE): str,
                }
            ),
            errors=errors,
        )
