"""Hardware-free checks for the face numbering table (hapble.facemap)."""

from __future__ import annotations

from hapble import facemap


def _rejects(text: str) -> bool:
    try:
        facemap.parse_face_map(text)
    except ValueError:
        return True
    return False


def test_face_map() -> None:
    assert facemap.parse_face_map("") == facemap.IDENTITY
    assert facemap.parse_face_map(None) == facemap.IDENTITY
    shifted = facemap.parse_face_map("12,1,2,3,4,5,6,7,8,9,10,11")
    assert facemap.face_for_index(shifted, 0) == 12
    assert facemap.face_for_index(shifted, 11) == 11
    for bad in ("1,2", "a,b", "1,1,2,3,4,5,6,7,8,9,10,11", "0,1,2,3,4,5,6,7,8,9,10,11"):
        assert _rejects(bad), bad

    # Detected position n really is face (n % 12) + 1.
    results = [((n % 12) + 1, n) for n in range(1, 13)]
    suggested, notes = facemap.suggest_face_map(results)
    assert suggested == (2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 1) and not notes
    assert facemap.parse_face_map(facemap.format_face_map(suggested)) == suggested

    partial, notes = facemap.suggest_face_map(results[:3])
    assert partial is None and notes
    conflict, notes = facemap.suggest_face_map([(2, 1), (3, 1)])
    assert conflict is None and notes
