"""The Nth switch instance must be the same one at every connection.

BlueZ hands the GATT services over in the order of a Python `set` of D-Bus
paths, which differs from one process to the next. The face map is stored as
"detected position -> face", so the order has to come from the accessory
(GATT handles), not from the host.
"""

from types import SimpleNamespace

import pytest

from hapble import uuids
from hapble.transport import HapBleAccessory

SWITCH = uuids.STATELESS_PROGRAMMABLE_SWITCH_SERVICE_UUID
EVENT = uuids.PROGRAMMABLE_SWITCH_EVENT_CHARACTERISTIC_UUID
HANDLES = [0x10, 0x20, 0x30, 0x40, 0x50, 0x60, 0x70, 0x80, 0x90, 0xA0, 0xB0, 0xC0]


def service(handle: int, uuid: str = SWITCH) -> SimpleNamespace:
    char = SimpleNamespace(uuid=EVENT, handle=handle + 1)
    return SimpleNamespace(
        uuid=uuid,
        handle=handle,
        get_characteristic=lambda char_uuid: char if char_uuid == EVENT else None,
    )


def accessory_with(services: list[SimpleNamespace]) -> HapBleAccessory:
    accessory = HapBleAccessory("AA:BB:CC:DD:EE:FF")
    accessory.client = SimpleNamespace(services=services)
    return accessory


@pytest.mark.parametrize("seed", range(5))
def test_instances_come_back_in_handle_order(seed: int) -> None:
    import random

    handles = HANDLES[:]
    random.Random(seed).shuffle(handles)
    accessory = accessory_with([service(h) for h in handles])

    found = accessory.programmable_switch_event_characteristics()

    assert [c.gatt_char.handle for c in found] == [h + 1 for h in sorted(HANDLES)]


def test_other_services_are_ignored() -> None:
    services = [service(0x05, uuid="0000180a-0000-1000-8000-00805f9b34fb")]
    services += [service(h) for h in reversed(HANDLES)]

    found = accessory_with(services).programmable_switch_event_characteristics()

    assert len(found) == len(HANDLES)
