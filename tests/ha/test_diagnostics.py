"""Diagnostics must never expose the pairing keys (no hardware)."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

pytest.importorskip("homeassistant")

from custom_components.nanoleaf_remote import diagnostics  # noqa: E402


def test_pairing_keys_and_address_are_redacted() -> None:
    entry = SimpleNamespace(
        title="Nanoleaf Remote",
        data={
            "address": "FA:2E:63:20:7F:BE",
            "pairing": {"controller_ltsk": "SECRET-PRIVATE-KEY"},
        },
        options={"face_map": "1,2,3,4,5,6,7,8,9,10,11,12"},
        runtime_data=SimpleNamespace(
            connected=True, last_position=(4, 1.0), battery_level=72
        ),
    )
    result = asyncio.run(diagnostics.async_get_config_entry_diagnostics(None, entry))
    text = str(result)
    assert "SECRET-PRIVATE-KEY" not in text
    assert "FA:2E:63:20:7F:BE" not in text
    assert result["entry"]["options"] == {"face_map": "1,2,3,4,5,6,7,8,9,10,11,12"}
    assert result["runtime"] == {
        "connected": True,
        "last_position": 4,
        "battery_level": 72,
    }
