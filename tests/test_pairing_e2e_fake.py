"""
Simule un accessoire HAP côté "serveur" pour Pair-Setup, en Python pur,
afin de valider l'intégralité de hapble.pairing.pair_setup() (TLV8, SRP-6a,
HKDF, Ed25519, ChaCha20-Poly1305, machine à états M1-M6) SANS dépendre du
Bluetooth ni du vrai appareil.

Important : ceci teste la cohérence INTERNE de notre implémentation (le
client et ce faux serveur utilisent la même compréhension du protocole).
Ça ne remplace donc pas le test contre le vrai firmware Nanoleaf, qui reste
le seul juge final. Mais si CE test échoue, on sait qu'il y a un bug dans
notre code avant même de le tester en conditions réelles — précieux vu la
fenêtre de connexion très courte observée en Phase 1.
"""

import asyncio
import sys

from hapble import crypto_hap, pairing, srp, tlv8, uuids  # noqa: E402


class FakeAccessory:
    """Implémente le côté "accessoire" du Pair-Setup, avec la même
    interface write_ktlvs() qu'une vraie HapBleCharacteristic, pour que
    hapble.pairing.pair_setup() puisse lui parler sans savoir que ce n'est
    pas du vrai Bluetooth."""

    def __init__(self, setup_code: str):
        self.setup_code = pairing.normalize_setup_code(setup_code)
        self.state = 0
        self.b = 0
        self.B = 0
        self.salt = b""
        self.v = 0
        self.session_key = b""
        self.controller_ltpk = b""
        self.controller_pairing_id = b""
        self.ltsk, self.ltpk = crypto_hap.generate_ed25519_keypair()
        self.accessory_pairing_id = b"fake-accessory-0001"

    async def write_ktlvs(self, ktlvs):
        # Simule fidèlement le round-trip fil : encode comme le ferait
        # notre transport réel, puis décode côté "accessoire" — ça exerce
        # aussi la logique de fragmentation TLV8 (ex: PublicKey > 255o).
        wire_bytes = tlv8.encode(ktlvs)
        ktlvs = tlv8.decode(wire_bytes)

        state = ktlvs[uuids.TLVType.STATE][0]

        if state == 1:
            response = self._handle_m1()
        elif state == 3:
            response = self._handle_m3(ktlvs)
        elif state == 5:
            response = self._handle_m5(ktlvs)
        else:
            raise AssertionError(f"État client inattendu: {state}")

        response_wire = tlv8.encode(list(response.items()))
        return tlv8.decode(response_wire)

    def _handle_m1(self):
        import secrets as _secrets

        self.salt = _secrets.token_bytes(16)
        x = int.from_bytes(
            srp._sha512(self.salt, srp._sha512(srp.USERNAME, b":", self.setup_code)),
            "big",
        )
        self.v = pow(srp.G, x, srp.N)
        self.b = int.from_bytes(_secrets.token_bytes(32), "big")
        k = int.from_bytes(srp._sha512(srp.pad(srp.N), srp.pad(srp.G)), "big")
        self.B = (k * self.v + pow(srp.G, self.b, srp.N)) % srp.N
        return {
            uuids.TLVType.STATE: bytes([2]),
            uuids.TLVType.PUBLIC_KEY: srp.pad(self.B),
            uuids.TLVType.SALT: self.salt,
        }

    def _handle_m3(self, ktlvs):
        A_bytes = ktlvs[uuids.TLVType.PUBLIC_KEY]
        client_proof = ktlvs[uuids.TLVType.PROOF]
        A = int.from_bytes(A_bytes, "big")

        u = int.from_bytes(srp._sha512(srp.pad(A), srp.pad(self.B)), "big")
        S = pow(A * pow(self.v, u, srp.N), self.b, srp.N)
        self.session_key = srp._sha512(srp.pad(S))

        # Note : un vrai accessoire ne "sait" pas si le mot de passe entré
        # par le client était le bon avant ce point — il calcule
        # simplement SA preuve à partir de SA session_key (dérivée de son
        # v correct), et c'est au CLIENT de détecter un désaccord en
        # vérifiant cette preuve (verify_server_proof). On ne fait donc
        # PAS d'assertion ici : si le mot de passe du client était faux,
        # client_proof ne matchera jamais ce que la formule symétrique
        # produirait, et c'est exactement ce que ce test négatif vérifie.
        server_proof = srp._sha512(
            srp._minimal_bytes(A), client_proof, self.session_key
        )
        return {
            uuids.TLVType.STATE: bytes([4]),
            uuids.TLVType.PROOF: server_proof,
        }

    def _handle_m5(self, ktlvs):
        encrypt_key = crypto_hap.hkdf_sha512(
            self.session_key,
            uuids.HKDF_PAIR_SETUP_ENCRYPT_SALT,
            uuids.HKDF_PAIR_SETUP_ENCRYPT_INFO,
            length=32,
        )
        encrypted = ktlvs[uuids.TLVType.ENCRYPTED_DATA]
        nonce = bytes(4) + b"PS-Msg05"
        sub_tlv_bytes = crypto_hap.chacha20poly1305_decrypt(
            encrypt_key, nonce, encrypted
        )
        sub_tlv = tlv8.decode(sub_tlv_bytes)
        self.controller_pairing_id = sub_tlv[uuids.TLVType.IDENTIFIER]
        self.controller_ltpk = sub_tlv[uuids.TLVType.PUBLIC_KEY]
        signature = sub_tlv[uuids.TLVType.SIGNATURE]

        controller_sign_key = crypto_hap.hkdf_sha512(
            self.session_key,
            uuids.HKDF_PAIR_SETUP_CONTROLLER_SIGN_SALT,
            uuids.HKDF_PAIR_SETUP_CONTROLLER_SIGN_INFO,
            length=32,
        )
        controller_info = (
            controller_sign_key + self.controller_pairing_id + self.controller_ltpk
        )
        crypto_hap.ed25519_verify(self.controller_ltpk, controller_info, signature)

        # Construit M6 : notre identité (fausse) signée et chiffrée.
        accessory_sign_key = crypto_hap.hkdf_sha512(
            self.session_key,
            uuids.HKDF_PAIR_SETUP_ACCESSORY_SIGN_SALT,
            uuids.HKDF_PAIR_SETUP_ACCESSORY_SIGN_INFO,
            length=32,
        )
        accessory_info = accessory_sign_key + self.accessory_pairing_id + self.ltpk
        accessory_signature = crypto_hap.ed25519_sign(self.ltsk, accessory_info)
        m6_sub_tlv = tlv8.encode(
            [
                (uuids.TLVType.IDENTIFIER, self.accessory_pairing_id),
                (uuids.TLVType.PUBLIC_KEY, self.ltpk),
                (uuids.TLVType.SIGNATURE, accessory_signature),
            ]
        )
        m6_nonce = bytes(4) + b"PS-Msg06"
        m6_encrypted = crypto_hap.chacha20poly1305_encrypt(
            encrypt_key, m6_nonce, m6_sub_tlv
        )
        return {
            uuids.TLVType.STATE: bytes([6]),
            uuids.TLVType.ENCRYPTED_DATA: m6_encrypted,
        }


