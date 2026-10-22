# Nanoleaf Remote — Home Assistant

Pairs a Nanoleaf Remote directly through Home Assistant's own Bluetooth stack (local adapter or ESPHome Bluetooth proxy) and exposes rotations as an **Event** entity with event types `face_1` … `face_12`. No Apple Home, no MQTT.

## Installation

1. In HACS, add this repository as a custom repository of type **Integration**, download it and restart Home Assistant.
2. **Remove the Remote from Apple Home first.** It only accepts one controller; otherwise pairing fails with "refuses new pairings".
3. Turn the Remote to wake it. Home Assistant should offer it as a discovered device; otherwise add **Nanoleaf Remote** in Settings → Devices & services.
4. Enter the 8-digit HomeKit setup code printed on the Remote.

If the Remote is not listed, type its Bluetooth address (printed in the `hapble` tools output, e.g. `D6:BD:09:C0:32:1D`). You can check that Home Assistant sees it in Settings → Devices & services → Bluetooth → Configure → Advertisement monitor.

### Already paired with the `hapble` tools?

If you already ran `poetry run phase2` and have a `pairing.json`, the Remote is still paired with that file and will refuse a second pairing. Choose **Reuse an existing pairing** in the setup flow and paste the content of `pairing.json`: Home Assistant checks it against the Remote, then keeps it. Do not run the `hapble` tools against the same Remote at the same time (it accepts only one connection).

## Using it

Create an automation with an **Event** trigger on the entity and match `event_type` (`face_1` … `face_12`). By default the face number is the detected position (switch instance index + 1), which may not match the numbering you expect. Run `poetry run calibrate` from the repository (Remote near the computer, test all 12 faces): it prints a table. Then open Settings → Devices & services → Nanoleaf Remote → **Configure** and paste it (12 comma-separated numbers, the Nth being the real face for the Nth detected position). The same table works for the MQTT bridge as `FACE_MAP` in `.env`.

## Status and limitations

- Not yet validated end to end from Home Assistant on real hardware. The protocol layer has been validated against a real Remote with the standalone tools.
- The Remote disconnects after ~5 s of silence, so the integration polls every 1.5 s to stay connected. The entity is unavailable while the Remote is out of range.
- The cryptographic code has had no independent security audit. See `SECURITY.md`.
- `custom_components/nanoleaf_remote/hapble/` is a vendored copy of the root `hapble/` library. Do not edit it by hand: run `python scripts/sync_vendored.py`.
