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
poetry run srp-vector          # SRP implementation vs. Apple's official test vector
poetry run pairing-fake        # full Pair-Setup against a simulated accessory
poetry run verify-fake         # full Pair-Verify against a simulated accessory
```

These three `poetry run` commands are exactly what CI runs on every push
and pull request — they need no real Bluetooth hardware. The `phaseN`,
`calibrate`, and `bridge` commands do need a real Nanoleaf Remote and
can't be exercised in CI; if you have one and are touching code they
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
