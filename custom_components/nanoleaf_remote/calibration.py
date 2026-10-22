"""Face calibration run from the Home Assistant options dialog.

The user turns the Remote onto each face in turn (their own numbering: they
pick which face is 1, then follow a consistent order). For each face we note
which switch position the Remote reported, then build the numbering table.
"""

from __future__ import annotations

from .hapble import facemap


class CalibrationSession:
    """Collects (face, detected position) pairs, one face at a time."""

    def __init__(self, face_count: int = facemap.FACE_COUNT) -> None:
        self.face_count = face_count
        self.face = 1
        self.results: list[tuple[int, int]] = []

    @property
    def done(self) -> bool:
        return self.face > self.face_count

    def record(self, position_index: int) -> None:
        """Record the 0-based position detected for the current face.

        Raises ValueError when that position was already assigned to another
        face (the Remote was probably not turned).
        """
        detected = position_index + 1
        if any(seen == detected for _, seen in self.results):
            raise ValueError("position already used")
        self.results.append((self.face, detected))
        self.face += 1

    def table(self) -> tuple[tuple[int, ...] | None, list[str]]:
        return facemap.suggest_face_map(self.results)
