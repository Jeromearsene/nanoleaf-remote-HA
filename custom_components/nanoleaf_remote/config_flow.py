"""Config flow for Nanoleaf Remote."""

from __future__ import annotations

import base64
import logging
import uuid

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.components import bluetooth
from homeassistant.const import CONF_ADDRESS

from .const import CONF_PAIRING, DOMAIN
from .hapble import pairing
from .hapble.transport import HapBleAccessory

_LOGGER = logging.getLogger(__name__)


class NanoleafRemoteConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Configure a Nanoleaf Remote."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        """Handle the user-initiated setup step."""
        errors = {}
        if user_input is not None:
            address = user_input[CONF_ADDRESS].strip()
            setup_code = user_input["setup_code"].strip()
            await self.async_set_unique_id(address.lower())
            self._abort_if_unique_id_configured()
            device = bluetooth.async_ble_device_from_address(
                self.hass, address, connectable=True
            )
            if device is None:
                errors["base"] = "device_not_found"
            else:
                try:
                    async with bluetooth.async_bleak_client(
                        self.hass, device, name="Nanoleaf Remote setup"
                    ) as client:
                        accessory = HapBleAccessory(device, client=client)
                        result = await pairing.pair_setup(
                            accessory.pair_setup_characteristic(),
                            setup_code,
                            str(uuid.uuid4()).encode("ascii"),
                        )
                    pairing_data = {
                        key: base64.b64encode(getattr(result, key)).decode("ascii")
                        for key in (
                            "controller_pairing_id",
                            "controller_ltsk",
                            "controller_ltpk",
                            "accessory_pairing_id",
                            "accessory_ltpk",
                        )
                    }
                    return self.async_create_entry(
                        title="Nanoleaf Remote",
                        data={CONF_ADDRESS: address, CONF_PAIRING: pairing_data},
                    )
                except Exception as err:
                    # Never log or persist the submitted setup code or private keys.
                    _LOGGER.warning(
                        "Nanoleaf Remote pairing failed (%s)", type(err).__name__
                    )
                    errors["base"] = "pairing_failed"
        schema = vol.Schema(
            {vol.Required(CONF_ADDRESS): str, vol.Required("setup_code"): str}
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)
