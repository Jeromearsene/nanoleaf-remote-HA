"""The changeset tool: parsing, version arithmetic, changelog output."""

import importlib.util
import sys
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location(
    "changeset", Path(__file__).resolve().parent.parent / "scripts" / "changeset.py"
)
cs = importlib.util.module_from_spec(_spec)
sys.modules["changeset"] = cs  # dataclasses look the module up by name
_spec.loader.exec_module(cs)

CHANGELOG = """# Changelog

Intro.

## [0.1.0] — 2026-10-22

Initial version.
"""


def test_parse_valid_changeset():
    change = cs.parse_changeset("a.md", "---\nbump: minor\n---\n\nAdd X.\n")
    assert (change.bump, change.summary) == ("minor", "Add X.")


@pytest.mark.parametrize(
    "text",
    [
        "no front matter",
        "---\nbump: huge\n---\nText",
        "---\nbump: patch\n---\n\n",
        "---\n---\nText",
    ],
)
def test_parse_rejects_malformed(text):
    with pytest.raises(cs.ChangesetError):
        cs.parse_changeset("a.md", text)


@pytest.mark.parametrize(
    ("bump", "expected"),
    [("patch", "1.2.4"), ("minor", "1.3.0"), ("major", "2.0.0")],
)
def test_bump_version(bump, expected):
    assert cs.bump_version("1.2.3", bump) == expected


def test_highest_bump_wins():
    changes = [cs.Changeset("a", "patch", "x"), cs.Changeset("b", "major", "y")]
    assert cs.highest_bump(changes) == "major"


def test_section_is_grouped_and_inserted_above_latest_release():
    changes = [
        cs.Changeset("a", "patch", "Fix Y."),
        cs.Changeset("b", "minor", "Add X.\nMore detail."),
    ]
    section = cs.render_section("0.2.0", "2026-11-01", changes)
    result = cs.insert_section(CHANGELOG, section)
    assert result.index("## [0.2.0]") < result.index("## [0.1.0]")
    assert result.index("### Minor changes") < result.index("### Patch changes")
    assert "- Add X.\n  More detail." in result


def test_release_notes_extracts_one_section():
    section = cs.render_section(
        "0.2.0", "2026-11-01", [cs.Changeset("a", "patch", "Fix Y.")]
    )
    result = cs.insert_section(CHANGELOG, section)
    assert cs.release_notes(result, "0.2.0").strip() == "### Patch changes\n\n- Fix Y."
    assert cs.release_notes(result, "0.1.0").strip() == "Initial version."
    with pytest.raises(cs.ChangesetError):
        cs.release_notes(result, "9.9.9")
