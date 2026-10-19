# Nanoleaf Remote — Home Assistant

Initial HACS foundation for the Nanoleaf Remote. It pairs directly through Home Assistant Bluetooth and exposes rotations as an Event entity with event types `face_1` through `face_12`.

## Development installation

1. Add this repository to HACS as a custom repository of type **Integration**.
2. Download the integration and restart Home Assistant.
3. Add **Nanoleaf Remote** in Settings → Devices & services.
4. Enter the Bluetooth address and the HomeKit setup code.

## Status and limitations

This initial implementation has not yet been validated against real hardware from Home Assistant OS. It polls the switch characteristics to accommodate observed idle disconnects. Confirm face numbering and reconnect behavior before relying on it for important automations. The cryptographic protocol code has not received an independent security audit.
