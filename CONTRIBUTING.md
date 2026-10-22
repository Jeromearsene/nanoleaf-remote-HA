# Contributing to hapble

Thanks for your interest in this project! It started as a personal
reverse-engineering effort to control a Nanoleaf Remote from Home Assistant
without depending on Apple Home, and grew into a from-scratch HAP-BLE
(HomeKit Accessory Protocol over Bluetooth LE) client — the first one, as
far as we know, built on `bleak` instead of `bluepy`/BlueZ, so it runs on
Windows and macOS as well as Linux.

Issues and pull requests are welcome, in English or in French.

## Before you start

- **Read `README.md`** (and its French counterpart `README.fr.md`) for the
  integration, and `docs/hapble.md` for the protocol write-up. Its
  "Project status" section documents exactly what has been verified against
  real hardware, what's only validated against simulated accessories, and
  what remains uncertain. Please don't assume a phase is solid just because
  the code exists; check its status first.
- **Hardware-dependent changes are hard to verify remotely.** Most of this
  project was built through an iterative, evidence-driven process: form a
  hypothesis from a primary source (the official HAP specification when
  available, or a cross-referenced independent implementation otherwise),
  write an automated test against a simulated accessory, *then* test
  against real hardware, and adjust based on what actually happens. If
  you're proposing a protocol-level change, please follow the same
  discipline — cite a source, and add or update the relevant fake-accessory
  test in the same pull request.

## Development setup

This project uses [Poetry](https://python-poetry.org/) for dependencies,
the virtual environment, and the scripts listed in `pyproject.toml`.

```bash
poetry install
```

Install the pre-commit hooks (runs the linter automatically before each
commit):

```bash
poetry run pre-commit install
```

## Running the checks locally

```bash
poetry run ruff check .        # lint
poetry run ruff format --check .   # formatting
poetry run pytest                              # protocol tests, no hardware needed
python scripts/sync_vendored.py --check        # vendored hapble == hapble/
```

The Home Assistant integration tests (`tests/ha`) need Home Assistant
installed (Python 3.13): `pip install homeassistant bleak-retry-connector`
plus its Bluetooth dependencies, as in `.github/workflows/ci.yml`, then
`python -m pytest tests/ha`. They are skipped when Home Assistant is absent.

Everything above runs in CI on every push and pull request. If you change
`hapble/`, run `python scripts/sync_vendored.py` to refresh the copy
shipped inside the integration (HACS only installs that folder). The
`phaseN`, `calibrate`, and `bridge` commands (in `tools/`) do need a real
Nanoleaf Remote and can't be exercised in CI; if you have one and are touching code they
depend on, please mention in your PR description what you tested against
real hardware.

## Reporting a real-hardware discrepancy

If a script behaves differently against your accessory than what's
documented in the README, that's valuable signal, not just a bug report —
please open an issue with:
- which command you ran, and its full output (redact your pairing code
  and the contents of `pairing.json` if you paste it — see `SECURITY.md`);
- your OS and Python version;
- if relevant, `BLEAK_LOGGING=1` output for the same run.

## Code style

- `ruff` (linting and formatting) is the source of truth — run it before
  pushing, or let the pre-commit hook do it for you.
- Comments and docstrings in the core protocol modules (`hapble/`) are
  currently in French, reflecting how the project was originally
  developed and documented; new contributions may add English comments
  alongside rather than translating existing ones wholesale. Identifiers
  (function/variable/class names) are in English throughout.
- Prefer small, focused pull requests over large rewrites, especially for
  anything touching the cryptography or framing code — those modules are
  deliberately conservative and heavily commented with their sources.

## Security

Please see `SECURITY.md` before reporting anything sensitive (e.g. a flaw
that would let someone impersonate a paired controller).

## Changesets and releasing

The version is chosen by hand, change by change, with *changesets* (same idea
as `@changesets/cli`, in plain Python: `scripts/changeset.py`).

**In every pull request** that changes what users get (`custom_components/` or
`hapble/`), add a changeset saying how big the change is and what the
changelog should say:

```sh
python scripts/changeset.py new --bump patch|minor|major -m "What changed, for users"
```

`patch` is a fix, `minor` a backwards-compatible feature, `major` a breaking
change. Commit the generated `.changeset/*.md` file with the PR. The
`Changeset` check fails if it is missing; add the `no-changeset` label for an
internal change that should not be in the changelog. Docs, tests, CI and
`tools/` need none.

**To release** (when you decide, not on every merge):

1. `python scripts/changeset.py status` shows what would ship and the next
   version.
2. On a branch, run `python scripts/changeset.py version`: it applies the
   highest pending bump to `manifest.json` and `pyproject.toml`, writes the
   `CHANGELOG.md` section and deletes the consumed changesets. Open a PR
   ("Release vX.Y.Z") and merge it.
3. That's it: on the push to `main`, the `Release` workflow sees a version
   without a GitHub release and publishes `vX.Y.Z` (notes = its changelog
   section). HACS uses that release for updates. No manual tag.
