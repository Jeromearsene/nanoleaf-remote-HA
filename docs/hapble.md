# hapble — a from-scratch HAP-BLE client for the Nanoleaf Remote

> 📚 This is the technical write-up of the protocol work behind the integration. For installing and using the Home Assistant integration, see the [main README](../README.md).

[![CI](https://github.com/Jeromearsene/nanoleaf-remote-HA/actions/workflows/ci.yml/badge.svg)](https://github.com/Jeromearsene/nanoleaf-remote-HA/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

🇬🇧 English (this document) | 🇫🇷 [Français](hapble.fr.md)

> **Disclaimer**: independent reverse-engineering project, not affiliated
> with Apple or Nanoleaf. Provided as-is, no warranty — see `LICENSE` and
> [`SECURITY.md`](../SECURITY.md).

Goal: speak the HomeKit Accessory Protocol (HAP) over Bluetooth LE
**straight from Windows** (or macOS, or Linux) via [`bleak`](https://github.com/hbldh/bleak),
without depending on `bluepy`/BlueZ — so no Linux requirement, no VM, no
ESPHome proxy.

## Why this project exists

Every existing Python HAP-BLE implementation (`homekit_python`,
`pyhomekit`, and by extension `aiohomekit` — which Home Assistant's own
`homekit_controller` integration uses for BLE) is built on `bluepy`, which
itself depends on **BlueZ via D-Bus**, available on Linux only. `bleak`,
by contrast, is cross-platform (Windows/Linux/macOS). This repository
reuses `pyhomekit`'s protocol logic (its source was read closely while
building this) but with `bleak` as the transport instead of `bluepy` —
as far as we know, the first HAP-BLE client built this way.

## Project status

Everything below was built and verified against a real Nanoleaf Remote,
through an iterative, evidence-driven process: form a hypothesis from a
primary source (ideally the official HAP specification itself, or a
cross-referenced independent implementation otherwise), write an
automated test against a *simulated* accessory to catch logic bugs
cheaply, *then* test against the real device, and adjust based on what
actually happens. Several real bugs were only found this way — see
[`CHANGELOG.md`](../CHANGELOG.md) for the highlights, and the phase-by-phase notes below for
the full story, dead ends included.

### ✅ Phase 1 — Transport & framing

- GATT connection via `bleak`.
- TLV8 encoding/decoding (`tlv8.py`).
- HAP-BLE request/response headers, Control Field, fragmentation
  (`pdu.py`).
- One real, risk-free HAP-BLE request: reading the **Pairing Features**
  characteristic, which is readable without pairing (`transport.py`).

This is the decisive test: if it passes, our understanding of the
protocol (UUIDs, TLV8, PDU framing) is correct against the Remote's real
firmware, *before* investing time in the cryptography.

### ✅ Phase 2 — Pair-Setup (SRP-6a + Ed25519)

- SRP-6a in pure Python (`srp.py`), 3072-bit group (RFC 5054), SHA-512,
  username `"Pair-Setup"`. The `N` constant was verified programmatically
  against the RFC's raw text (a manual-transcription bug was caught and
  fixed this way during development).
- HKDF-SHA512, Ed25519, X25519, ChaCha20-Poly1305 (`crypto_hap.py`), via
  the `cryptography` library.
- Full M1→M6 state machine (`pairing.py`).
- Result persisted (`pairing_store.py`) to `pairing.json`.
- **Verified end-to-end against a pure-Python simulated accessory**
  (`tests/test_pairing_e2e_fake.py`, needs no hardware): the happy path succeeds
  with client/accessory cross-checks, and the error path (wrong code) is
  correctly rejected.
- **PDU-level fragmentation of large responses (`continuation` bit)**:
  message M2 (which carries a 384-byte SRP public key) far exceeds a
  single GATT frame. Neither `pyhomekit` nor any other reference found
  implemented this case (`pyhomekit`'s own author left it as a
  `NotImplementedError`) — so it had to be implemented from scratch: after
  a first GATT read announces a total length, further GATT reads (no new
  write) are issued until that length is assembled. Verified with an
  integration test reproducing exactly the pattern observed against the
  real device (240 bytes received, 1151 announced, assembled over 3
  reads).

**Fix applied after a second real-world failure**: the password fed into
the SRP computation must be the **full code with dashes**
(`"543-97-113"`), not the bare 8 digits (`"54397113"`) — confirmed by 4
independent sources, including `pyhomekit` itself (this project's main
reference throughout), which states it explicitly in its docstring.
`normalize_setup_code()` now produces the canonical `XXX-XX-XXX` form
regardless of the input format.

*(Earlier, inconclusive attempt: minimal vs. 384-byte padding in the
M1/M2 proof formula — kept in `srp.py` out of caution and documented with
an otherwise-reliable source, but it wasn't sufficient on its own.)*

### ✅ Phase 3 — Pair-Verify

- Implemented directly from the **full, official** text of the HAP spec
  (section 5.7), fetched and read in full for this project — no
  guesswork like the back-and-forth that Pair-Setup's SRP proof required.
- Verified end-to-end against a simulated accessory
  (`tests/test_pair_verify_e2e_fake.py`): identical session keys computed
  independently on both sides, and correct rejection of an unexpected
  accessory identifier (protection against a spoofed/different
  accessory).
- **Bonus**: the *official* SRP test vector from the Apple spec (section
  5.5.2) is now a permanent regression test (`tests/test_srp_official_vector.py`)
  — v, A, B, S, K checked exactly against the values Apple itself
  publishes, independent of any hardware. The vectors are reconstructed
  programmatically from the spec's raw text (not hand-typed, out of
  caution after the transcription bug caught earlier on the `N`
  constant).

### ✅ Phase 4 — Encrypted session + reading ProgrammableSwitchEvent

- The encrypted-PDU format was confirmed via a Rust crate dedicated
  specifically to the HAP-BLE transport (not HAP-IP, whose conventions
  differ): each GATT operation encrypts/decrypts one whole HAP-BLE PDU as
  a single ChaCha20-Poly1305 block, no AAD, nonce = 4 zero bytes + a
  64-bit little-endian counter, one counter per direction
  (`ble_session.py`).
- Verified with an integration test simulating a fully encrypted
  accessory: encrypted write, decryption on the simulated "accessory"
  side, encrypted response back, correct decryption and parsing on the
  client side.
- The PDU format itself (control field, TLV8) is unchanged: this layer
  only adds encryption/decryption around what already existed.

**Known limitation, unresolved at this stage**: `ProgrammableSwitchEvent`
characteristics have the GATT `indicate` property (spotted in Phase 1) —
a plain direct read might return nothing if the accessory instead expects
a BLE indication subscription (via the `0x2902` CCCD descriptor), which
wasn't implemented yet. `tools/phase4.py` tries the direct read first
(simpler, reuses everything already built) and documents this point if it
comes back empty.

**Other practical limitation**: the accessory's short connection window
(~1s, see Phase 1) likely doesn't allow reading all 8 instances in one
connection — the script keeps going after a partial failure instead of
giving up.

### ✅ Phase 5 — Hybrid listening (indications + keep-alive polling) — verified against real hardware

Confirmed empirically (Phase 4): **index in the list of 12 instances =
face number − 1**, and the active instance's value reverts to `"null"`
after being read (a transient signal, not persistent state).

**First-attempt diagnosis (subscription only, no polling)**: the CCCD was
confirmed in *indicate* mode on all 12 instances (so not a notify/indicate
mode mismatch), but the accessory dropped the connection after ~5 seconds
of passive listening, before any rotation could be detected — confirming
the Phase 1 hypothesis: this accessory disconnects a connection it deems
idle, and staying quietly subscribed doesn't count as activity in its
eyes.

**Solution verified in real conditions**: a light poll (~1.5s) runs
alongside the indication subscription. Result on a 30-second trial with
several rotations: the connection held for the full duration, **and both
mechanisms each caught one event** — a real GATT indication arrived
(empty payload, confirming the accessory does actively notify but without
the value itself; the re-read triggered in response caught it with
minimal latency), and polling independently caught a second event. The
hybrid system works as intended: fast when the indication comes through,
guaranteed otherwise (worst-case latency ~1.5s).

### ✅ Calibration — interactive face-by-face verification

The "index = face − 1" mapping had only been checked against 2 data
points (Phase 4: faces 2 and 9). `tools/calibrate.py` lets you verify it
explicitly, as many times as you like, before relying on it for real Home
Assistant automations: for each trial, you state which face you're about
to test, then rotate — the script confirms or flags a mismatch, and gives
a final summary (X/Y trials correct, any mismatches listed).

Reuses the same connection logic as Phase 5 (indications + keep-alive
polling); the summary logic (`summarize()`) is tested independently of
any hardware.

### ✅ Phase 6 — MQTT bridge to Home Assistant

Turns the test script (Phase 5) into a long-running service: an
indefinite reconnection loop (instead of stopping after a fixed
duration), and publishing every event to MQTT in Home Assistant's
auto-discovery format ([MQTT Event](https://www.home-assistant.io/integrations/event.mqtt/)
integration) — checked against the official documentation, then tested
against a **real local Mosquitto broker**, with an independent subscriber
simulating Home Assistant to confirm the message format.

- `hapble/mqtt_bridge.py`: builds the discovery payload (topic
  `homeassistant/event/nanoleaf_remote_rotation/config`, 12 `event_types`
  `face_1`...`face_12`, grouped under a "Nanoleaf Remote" device in the
  Home Assistant UI) and the state payload (`{"event_type": "face_N"}`).
- `tools/bridge.py`: an indefinite BLE reconnection loop wrapped around Phase
  5's logic, publishing to MQTT on every detected event (indication or
  polling).
- **Concurrency fix** added at this point: the polling loop and the
  indication-triggered callbacks can now talk to the same connection at
  the same time (which never happened in the earlier, strictly
  sequential test scripts) — a shared lock
  (`HapBleAccessory.request_lock`) serializes exchanges so a response
  can't be read by the wrong request. Verified with a dedicated test:
  without the lock, interleaving does happen (confirming the test is
  meaningful); with the lock, every write is always immediately followed
  by its own read.

Configured via environment variables (`MQTT_HOST`, `MQTT_PORT`,
`MQTT_USERNAME`, `MQTT_PASSWORD` — all optional, defaulting to
`localhost:1883` with no authentication), or a `.env` file at the project
root (see `.env.example`).

**Not yet verified**: behavior over a run of several hours/days (memory
leaks, nonce-counter drift after a very large number of messages,
robustness of a remote MQTT broker across an extended network outage).

## Installation

This project uses [Poetry](https://python-poetry.org/) for the
environment, dependencies, and the scripts you run.

```bash
poetry install
```

This creates a virtual environment in `.venv/` (configured in
`poetry.toml`, so it's visible in the project folder rather than hidden
in Poetry's global cache) and installs `bleak`, `cryptography`,
`aiomqtt`, and `python-dotenv` into it.

Two equivalent ways to run a command inside it:

```bash
poetry run <command>   # one-off command
poetry shell            # or: activate the venv for the whole shell session
```

## Running Phase 1

```bash
poetry run phase1
```

Expected result: the list of the Remote's GATT services/characteristics
(the `00000055-0000-1000-8000-0026bb765291` service should appear in it),
then the value of `Pairing Features`.

To see every exchanged frame in hex (useful when troubleshooting): set
`LOG_LEVEL = logging.DEBUG` near the top of `tools/phase1.py`.

## Running Phase 2 (Pair-Setup)

First, with no hardware, to validate the internal logic:

```bash
poetry run pytest tests/test_pairing_e2e_fake.py
```

Then against the real device (8-digit code required — label under the
Remote or in the Nanoleaf app):

```bash
poetry run phase2
# or directly: poetry run phase2 123-45-678
```

If it fails from a disconnection mid-exchange (the accessory's short
connection window, see Phase 1): just retry — nothing is persisted before
M6 succeeds.

## Running Phase 3 (Pair-Verify)

First, with no hardware:

```bash
poetry run pytest tests/test_pair_verify_e2e_fake.py
```

Then against the real device (needs an existing `pairing.json`, produced
by `phase2` — does NOT ask for the 8-digit code again):

```bash
poetry run phase3
```

Also worth running any time (no hardware needed, checks `srp.py` against
Apple's official test vector):

```bash
poetry run pytest tests/test_srp_official_vector.py
```

## Running Phase 4 (encrypted session + reading an event)

```bash
poetry run phase4
```

Reuses `pairing.json` (Pair-Verify, no code re-entry), then tries reading
each of the 8 `ProgrammableSwitchEvent` instances. Try rotating the
Remote right before/during the run.

## Running Phase 5 (indications, live listening)

```bash
poetry run phase5          # listens for 30s by default
poetry run phase5 60       # or a custom duration, in seconds
```

Rotate the Remote to several different faces during the listening window
to see multiple events come through.

## Running the calibration tool (face-by-face check)

```bash
poetry run calibrate
```

For each trial: type the face number (1-12), then rotate the Remote to
that face. Type `q` to stop and see the summary.

## Running the MQTT bridge (Phase 6)

Needs a reachable MQTT broker (e.g. Home Assistant's Mosquitto add-on, or
any existing MQTT broker). Configure via environment variables, or copy
`.env.example` to `.env` and fill it in:

```bash
export MQTT_HOST=192.168.1.10      # your broker's address (default: localhost)
export MQTT_PORT=1883              # (default: 1883)
export MQTT_USERNAME=...           # optional
export MQTT_PASSWORD=...           # optional

poetry run bridge
```

Runs indefinitely (Ctrl+C to stop), reconnecting automatically after a
BLE drop. Home Assistant should auto-discover a **"Nanoleaf Remote
Position"** entity (type *event*) — each rotation shows up as a `face_1`
through `face_12` event, usable directly in an HA automation (a "State"
trigger on this entity, filtered on the `event_type` attribute).

## Command reference

| Command | Needs hardware? | What it does |
|---|:---:|---|
| `poetry run pytest tests/test_srp_official_vector.py` | No | Checks `srp.py` against Apple's official test vector |
| `poetry run pytest tests/test_pairing_e2e_fake.py` | No | Full Pair-Setup against a simulated accessory |
| `poetry run pytest tests/test_pair_verify_e2e_fake.py` | No | Full Pair-Verify against a simulated accessory |
| `poetry run phase1` | Yes | HAP-BLE transport/framing (Pairing Features) |
| `poetry run phase2 <code>` | Yes | Real Pair-Setup (8-digit code) |
| `poetry run phase3` | Yes | Real Pair-Verify (reuses `pairing.json`) |
| `poetry run phase4` | Yes | Encrypted session + reading an event |
| `poetry run phase5 [duration]` | Yes | Indication subscription (live listening) |
| `poetry run calibrate` | Yes | Interactive face-by-face verification |
| `poetry run bridge` | Yes | Long-running service: publishes events to MQTT/Home Assistant |
| `poetry run watch_adv` | Yes (listen only) | Watches the Remote's advertisements (no connection) to see whether its state counter changes when turned |

## Sources used for the protocol constants

- Pairing service UUID / Pair Setup, Pair Verify, Pairing Features
  characteristics, and TLV8 values (`kTLVType_*`): source code of
  [pyhomekit](https://github.com/henridwyer/pyhomekit) (`constants.py`).
- HAP-BLE PDU header format (Control Field, fragmentation): same
  project, `ble.py` (`HapBlePduRequestHeader`/`HapBlePduResponseHeader`).
- HKDF salt/info strings for Pair-Setup and Pair-Verify: cross-referenced
  across several independent implementations (including
  `aanon4/HomeKit`) and Apple developer-forum threads about undocumented
  pitfalls in the non-commercial HAP spec.

As always with reverse engineering: these constants are verified by
cross-referencing sources, but only a test against the real device
(Phase 1) confirms they hold for this specific Remote's firmware.

## Contributing

Issues and pull requests are welcome, in English or French — see
`CONTRIBUTING.md` for the development setup and the checks to run
locally.

## Security

`pairing.json` contains a private key: see [`SECURITY.md`](../SECURITY.md) before sharing
it or pasting it into an issue. To report a flaw in the cryptographic
implementation itself, please use GitHub's private vulnerability
reporting rather than a public issue — details in [`SECURITY.md`](../SECURITY.md).

## License

[MIT](../LICENSE). See also [`CHANGELOG.md`](../CHANGELOG.md) for release history.
