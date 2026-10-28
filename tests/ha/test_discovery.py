"""Finding the Remote by its HomeKit device ID (no hardware)."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import patch

import pytest

pytest.importorskip("homeassistant")

from custom_components.nanoleaf_remote import discovery  # noqa: E402

DEVICE_ID = "D6:BD:09:C0:32:1D"
# Layout from the HAP-BLE advertisement: 06, subtype/len, flags, device ID,
# category (15 = programmable switch), ...
REMOTE = SimpleNamespace(
    address="FA:2E:63:20:7F:BE",
    name=None,
    manufacturer_data={
        76: bytes([6, 0x31, 0, 0xD6, 0xBD, 0x09, 0xC0, 0x32, 0x1D, 0x0F, 0])
    },
)
OTHER = SimpleNamespace(
    address="11:22:33:44:55:66",
    name=None,
    manufacturer_data={76: bytes([6, 0x31, 0, 1, 2, 3, 4, 5, 6, 0x0F, 0])},
)
NOT_HOMEKIT = SimpleNamespace(
    address="AA:AA:AA:AA:AA:AA", name=None, manufacturer_data={76: bytes([2, 0x15])}
)


def test_device_id_is_read_from_the_apple_advertisement() -> None:
    assert discovery.homekit_device_id(REMOTE) == DEVICE_ID
    assert discovery.homekit_device_id(NOT_HOMEKIT) is None


def test_normalize_device_id() -> None:
    assert discovery.normalize_device_id(b"d6:bd:09:c0:32:1d") == DEVICE_ID
    assert discovery.normalize_device_id("not an id") is None
    assert discovery.normalize_device_id(b"\xff\xfe") is None
    assert discovery.normalize_device_id(None) is None


def _seen(*infos):
    return patch.object(
        discovery.bluetooth, "async_discovered_service_info", return_value=list(infos)
    )


def test_found_in_the_cache_by_device_id() -> None:
    with _seen(OTHER, REMOTE):
        found = asyncio.run(
            discovery.async_wait_for_service_info(None, None, DEVICE_ID, 1)
        )
    assert found is REMOTE


def test_waits_for_the_next_advertisement() -> None:
    async def fake_wait(hass, callback, matcher, mode, timeout):
        assert callback(OTHER) is False
        assert callback(REMOTE) is True
        return REMOTE

    with (
        _seen(OTHER),
        patch.object(discovery.bluetooth, "async_process_advertisements", fake_wait),
    ):
        found = asyncio.run(
            discovery.async_wait_for_service_info(None, None, DEVICE_ID, 1)
        )
    assert found is REMOTE


def test_gives_up_after_the_timeout() -> None:
    async def timeout(*args):
        raise TimeoutError

    with (
        _seen(OTHER),
        patch.object(discovery.bluetooth, "async_process_advertisements", timeout),
    ):
        found = asyncio.run(
            discovery.async_wait_for_service_info(None, None, DEVICE_ID, 1)
        )
    assert found is None


def test_gsn_is_read_from_the_advertisement() -> None:
    # ... category 0x000F, GSN 52 (0x0034), config number 115, compat version 2
    full = SimpleNamespace(
        address="FA:2E:63:20:7F:BE",
        name=None,
        manufacturer_data={
            76: bytes([6, 0x31, 0, 0xD6, 0xBD, 0x09, 0xC0, 0x32, 0x1D])
            + bytes([0x0F, 0x00, 0x34, 0x00, 115, 2])
        },
    )
    assert discovery.homekit_gsn(full) == 52
    assert discovery.homekit_gsn(REMOTE) is None  # too short to carry one
    assert discovery.homekit_gsn(NOT_HOMEKIT) is None
