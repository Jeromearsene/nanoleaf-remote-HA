"""Changesets for this repo: one small file per change, version chosen by hand.

Same idea as `@changesets/cli`, in plain Python (no Node needed here).

    python scripts/changeset.py new --bump minor -m "Add X"   # write a changeset
    python scripts/changeset.py status                         # what would ship
    python scripts/changeset.py check [--base origin/main]     # CI guard
    python scripts/changeset.py version                        # cut a release
    python scripts/changeset.py notes 0.2.0                    # release notes

A changeset is `.changeset/<name>.md`:

    ---
    bump: minor
    ---

    Add a face calibration step to the Configure dialog.

`version` applies the highest pending bump (major > minor > patch) to
`manifest.json` and `pyproject.toml`, writes the descriptions into
`CHANGELOG.md`, and deletes the consumed files.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CHANGESET_DIR = ROOT / ".changeset"
MANIFEST = ROOT / "custom_components/nanoleaf_remote/manifest.json"
PYPROJECT = ROOT / "pyproject.toml"
CHANGELOG = ROOT / "CHANGELOG.md"

BUMPS = ("patch", "minor", "major")
# Changes to these paths reach users, so a pull request touching them needs a
# changeset (or the `no-changeset` label). Tests, docs, CI and tools do not.
USER_FACING = ("custom_components/", "hapble/")
CHANGELOG_HEADING = re.compile(r"^## \[(?P<version>[^\]]+)\]", re.M)
VERSION_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")


class ChangesetError(Exception):
    """A changeset file or the repo state is not usable."""


@dataclass(frozen=True)
class Changeset:
    name: str
    bump: str
    summary: str


def parse_changeset(name: str, text: str) -> Changeset:
    """Parse one changeset file; raise ChangesetError if it is malformed."""
    match = re.match(r"\A---\n(.*?)\n---\n(.*)\Z", text.replace("\r\n", "\n"), re.S)
    if not match:
        raise ChangesetError(f"{name}: expected a '---' front matter block")
    front, body = match.groups()
    fields = dict(
        (key.strip(), value.strip())
        for key, _, value in (line.partition(":") for line in front.splitlines())
        if key.strip()
    )
    bump = fields.get("bump")
    if bump not in BUMPS:
        raise ChangesetError(
            f"{name}: 'bump' must be one of {', '.join(BUMPS)} (got {bump!r})"
        )
    summary = body.strip()
    if not summary:
        raise ChangesetError(f"{name}: the description is empty")
    return Changeset(name=name, bump=bump, summary=summary)


def read_changesets(directory: Path = CHANGESET_DIR) -> list[Changeset]:
    """All pending changesets, oldest name first (README.md is not one)."""
    if not directory.is_dir():
        return []
    return [
        parse_changeset(path.name, path.read_text(encoding="utf-8"))
        for path in sorted(directory.glob("*.md"))
        if path.name.lower() != "readme.md"
    ]


def bump_version(version: str, bump: str) -> str:
    match = VERSION_RE.match(version)
    if not match:
        raise ChangesetError(f"not a plain X.Y.Z version: {version!r}")
    major, minor, patch = map(int, match.groups())
    if bump == "major":
        return f"{major + 1}.0.0"
    if bump == "minor":
        return f"{major}.{minor + 1}.0"
    return f"{major}.{minor}.{patch + 1}"


def highest_bump(changesets: list[Changeset]) -> str:
    return max((c.bump for c in changesets), key=BUMPS.index)


def render_section(version: str, date: str, changesets: list[Changeset]) -> str:
    """CHANGELOG section: one list per bump level, biggest first."""
    lines = [f"## [{version}] — {date}", ""]
    for bump in reversed(BUMPS):
        group = [c for c in changesets if c.bump == bump]
        if not group:
            continue
        lines += [f"### {bump.capitalize()} changes", ""]
        for change in group:
            first, *rest = change.summary.splitlines()
            lines.append(f"- {first}")
            lines += [f"  {line}" if line.strip() else "" for line in rest]
        lines.append("")
    return "\n".join(lines)


def insert_section(changelog: str, section: str) -> str:
    """Put the new section above the most recent release."""
    match = CHANGELOG_HEADING.search(changelog)
    if not match:
        return changelog.rstrip("\n") + "\n\n" + section.rstrip("\n") + "\n"
    return changelog[: match.start()] + section + "\n" + changelog[match.start() :]


def release_notes(changelog: str, version: str) -> str:
    """The body of one version's CHANGELOG section (without its heading)."""
    matches = list(CHANGELOG_HEADING.finditer(changelog))
    for i, match in enumerate(matches):
        if match.group("version") == version:
            end = matches[i + 1].start() if i + 1 < len(matches) else len(changelog)
            body = changelog[match.end() : end]
            return body.split("\n", 1)[1].strip() + "\n" if "\n" in body else ""
    raise ChangesetError(f"CHANGELOG.md has no section for {version}")


