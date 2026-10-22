"""
Simule un accessoire HAP côté "serveur" pour Pair-Verify, en Python pur,
pour valider hapble.pair_verify de bout en bout sans matériel réel — même
démarche que tests/test_pairing_e2e_fake.py pour Pair-Setup.

Ce faux accessoire "connaît" à l'avance le résultat d'un Pair-Setup (LTPK du
controller, sa propre paire LTSK/LTPK) — exactement l'état dans lequel se
trouverait un vrai accessoire après un Pair-Setup réussi.
"""

import asyncio
import sys

from hapble import crypto_hap, pair_verify, tlv8, uuids  # noqa: E402
from hapble.pairing import PairingResult  # noqa: E402


class FakeAccessoryForVerify:
    """Implémente le côté "accessoire" de Pair-Verify."""

    def __init__(
        self,
        accessory_pairing_id: bytes,
        accessory_ltsk: bytes,
        accessory_ltpk: bytes,
        controller_pairing_id: bytes,
        controller_ltpk: bytes,
    ):
        self.accessory_pairing_id = accessory_pairing_id
        self.accessory_ltsk = accessory_ltsk
        self.accessory_ltpk = accessory_ltpk
        self.controller_pairing_id = controller_pairing_id
        self.controller_ltpk = controller_ltpk  # obtenu lors du Pair-Setup

    async def write_ktlvs(self, ktlvs):
        wire_bytes = tlv8.encode(ktlvs)
        ktlvs = tlv8.decode(wire_bytes)
        state = ktlvs[uuids.TLVType.STATE][0]

        if state == 1:
            response = self._handle_m1(ktlvs)
        elif state == 3:
            response = self._handle_m3(ktlvs)
        else:
            raise AssertionError(f"État client inattendu: {state}")

        response_wire = tlv8.encode(list(response.items()))
        return tlv8.decode(response_wire)

    def _handle_m1(self, ktlvs):
        ctrl_eph_pub = ktlvs[uuids.TLVType.PUBLIC_KEY]

        acc_eph_priv, acc_eph_pub = crypto_hap.generate_x25519_keypair()
        self._acc_eph_priv = acc_eph_priv
        self._acc_eph_pub = acc_eph_pub
        self._ctrl_eph_pub = ctrl_eph_pub

        shared_secret = crypto_hap.x25519_exchange(acc_eph_priv, ctrl_eph_pub)
        self._shared_secret = shared_secret
        session_key = crypto_hap.hkdf_sha512(
            shared_secret,
            uuids.HKDF_PAIR_VERIFY_ENCRYPT_SALT,
            uuids.HKDF_PAIR_VERIFY_ENCRYPT_INFO,
            length=32,
        )
        self._session_key = session_key

        accessory_info = acc_eph_pub + self.accessory_pairing_id + ctrl_eph_pub
        accessory_signature = crypto_hap.ed25519_sign(
            self.accessory_ltsk, accessory_info
        )
        sub_tlv = tlv8.encode(
            [
                (uuids.TLVType.IDENTIFIER, self.accessory_pairing_id),
                (uuids.TLVType.SIGNATURE, accessory_signature),
            ]
        )
        nonce = bytes(4) + b"PV-Msg02"
        encrypted = crypto_hap.chacha20poly1305_encrypt(session_key, nonce, sub_tlv)
        return {
            uuids.TLVType.STATE: bytes([2]),
            uuids.TLVType.PUBLIC_KEY: acc_eph_pub,
            uuids.TLVType.ENCRYPTED_DATA: encrypted,
        }

    def _handle_m3(self, ktlvs):
        encrypted = ktlvs[uuids.TLVType.ENCRYPTED_DATA]
        nonce = bytes(4) + b"PV-Msg03"
        sub_tlv_bytes = crypto_hap.chacha20poly1305_decrypt(
            self._session_key, nonce, encrypted
        )
        sub_tlv = tlv8.decode(sub_tlv_bytes)
        received_id = sub_tlv[uuids.TLVType.IDENTIFIER]
        signature = sub_tlv[uuids.TLVType.SIGNATURE]

        assert received_id == self.controller_pairing_id, (
            "Identifiant controller inattendu"
        )
        controller_info = self._ctrl_eph_pub + received_id + self._acc_eph_pub
        crypto_hap.ed25519_verify(self.controller_ltpk, controller_info, signature)

        return {uuids.TLVType.STATE: bytes([4])}


