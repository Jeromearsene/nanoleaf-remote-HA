"""When a change of the advertised state counter means "connect now"."""

from __future__ import annotations

import pytest

pytest.importorskip("homeassistant")

from custom_components.nanoleaf_remote.gsn import GsnWatcher  # noqa: E402


def test_first_advertisement_triggers_a_session() -> None:
    watcher = GsnWatcher(baseline_window=6)
    assert watcher.observe(52, now=0) is True  # reference unknown: sync once


def test_same_counter_does_nothing_and_a_change_triggers() -> None:
    watcher = GsnWatcher(baseline_window=6)
    watcher.observe(52, now=0)
    assert watcher.observe(52, now=1) is False
    assert watcher.observe(53, now=2) is True
    assert watcher.observe(53, now=3) is False


def test_counter_rollover_is_a_change() -> None:
    watcher = GsnWatcher(baseline_window=6)
    watcher.observe(65535, now=0)
    assert watcher.observe(1, now=1) is True


def test_a_change_right_after_a_session_is_absorbed() -> None:
    watcher = GsnWatcher(baseline_window=6)
    watcher.observe(52, now=0)
    watcher.session_ended(now=10)
    # The session itself moved the counter: no new session...
    assert watcher.observe(53, now=12) is False
    # ... and 53 is now the reference.
    assert watcher.observe(53, now=30) is False
    assert watcher.observe(54, now=31) is True


def test_change_after_the_window_with_no_advertisement_in_it_triggers() -> None:
    watcher = GsnWatcher(baseline_window=6)
    watcher.observe(52, now=0)
    watcher.session_ended(now=10)
    # Nothing heard for a while, then the Remote is turned: counter moved.
    assert watcher.observe(54, now=100) is True
