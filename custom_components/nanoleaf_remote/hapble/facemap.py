"""Mapping between a switch instance index and the physical face number.

The Remote exposes 12 ProgrammableSwitchEvent characteristics. By default the
face number is simply `index + 1`; if calibration shows another order, a
"face map" (12 distinct numbers) translates each detected position to the
real face number.

A face map is written as 12 comma-separated numbers: the Nth number is the
real face for the Nth detected position. "1,2,3,4,5,6,7,8,9,10,11,12" is the
identity.
"""

from __future__ import annotations

FACE_COUNT = 12
IDENTITY = tuple(range(1, FACE_COUNT + 1))


def parse_face_map(text: str | None) -> tuple[int, ...]:
    """Parse a face map; an empty value means the identity mapping.

    Raises ValueError when it is not a permutation of 1..12.
    """
    if text is None or not text.strip():
        return IDENTITY
    try:
        values = tuple(int(part) for part in text.replace(";", ",").split(","))
    except ValueError as err:
        raise ValueError("a face map only contains numbers") from err
    if sorted(values) != list(IDENTITY):
        raise ValueError(f"a face map must use each number from 1 to {FACE_COUNT} once")
    return values


def format_face_map(face_map: tuple[int, ...]) -> str:
    return ",".join(str(value) for value in face_map)


def face_for_index(face_map: tuple[int, ...], index: int) -> int:
    """Real face number for a detected 0-based instance index."""
    return face_map[index]


def suggest_face_map(
    results: list[tuple[int, int]],
) -> tuple[tuple[int, ...] | None, list[str]]:
    """Build a face map from calibration results.

    `results` holds (face the user turned to, face detected as index + 1).
    Returns (map or None if it cannot be built yet, human-readable notes).
    """
    notes: list[str] = []
    mapping: dict[int, int] = {}
    for expected, detected in results:
        if mapping.setdefault(detected, expected) != expected:
            notes.append(
                f"Position détectée {detected} : plusieurs faces différentes "
                f"({mapping[detected]} et {expected}), essai incohérent."
            )
    if notes:
        return None, notes
    missing_detected = [n for n in IDENTITY if n not in mapping]
    if missing_detected:
        notes.append(
            "Positions détectées pas encore vues : "
            + ", ".join(str(n) for n in missing_detected)
            + " (testez toutes les faces pour obtenir la table complète)."
        )
        return None, notes
    values = tuple(mapping[n] for n in IDENTITY)
    if sorted(values) != list(IDENTITY):
        notes.append(
            "Deux positions détectées donnent la même face : refaites les essais."
        )
        return None, notes
    return values, notes
