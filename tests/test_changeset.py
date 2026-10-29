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


def _git(repo, *args):
    import subprocess

    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.com", *args],
        cwd=repo,
        check=True,
        capture_output=True,
    )


def _repo_with_base(tmp_path):
    (tmp_path / "custom_components").mkdir()
    (tmp_path / "custom_components" / "mod.py").write_text("a = 1\n")
    (tmp_path / ".changeset").mkdir()
    (tmp_path / ".changeset" / "README.md").write_text("doc\n")
    (tmp_path / ".changeset" / "old.md").write_text("---\nbump: patch\n---\n\nOld.\n")
    _git(tmp_path, "init", "-q", "-b", "main")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "base")
    _git(tmp_path, "checkout", "-q", "-b", "pr")
    return tmp_path


def test_check_requires_a_changeset_for_user_facing_changes(tmp_path, monkeypatch):
    repo = _repo_with_base(tmp_path)
    monkeypatch.setattr(cs, "ROOT", repo)
    monkeypatch.setattr(cs, "CHANGESET_DIR", repo / ".changeset")
    (repo / "custom_components" / "mod.py").write_text("a = 2\n")
    _git(repo, "commit", "-q", "-am", "change")
    assert cs.main(["check", "--base", "main"]) == 1
    cs.main(["new", "--bump", "patch", "-m", "Fix it", "--name", "fix-it"])
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "changeset")
    assert cs.main(["check", "--base", "main"]) == 0


def test_check_accepts_a_release_pr_that_consumes_changesets(tmp_path, monkeypatch):
    repo = _repo_with_base(tmp_path)
    monkeypatch.setattr(cs, "ROOT", repo)
    monkeypatch.setattr(cs, "CHANGESET_DIR", repo / ".changeset")
    (repo / "custom_components" / "mod.py").write_text("a = 3\n")  # version bump
    (repo / ".changeset" / "old.md").unlink()
    _git(repo, "commit", "-q", "-am", "release")
    assert cs.main(["check", "--base", "main"]) == 0
