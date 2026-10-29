# Changelog

All notable changes to this project are documented here. Format loosely
inspired by [Keep a Changelog](https://keepachangelog.com/).

## [0.2.1] — 2026-10-29

### Patch changes

- Battery saving mode: fix "ChaCha20-Poly1305 tag invalid" right after subscribing to the Remote's events. The Remote can deliver a response twice (as an indication and by read); the encrypted session now resynchronises its counter instead of failing.

## [0.2.0] — 2026-10-28

### Minor changes

- Experimental battery saving mode (Configure): Home Assistant listens to the Remote's Bluetooth advertisements and connects only when it is turned, instead of polling it every 1.5 s. Off by default. Saving the face table no longer drops other options.

### Patch changes

- New integration icon: a dodecahedron seen face-on, like the real Remote.

## [0.1.0] — 2026-10-22

Initial public version. Everything below was built and tested — against a
real Nanoleaf Remote unless noted otherwise — in a single, heavily
iterative reverse-engineering effort; see `docs/hapble.md` for the full story of
each phase, including the dead ends and what confirmed each fix.

### Added
- Home Assistant (HACS) integration in `custom_components/nanoleaf_remote/`:
  Bluetooth discovery and UI pairing flow, an Event entity (`face_1` …
  `face_12`), reconnection with backoff, per-remote events and availability.
  It uses Home Assistant's Bluetooth stack (`bleak-retry-connector`) and a
  vendored copy of `hapble` kept in sync by `scripts/sync_vendored.py`.
  Pairs with the setup code or reuses an existing `pairing.json`.
  Validated end to end on a real Remote from Home Assistant.
- hassfest and HACS validation workflow, a release workflow that checks the
  tag against the integration version, Dependabot, CODEOWNERS, and diagnostics
  with the pairing keys redacted.
- Configurable face numbering table (`FACE_MAP`, and the Configure dialog in
  Home Assistant), computed by `poetry run calibrate` from the faces you test,
  or by a guided calibration in the Configure dialog of the integration.
- BLE transport and HAP-BLE PDU framing on top of `bleak`, including
  request/response fragmentation across multiple GATT reads.
- Pair-Setup (SRP-6a + Ed25519), verified against the official HAP
  specification's published SRP test vector, and end-to-end against a
  simulated accessory before real hardware.
- Pair-Verify (X25519 + Ed25519), same verification approach.
- Encrypted BLE session (ChaCha20-Poly1305) for ordinary characteristic
  reads/writes after pairing.
- Discovery of, and reading from, all instances of the
  `ProgrammableSwitchEvent` characteristic (one per Remote face).
- Hybrid GATT-indication + polling listener, working around the
  accessory's aggressive idle-disconnect behavior.
- `tools/calibrate.py`: interactive face-by-face verification tool.
- `tools/bridge.py`: long-running service publishing rotation events to MQTT,
  with Home Assistant MQTT-discovery support and automatic BLE
  reconnection.

### Fixed (real-hardware debugging highlights)
- Pair-Setup password must be the full dashed setup code
  (`"123-45-678"`), not the bare 8 digits — confirmed by multiple
  independent sources after a real pairing attempt failed with a correct
  code.
- PDU-level response fragmentation (`continuation` bit) had to be
  implemented from scratch — no reference implementation found handled
  it either.
- A concurrency bug (two coroutines writing/reading the same GATT
  connection at once, as happens once the bridge combines polling with
  indication callbacks) could let one request's response be consumed by
  another; fixed with a per-connection lock, verified by a dedicated test
  that first reproduces the interleaving without the lock.