async def main():
    print("=== Test de bout en bout : Pair-Verify contre un faux accessoire ===")
    print()

    # Simule le resultat d'un Pair-Setup prealable.
    controller_ltsk, controller_ltpk = crypto_hap.generate_ed25519_keypair()
    accessory_ltsk, accessory_ltpk = crypto_hap.generate_ed25519_keypair()
    controller_pairing_id = b"test-controller-0001"
    accessory_pairing_id = b"fake-accessory-0001"

    pairing_result = PairingResult(
        controller_pairing_id=controller_pairing_id,
        controller_ltsk=controller_ltsk,
        controller_ltpk=controller_ltpk,
        accessory_pairing_id=accessory_pairing_id,
        accessory_ltpk=accessory_ltpk,
    )

    fake = FakeAccessoryForVerify(
        accessory_pairing_id=accessory_pairing_id,
        accessory_ltsk=accessory_ltsk,
        accessory_ltpk=accessory_ltpk,
        controller_pairing_id=controller_pairing_id,
        controller_ltpk=controller_ltpk,
    )

    session_keys = await pair_verify.pair_verify(fake, pairing_result)

    print("Pair-Verify terminé avec succès (côté client).")
    print(f"  read_key  (hex): {session_keys.read_key.hex()}")
    print(f"  write_key (hex): {session_keys.write_key.hex()}")
    print()

    # Verifications croisees : le meme secret partage doit produire les
    # memes cles de session des DEUX cotes (calcule independamment ici).
    fake_read_key = crypto_hap.hkdf_sha512(
        fake._shared_secret,
        uuids.HKDF_CONTROL_SALT,
        uuids.HKDF_CONTROL_READ_INFO,
        length=32,
    )
    fake_write_key = crypto_hap.hkdf_sha512(
        fake._shared_secret,
        uuids.HKDF_CONTROL_SALT,
        uuids.HKDF_CONTROL_WRITE_INFO,
        length=32,
    )
    assert fake_read_key == session_keys.read_key
    assert fake_write_key == session_keys.write_key
    print(
        "OK : clés de session identiques calculées indépendamment côté "
        "'accessoire' (mêmes read_key/write_key)."
    )
    print()

    print("=== Test negatif : mauvais identifiant d'accessoire ===")
    bad_pairing = PairingResult(
        controller_pairing_id=controller_pairing_id,
        controller_ltsk=controller_ltsk,
        controller_ltpk=controller_ltpk,
        accessory_pairing_id=b"un-autre-identifiant",  # ne correspond pas
        accessory_ltpk=accessory_ltpk,
    )
    fake2 = FakeAccessoryForVerify(
        accessory_pairing_id=accessory_pairing_id,
        accessory_ltsk=accessory_ltsk,
        accessory_ltpk=accessory_ltpk,
        controller_pairing_id=controller_pairing_id,
        controller_ltpk=controller_ltpk,
    )
    try:
        await pair_verify.pair_verify(fake2, bad_pairing)
        print("ECHEC : aurait dû lever PairVerifyError")
        sys.exit(1)
    except pair_verify.PairVerifyError as exc:
        print(f"OK : identifiant inattendu correctement rejeté -> {exc}")

    print()
    print("TOUS LES TESTS PAIR-VERIFY SONT PASSES.")


def test_pair_verify_end_to_end_against_fake_accessory() -> None:
    asyncio.run(main())
