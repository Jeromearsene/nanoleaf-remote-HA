## What does this change?

## Why?

## How was this tested?

- [ ] `poetry run ruff check .` and `poetry run ruff format --check .` pass
- [ ] `poetry run srp-vector`, `poetry run pairing-fake`, and
      `poetry run verify-fake` still pass (these run in CI automatically,
      but are quick to check locally too)
- [ ] If this touches protocol/crypto code: tested against a simulated
      accessory (new/updated fake-accessory test included), and — if you
      have one — against real hardware. Please describe what you saw.

## Anything reviewers should pay special attention to?
