"""One session of the listener, with a fake Remote (no hardware)."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

pytest.importorskip("homeassistant")

from custom_components.nanoleaf_remote import NanoleafRuntime  # noqa: E402


class FakeChar:
    def __init__(self, values):
        self.values = list(values)

    async def read_value(self) -> bytes:
        value = self.values.pop(0) if len(self.values) > 1 else self.values[0]
        if isinstance(value, BaseException):
            raise value
        if value == "hang":
            await asyncio.sleep(3600)
        return value


class FakeClient:
    is_connected = True

    async def disconnect(self) -> None:
        self.is_connected = False


def make_runtime(power_saving: bool, chars):
    entry = SimpleNamespace(
        entry_id="e1",
        title="Remote",
        data={"address": "AA:BB:CC:DD:EE:FF", "pairing": {}},
        options={"power_saving": power_saving},
    )
    pairing = SimpleNamespace(accessory_pairing_id="D6:BD:09:C0:32:1D")
    events: list[tuple] = []
    patches = [
        patch("custom_components.nanoleaf_remote.decode_pairing", return_value=pairing),
        patch(
            "custom_components.nanoleaf_remote.bluetooth.async_ble_device_from_address",
            return_value=object(),
        ),
        patch(
            "custom_components.nanoleaf_remote.establish_connection",
            AsyncMock(return_value=FakeClient()),
        ),
        patch(
            "custom_components.nanoleaf_remote.pair_verify.pair_verify",
            AsyncMock(
                return_value=SimpleNamespace(read_key=bytes(32), write_key=bytes(32))
            ),
        ),
        patch(
            "custom_components.nanoleaf_remote.async_dispatcher_send",
            lambda hass, signal, *args: events.append(args) if args else None,
        ),
    ]
    accessory = SimpleNamespace(
        pair_verify_characteristic=lambda: object(),
        programmable_switch_event_characteristics=lambda session: chars,
        subscribe_switch_events=AsyncMock(return_value=len(chars)),
    )
    patches.append(
        patch(
            "custom_components.nanoleaf_remote.HapBleAccessory",
            lambda device, client: accessory,
        )
    )
    for p in patches:
        p.start()
    runtime = NanoleafRuntime(SimpleNamespace(), entry)
    return runtime, events, patches


@pytest.fixture(autouse=True)
def _stop_patches():
    yield
    patch.stopall()


def run_session(runtime, patches):
    asyncio.run(runtime._session())


def fast_timings(monkeypatch):
    monkeypatch.setattr("custom_components.nanoleaf_remote.ACTIVE_WINDOW", 0.2)
    monkeypatch.setattr("custom_components.nanoleaf_remote.POLL_INTERVAL", 0.05)
    monkeypatch.setattr("custom_components.nanoleaf_remote.READ_TIMEOUT", 0.2)


def test_event_is_dispatched_then_the_idle_remote_is_released(monkeypatch) -> None:
    fast_timings(monkeypatch)
    chars = [FakeChar([b"null"]), FakeChar([b"\x00", b"null"]), FakeChar([b"null"])]
    runtime, events, patches = make_runtime(True, chars)
    run_session(runtime, patches)  # returns by itself once idle
    assert events == [("face_2", {"face": 2})]


def test_a_dropped_connection_after_a_pass_is_not_a_failure(monkeypatch) -> None:
    fast_timings(monkeypatch)
    chars = [FakeChar([b"null", OSError("link lost")])]
    runtime, _events, patches = make_runtime(True, chars)
    run_session(runtime, patches)  # no exception


def test_a_hung_read_times_out_instead_of_blocking(monkeypatch) -> None:
    fast_timings(monkeypatch)
    chars = [FakeChar(["hang"])]
    runtime, _events, patches = make_runtime(True, chars)
    with pytest.raises(TimeoutError):
        run_session(runtime, patches)  # first pass: a real failure


def test_a_drop_in_permanent_mode_is_still_an_error(monkeypatch) -> None:
    fast_timings(monkeypatch)
    chars = [FakeChar([b"null", OSError("link lost")])]
    runtime, _events, patches = make_runtime(False, chars)
    with pytest.raises(OSError):
        run_session(runtime, patches)
