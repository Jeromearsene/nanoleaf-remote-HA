# Security Policy

## Scope and disclaimer

`hapble` is an independent, reverse-engineered implementation of the
HomeKit Accessory Protocol (HAP) over Bluetooth LE. It is **not affiliated
with, endorsed by, or supported by Apple Inc. or Nanoleaf**. It was built
by cross-referencing the publicly available non-commercial HAP
specification and several independent open-source implementations, and by
testing against one specific accessory (a Nanoleaf Remote). It is provided
"as is", with no warranty of any kind — see `LICENSE`.

This project implements real cryptography (SRP-6a, Ed25519, X25519,
ChaCha20-Poly1305) to interoperate with a real security protocol. It has
**not** received an independent security audit. Treat it accordingly: fine
for a personal home-automation project, not something to build a
safety-critical or otherwise high-stakes system on.

## Sensitive data produced by this project

Running `phase2` (Pair-Setup) creates a `pairing.json` file containing:
- this controller's long-term Ed25519 **private** key,
- the paired accessory's long-term public key and identifier.

This file plays the same role as a password: anyone who obtains it can act
as your paired controller (subject to whatever the specific accessory
allows a paired controller to do). It is already excluded via `.gitignore`
— never commit it, attach it to an issue, or otherwise share it. If you
paste terminal output while reporting an issue, double-check it doesn't
contain the contents of `pairing.json` or your 8-digit setup code.

## Sensitive data stored by the Home Assistant integration

The integration stores the same pairing material (controller private key,
accessory public key and identifiers) inside its config entry. Home
Assistant keeps config entries as **unencrypted JSON** in `.storage/` in
your configuration directory, so treat that directory, and any Home
Assistant backup that contains it, like a password. The 8-digit setup code
is used once to pair and is never stored or logged. If you suspect the
material leaked, remove the Remote from Home Assistant, factory-reset it
and pair it again.

## Reporting a vulnerability

If you find an issue in the cryptographic implementation itself (for
example, a flaw in the SRP-6a proof construction, the Pair-Verify
transcript, or the ChaCha20-Poly1305 framing that could let an
unauthenticated party read events, impersonate a controller, or impersonate
an accessory), please report it privately first, using GitHub's "Report a
vulnerability" feature under this repository's Security tab, rather than
opening a public issue. This gives time to publish a fix (and update the
relevant fake-accessory regression test) before the details are public.

For anything else — a bug, a real-hardware discrepancy, a missing feature
— a regular public issue is the right place; see `CONTRIBUTING.md`.
