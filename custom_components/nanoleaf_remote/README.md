# Nanoleaf Remote — Home Assistant

Pairs a Nanoleaf Remote directly through Home Assistant's own Bluetooth stack (local adapter or ESPHome Bluetooth proxy) and exposes rotations as an **Event** entity with event types `face_1` … `face_12`. No Apple Home, no MQTT.

## Installation

1. In HACS, add this repository as a custom repository of type **Integration**, download it and restart Home Assistant.
2. **Remove the Remote from Apple Home first.** It only accepts one controller; otherwise pairing fails with "refuses new pairings".
3. Turn the Remote to wake it. Home Assistant should offer it as a discovered device; otherwise add **Nanoleaf Remote** in Settings → Devices & services.
4. Enter the 8-digit HomeKit setup code printed on the Remote.

## Using it

Create an automation with an **Event** trigger on the entity and match `event_type` (`face_1` … `face_12`). The face number follows the order of the Remote's switch characteristics (instance index + 1). Run `poetry run calibrate` from the repository to check which physical face maps to which number.

## Status and limitations

- Not yet validated end to end from Home Assistant on real hardware. The protocol layer has been validated against a real Remote with the standalone tools.
- The Remote disconnects after ~5 s of silence, so the integration polls every 1.5 s to stay connected. The entity is unavailable while the Remote is out of range.
- The cryptographic code has had no independent security audit. See `SECURITY.md`.
- `custom_components/nanoleaf_remote/hapble/` is a vendored copy of the root `hapble/` library. Do not edit it by hand: run `python scripts/sync_vendored.py`.