def current_version() -> str:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))["version"]


def write_version(version: str) -> None:
    manifest = MANIFEST.read_text(encoding="utf-8")
    MANIFEST.write_text(
        re.sub(r'("version"\s*:\s*)"[^"]+"', rf'\1"{version}"', manifest, count=1),
        encoding="utf-8",
    )
    pyproject = PYPROJECT.read_text(encoding="utf-8")
    PYPROJECT.write_text(
        re.sub(
            r'^(version\s*=\s*)"[^"]+"',
            rf'\1"{version}"',
            pyproject,
            count=1,
            flags=re.M,
        ),
        encoding="utf-8",
    )


def slugify(text: str) -> str:
    words = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-").split("-")
    return "-".join(words[:6]) or "change"


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=ROOT, check=True, capture_output=True, text=True
    ).stdout


# --- commands ----------------------------------------------------------------


def cmd_new(args: argparse.Namespace) -> int:
    summary = (args.message or "").strip()
    if not summary:
        print("Describe the change with -m/--message.", file=sys.stderr)
        return 2
    CHANGESET_DIR.mkdir(exist_ok=True)
    path = CHANGESET_DIR / f"{args.name or slugify(summary)}.md"
    if path.exists():
        print(f"{path.relative_to(ROOT)} already exists.", file=sys.stderr)
        return 2
    path.write_text(f"---\nbump: {args.bump}\n---\n\n{summary}\n", encoding="utf-8")
    print(f"Wrote {path.relative_to(ROOT)}")
    return 0


def cmd_status(_: argparse.Namespace) -> int:
    changesets = read_changesets()
    if not changesets:
        print("No pending changesets: nothing to release.")
        return 0
    now = current_version()
    bump = highest_bump(changesets)
    print(
        f"{len(changesets)} pending changeset(s); {now} -> {bump_version(now, bump)} ({bump})"
    )
    for change in changesets:
        print(f"  [{change.bump}] {change.summary.splitlines()[0]}")
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    read_changesets()  # raises on a malformed file
    if not args.base:
        print("Changeset files are valid.")
        return 0
    base = git("merge-base", args.base, "HEAD").strip()
    changed = git("diff", "--name-only", f"{base}...HEAD").splitlines()
    touched = [p for p in changed if p.startswith(USER_FACING)]
    # A changeset added by the PR, or consumed by it (a release PR runs
    # `version`, which deletes them and bumps the version).
    added = [
        p
        for p in changed
        if p.startswith(".changeset/")
        and p.endswith(".md")
        and p != ".changeset/README.md"
    ]
    if touched and not added:
        print(
            "This change touches code users run "
            f"({', '.join(touched[:3])}{'…' if len(touched) > 3 else ''}) "
            "but adds no changeset.\n"
            'Run: python scripts/changeset.py new --bump patch|minor|major -m "..."\n'
            "(or add the `no-changeset` label if it should not appear in the changelog)",
            file=sys.stderr,
        )
        return 1
    print("Changeset check passed.")
    return 0


def cmd_version(_: argparse.Namespace) -> int:
    changesets = read_changesets()
    if not changesets:
        print("No pending changesets: nothing to release.", file=sys.stderr)
        return 1
    before = current_version()
    after = bump_version(before, highest_bump(changesets))
    section = render_section(after, dt.date.today().isoformat(), changesets)
    CHANGELOG.write_text(
        insert_section(CHANGELOG.read_text(encoding="utf-8"), section), encoding="utf-8"
    )
    write_version(after)
    for change in changesets:
        (CHANGESET_DIR / change.name).unlink()
    print(f"{before} -> {after}")
    return 0


def cmd_notes(args: argparse.Namespace) -> int:
    version = args.version.removeprefix("v")
    sys.stdout.write(release_notes(CHANGELOG.read_text(encoding="utf-8"), version))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)

    new = sub.add_parser("new", help="write a changeset file")
    new.add_argument("--bump", choices=BUMPS, required=True)
    new.add_argument("-m", "--message", help="what changed, for the changelog")
    new.add_argument("--name", help="file name (default: derived from the message)")
    new.set_defaults(func=cmd_new)

    sub.add_parser(
        "status", help="show pending changesets and the next version"
    ).set_defaults(func=cmd_status)

    check = sub.add_parser(
        "check", help="validate changesets; with --base, require one"
    )
    check.add_argument("--base", help="git ref the pull request will merge into")
    check.set_defaults(func=cmd_check)

    sub.add_parser(
        "version", help="apply pending changesets: bump, changelog, cleanup"
    ).set_defaults(func=cmd_version)

    notes = sub.add_parser("notes", help="print one version's changelog section")
    notes.add_argument("version")
    notes.set_defaults(func=cmd_notes)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except ChangesetError as err:
        print(f"error: {err}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