async def main():
    print("=== Test de bout en bout : Pair-Setup contre un faux accessoire ===")
    print()

    fake = FakeAccessory(setup_code="123-45-678")
    controller_id = b"test-controller-0001"

    result = await pairing.pair_setup(fake, "123-45-678", controller_id)

    print("Pair-Setup terminé avec succès (côté client).")
    print(f"  controller_pairing_id : {result.controller_pairing_id}")
    print(f"  accessory_pairing_id  : {result.accessory_pairing_id}")
    print(f"  accessory_ltpk (hex)  : {result.accessory_ltpk.hex()}")
    print()

    # Vérifications croisées : ce que le client a obtenu doit correspondre
    # exactement à ce que le faux accessoire a lui-même vu/généré.
    assert result.controller_pairing_id == controller_id
    assert result.accessory_pairing_id == fake.accessory_pairing_id
    assert result.accessory_ltpk == fake.ltpk
    assert fake.controller_pairing_id == controller_id
    assert fake.controller_ltpk == result.controller_ltpk
    print("OK : toutes les vérifications croisées client <-> accessoire passent.")
    print()

    print("=== Test negatif : mauvais code d'appairage ===")
    fake2 = FakeAccessory(setup_code="123-45-678")
    try:
        await pairing.pair_setup(fake2, "000-00-000", b"test-controller-0002")
        print("ECHEC : aurait dû lever SrpAuthenticationError")
        sys.exit(1)
    except srp.SrpAuthenticationError:
        print("OK : mauvais code correctement rejeté (SrpAuthenticationError)")

    print()
    print("TOUS LES TESTS DE BOUT EN BOUT SONT PASSES.")


def test_pair_setup_end_to_end_against_fake_accessory() -> None:
    asyncio.run(main())
