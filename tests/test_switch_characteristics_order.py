"""
`HapBleAccessory.programmable_switch_event_characteristics()` doit renvoyer
les instances triées par leur Characteristic Instance ID (CID), pas dans
l'ordre où un faux client `bleak` les énumère.

Motivation (voir le docstring de la méthode dans `hapble/transport.py`) :
un retour utilisateur signale que la table de calibration des faces se
retrouve fausse après chaque mise à jour/redémarrage de Home Assistant,
symptôme cohérent avec un ordre de découverte GATT qui changerait d'une
connexion à l'autre. Rien ne garantit cet ordre ; le CID, lui, est assigné
une fois pour toutes par le firmware. Ce test vérifie, sans aucun matériel,
que `programmable_switch_event_characteristics()` ignore bien l'ordre de
découverte et ne se fie qu'au CID.
"""

from __future__ import annotations

import asyncio

from hapble import uuids
from hapble.transport import HapBleAccessory


class FakeDescriptor:
    def __init__(self, uuid: str, handle: int) -> None:
        self.uuid = uuid
        self.handle = handle


class FakeGattChar:
    def __init__(self, uuid: str, cid_handle: int) -> None:
        self.uuid = uuid
        self.descriptors = [
            FakeDescriptor(uuids.CHARACTERISTIC_ID_DESCRIPTOR_UUID, cid_handle)
        ]


class FakeService:
    def __init__(self, uuid: str, characteristic: FakeGattChar) -> None:
        self.uuid = uuid
        self._characteristic = characteristic

    def get_characteristic(self, char_uuid: str):
        if self._characteristic.uuid.lower() == char_uuid.lower():
            return self._characteristic
        return None


class FakeClient:
    """`services` : ordre de découverte volontairement mélangé par rapport
    au CID (voir le test) ; `cid_by_handle` fournit la réponse de lecture
    du descripteur CID pour chaque handle, comme le ferait un vrai
    accessoire."""

    def __init__(
        self, services: list[FakeService], cid_by_handle: dict[int, int]
    ) -> None:
        self.services = services
        self._cid_by_handle = cid_by_handle

    async def read_gatt_descriptor(self, handle: int) -> bytes:
        return self._cid_by_handle[handle].to_bytes(2, "little")


def _switch_service(handle: int) -> FakeService:
    char = FakeGattChar(
        uuids.PROGRAMMABLE_SWITCH_EVENT_CHARACTERISTIC_UUID, cid_handle=handle
    )
    return FakeService(uuids.STATELESS_PROGRAMMABLE_SWITCH_SERVICE_UUID, char)


async def _ordered_cids(client: FakeClient) -> list[int]:
    accessory = HapBleAccessory(device_or_address=None, client=client)
    chars = await accessory.programmable_switch_event_characteristics()
    return list(await asyncio.gather(*(char.cid() for char in chars)))


def test_switch_characteristics_are_sorted_by_cid_not_discovery_order() -> None:
    # Les CID réels sont 10, 20, 30 ; le faux client les découvre dans un
    # ordre différent (30, 10, 20) - typiquement ce que ferait une
    # reconnexion qui réénumère les services dans un ordre différent.
    handles = {
        10: 10,
        20: 20,
        30: 30,
    }  # handle de descripteur = CID ici, pour simplifier
    discovery_order = [30, 10, 20]
    services = [_switch_service(handle) for handle in discovery_order]
    client = FakeClient(services, cid_by_handle=handles)

    cids = asyncio.run(_ordered_cids(client))
    assert cids == [10, 20, 30]


def test_switch_characteristics_order_is_stable_across_reconnections() -> None:
    """Deux "sessions" avec le même accessoire mais un ordre de découverte
    différent doivent produire le même ordre final (par CID) - c'est
    précisément la propriété qui manquait avant ce correctif, et qui
    rendait une table de calibration valable une session mais fausse la
    suivante."""
    handles = {10: 10, 20: 20, 30: 30}

    client_1 = FakeClient(
        [_switch_service(h) for h in [10, 20, 30]], cid_by_handle=handles
    )
    client_2 = FakeClient(
        [_switch_service(h) for h in [30, 20, 10]], cid_by_handle=handles
    )

    async def run() -> tuple[list[int], list[int]]:
        return await _ordered_cids(client_1), await _ordered_cids(client_2)

    cids_1, cids_2 = asyncio.run(run())
    assert cids_1 == cids_2 == [10, 20, 30]
