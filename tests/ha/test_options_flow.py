"""Options dialog (face calibration) driven with a fake Remote."""

from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace

import pytest

pytest.importorskip("homeassistant")

from custom_components.nanoleaf_remote import config_flow  # noqa: E402


class FakeRuntime:
    connected = True
    power_saving = False
    last_position = None
    suppress_events_until = 0.0


def _flow(runtime, options=None):
    entry = SimpleNamespace(options=options or {}, runtime_data=runtime)
    flow = config_flow.NanoleafOptionsFlow()
    flow.flow_id = "test"
    flow.handler = "nanoleaf_remote"
    flow.__class__.config_entry = property(lambda self: entry)
    return flow


def test_menu_offers_calibration_and_manual_table() -> None:
    result = asyncio.run(_flow(FakeRuntime()).async_step_init())
    assert result["type"] == "menu"
    assert result["menu_options"] == ["calibrate", "manual", "power_saving"]


def test_calibration_saves_the_table() -> None:
    runtime = FakeRuntime()
    flow = _flow(runtime)
    positions = [3, 4, 5, 6, 7, 8, 9, 10, 11, 0, 1, 2]

    async def run():
        result = await flow.async_step_calibrate()
        assert result["step_id"] == "calibrate_face"
        assert result["description_placeholders"] == {"face": "1", "total": "12"}
        # Submitting without turning the Remote is reported.
        result = await flow.async_step_calibrate_face({})
        assert result["errors"] == {"base": "no_rotation"}
        for position in positions:
            await asyncio.sleep(0.01)
            runtime.last_position = (position, time.monotonic())
            result = await flow.async_step_calibrate_face({})
        return result

    result = asyncio.run(run())
    assert result["type"] == "create_entry"
    assert result["data"] == {"face_map": "10,11,12,1,2,3,4,5,6,7,8,9"}
    assert runtime.suppress_events_until == 0.0


def test_reusing_a_position_is_reported() -> None:
    runtime = FakeRuntime()
    flow = _flow(runtime)

    async def run():
        await flow.async_step_calibrate()
        for _ in range(2):
            await asyncio.sleep(0.01)
            runtime.last_position = (5, time.monotonic())
            result = await flow.async_step_calibrate_face({})
        return result

    assert asyncio.run(run())["errors"] == {"base": "position_reused"}


def test_calibration_needs_a_connected_remote() -> None:
    runtime = FakeRuntime()
    runtime.connected = False
    result = asyncio.run(_flow(runtime).async_step_calibrate())
    assert result["type"] == "abort"
    assert result["reason"] == "not_connected"


def test_invalid_pasted_table_is_rejected() -> None:
    result = asyncio.run(_flow(FakeRuntime()).async_step_manual({"face_map": "1,2,3"}))
    assert result["errors"] == {"base": "invalid_face_map"}


def test_calibration_works_without_a_connection_in_battery_saving_mode() -> None:
    runtime = FakeRuntime()
    runtime.connected = False
    runtime.power_saving = True
    result = asyncio.run(_flow(runtime).async_step_calibrate())
    assert result["type"] == "form"
    assert result["step_id"] == "calibrate_face"


def test_battery_saving_option_is_saved_and_keeps_the_face_table() -> None:
    flow = _flow(FakeRuntime(), options={"face_map": "2,1,3,4,5,6,7,8,9,10,11,12"})
    form = asyncio.run(flow.async_step_power_saving())
    assert form["type"] == "form"
    result = asyncio.run(flow.async_step_power_saving({"power_saving": True}))
    assert result["data"] == {
        "face_map": "2,1,3,4,5,6,7,8,9,10,11,12",
        "power_saving": True,
    }


def test_saving_a_face_table_keeps_the_battery_saving_option() -> None:
    flow = _flow(FakeRuntime(), options={"power_saving": True})
    result = asyncio.run(
        flow.async_step_manual({"face_map": "2,1,3,4,5,6,7,8,9,10,11,12"})
    )
    assert result["data"]["power_saving"] is True
