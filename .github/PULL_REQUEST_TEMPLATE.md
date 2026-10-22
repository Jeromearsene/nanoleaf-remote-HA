## What does this change?

## Why?

## How was this tested?

- [ ] `poetry run ruff check .` and `poetry run ruff format --check .` pass
- [ ] `poetry run pytest` still passes (it runs in CI automatically, but is
      quick to check locally too), and `python scripts/sync_vendored.py
      --check` if you touched `hapble/`
- [ ] If this touches protocol/crypto code: tested against a simulated
      accessory (new/updated fake-accessory test included), and — if you
      have one — against real hardware. Please describe what you saw.

## Anything reviewers should pay special attention to?
