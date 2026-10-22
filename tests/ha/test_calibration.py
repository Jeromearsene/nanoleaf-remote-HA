"""Calibration session of the Home Assistant integration (no hardware)."""

from __future__ import annotations

import pytest

pytest.importorskip("homeassistant")

from custom_components.nanoleaf_remote.calibration import (
    CalibrationSession,  # noqa: E402
)


def test_full_run_builds_the_table() -> None:
    # The user's faces 1..12 are reported at these 0-based positions.
    positions = [3, 4, 5, 6, 7, 8, 9, 10, 11, 0, 1, 2]
    session = CalibrationSession()
    for position in positions:
        assert not session.done
        session.record(position)
    assert session.done
    table, notes = session.table()
    assert table == (10, 11, 12, 1, 2, 3, 4, 5, 6, 7, 8, 9)
    assert not notes


def test_a_reused_position_is_rejected() -> None:
    session = CalibrationSession()
    session.record(5)
    with pytest.raises(ValueError):
        session.record(5)
    assert session.face == 2  # still waiting for face 2
