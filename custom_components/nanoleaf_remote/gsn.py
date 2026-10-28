"""Decide, from advertisements, when the Remote has something to report.

A HomeKit BLE accessory advertises a Global State Number (GSN). The Remote
increments it when a rotation happens while no controller is connected (and
once per connection, not once per rotation), so a change means "connect and
read". A session itself can also move the GSN: for a few seconds after one
ends, advertisements only update the reference value.
"""

from __future__ import annotations


class GsnWatcher:
    """Turn the stream of advertised GSNs into "connect now" decisions."""

    def __init__(self, baseline_window: float) -> None:
        self.last: int | None = None
        self._baseline_window = baseline_window
        self._baseline_until = 0.0

    def observe(self, gsn: int, now: float) -> bool:
        """Return True if this advertisement means a session should start."""
        if now < self._baseline_until:
            self.last = gsn
            return False
        changed = self.last is None or gsn != self.last
        self.last = gsn
        return changed

    def session_ended(self, now: float) -> None:
        """Start the window in which the session's own GSN change is absorbed."""
        self._baseline_until = now + self._baseline_window
