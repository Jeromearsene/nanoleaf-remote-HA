"""
Pair-Setup HAP : les 6 messages (M1 -> M6) échangés sur la caractéristique
Pair Setup pour établir un appairage durable avec l'accessoire, à partir du
code à 8 chiffres.

Résumé du flot (voir aussi hapble/uuids.py pour les constantes salt/info) :

  M1 (nous  -> accessoire) : State=1, Method=PairSetup
  M2 (accessoire -> nous)  : State=2, PublicKey=B, Salt=s          [SRP]
  M3 (nous  -> accessoire) : State=3, PublicKey=A, Proof=M1_srp
  M4 (accessoire -> nous)  : State=4, Proof=M2_srp                  [ou Error]
  M5 (nous  -> accessoire) : State=5, EncryptedData=chiffré(
                                  Identifier=notre_id,
                                  PublicKey=notre_LTPK,
                                  Signature=signature(...))
  M6 (accessoire -> nous)  : State=6, EncryptedData=chiffré(
                                  Identifier=id_accessoire,
                                  PublicKey=LTPK_accessoire,
                                  Signature=signature(...))          [ou Error]

À la fin, on obtient et on conserve : notre propre paire Ed25519 (LTSK/LTPK)
et l'identité de l'accessoire (son Identifier + LTPK) — c'est ce dont
Pair-Verify (Phase 3) aura besoin à chaque future connexion, SANS avoir à
ressaisir le code à 8 chiffres.
"""

import re
from dataclasses import dataclass

from . import crypto_hap, srp, tlv8, uuids
from .transport import HapBleCharacteristic


class PairSetupError(Exception):
    """Erreur remontée par l'accessoire (kTLVType_Error) ou détectée
    localement (State inattendu, signature invalide, etc.).

    `tlv_error` contient le code kTLVType_Error de l'accessoire (voir
    `uuids.TLVError`) quand il est à l'origine du refus, sinon None."""

    def __init__(self, message: str, tlv_error: int | None = None):
        super().__init__(message)
        self.tlv_error = tlv_error


@dataclass
class PairingResult:
    controller_pairing_id: bytes  # notre identifiant (choisi par nous)
    controller_ltsk: bytes  # notre clé privée Ed25519 (32o) — SECRET
    controller_ltpk: bytes  # notre clé publique Ed25519 (32o)
    accessory_pairing_id: bytes  # identifiant de l'accessoire
    accessory_ltpk: bytes  # clé publique Ed25519 de l'accessoire


def normalize_setup_code(code: str) -> bytes:
    """Normalise vers le format canonique XXX-XX-XXX, TIRETS INCLUS.

    Important : le mot de passe utilisé dans le calcul SRP (x = H(s | H(I |
    ':' | P))) est la chaîne complète avec tirets, pas les 8 chiffres nus.
    Confirmé par plusieurs sources indépendantes (dont pyhomekit, notre
    référence principale : "Must be formatted as XXX-XX-XXX where each X
    is a 0-9 digit and dashes are required" ; RubyHome : "the accessory
    must generate its SRP verifier with the full Setup Code, including
    dashes"). Accepte en entrée aussi bien "54397113" que "543-97-113".
    """
    digits = re.sub(r"\D", "", code)
    if len(digits) != 8:
        raise ValueError(
            f"Le code d'appairage doit contenir 8 chiffres, "
            f"{len(digits)} trouvé(s) dans {code!r}."
        )
    formatted = f"{digits[0:3]}-{digits[3:5]}-{digits[5:8]}"
    return formatted.encode("ascii")


def _check_error(ktlvs: dict) -> None:
    if uuids.TLVType.ERROR in ktlvs:
        code = ktlvs[uuids.TLVType.ERROR][0]
        message = {
            uuids.TLVError.UNKNOWN: "Erreur inconnue.",
            uuids.TLVError.AUTHENTICATION: (
                "Échec d'authentification — code à 8 chiffres incorrect."
            ),
            uuids.TLVError.BACKOFF: (
                "L'accessoire demande d'attendre avant de réessayer "
                "(trop de tentatives récentes)."
            ),
            uuids.TLVError.MAX_PEERS: "L'accessoire a atteint son nombre maximum de pairings.",
            uuids.TLVError.MAX_TRIES: "Nombre maximum de tentatives atteint.",
            uuids.TLVError.UNAVAILABLE: "L'appairage n'est pas/plus disponible sur cet accessoire.",
            uuids.TLVError.BUSY: "L'accessoire est occupé, réessayer plus tard.",
        }.get(code, f"Code d'erreur TLV inconnu: 0x{code:02x}")
        raise PairSetupError(
            f"L'accessoire a refusé l'appairage : {message}", tlv_error=code
        )


async def pair_setup(
    char: HapBleCharacteristic, setup_code: str, controller_pairing_id: bytes
) -> PairingResult:
    """Exécute l'intégralité du Pair-Setup HAP (M1->M6) sur la
    caractéristique Pair Setup déjà ouverte, et retourne les clés à
    conserver pour les futures connexions (Pair-Verify)."""

    password = normalize_setup_code(setup_code)

    # --- M1 : State=1, Method=PairSetup(1) --------------------------------
    m2 = await char.write_ktlvs(
        [
            (uuids.TLVType.STATE, bytes([1])),
            (uuids.TLVType.METHOD, bytes([uuids.PairMethod.PAIR_SETUP])),
        ]
    )
    _check_error(m2)
    if m2.get(uuids.TLVType.STATE) != bytes([2]):
        raise PairSetupError(
            f"État inattendu en M2 : {m2.get(uuids.TLVType.STATE)!r} (2 attendu)."
        )
    accessory_public_key = m2[uuids.TLVType.PUBLIC_KEY]  # B, 384 octets
    salt = m2[uuids.TLVType.SALT]  # s, 16 octets

    # --- Calcul SRP côté client --------------------------------------------
    client = srp.SrpClient()
    our_public_key = client.generate_a()  # A, 384 octets (déjà PAD())
    client.process_challenge(salt, accessory_public_key, password)
    client_proof = client.compute_client_proof()  # M1_srp, 64 octets

    # --- M3 : State=3, PublicKey=A, Proof=M1_srp ---------------------------
    m4 = await char.write_ktlvs(
        [
            (uuids.TLVType.STATE, bytes([3])),
            (uuids.TLVType.PUBLIC_KEY, our_public_key),
            (uuids.TLVType.PROOF, client_proof),
        ]
    )
    _check_error(m4)
    if m4.get(uuids.TLVType.STATE) != bytes([4]):
        raise PairSetupError(
            f"État inattendu en M4 : {m4.get(uuids.TLVType.STATE)!r} (4 attendu)."
        )
    server_proof = m4[uuids.TLVType.PROOF]  # M2_srp, 64 octets

    # Lève SrpAuthenticationError si le code à 8 chiffres est incorrect.
    client.verify_server_proof(server_proof)

    session_key = client.K  # 64 octets, dérivé du secret SRP partagé

    # --- Préparation de M5 : notre identité signée, chiffrée --------------
    encrypt_key = crypto_hap.hkdf_sha512(
        session_key,
        uuids.HKDF_PAIR_SETUP_ENCRYPT_SALT,
        uuids.HKDF_PAIR_SETUP_ENCRYPT_INFO,
        length=32,
    )

    controller_ltsk, controller_ltpk = crypto_hap.generate_ed25519_keypair()

    controller_sign_key = crypto_hap.hkdf_sha512(
        session_key,
        uuids.HKDF_PAIR_SETUP_CONTROLLER_SIGN_SALT,
        uuids.HKDF_PAIR_SETUP_CONTROLLER_SIGN_INFO,
        length=32,
    )
    controller_info = controller_sign_key + controller_pairing_id + controller_ltpk
    controller_signature = crypto_hap.ed25519_sign(controller_ltsk, controller_info)

    m5_sub_tlv = tlv8.encode(
        [
            (uuids.TLVType.IDENTIFIER, controller_pairing_id),
            (uuids.TLVType.PUBLIC_KEY, controller_ltpk),
            (uuids.TLVType.SIGNATURE, controller_signature),
        ]
    )
    m5_nonce = bytes(4) + b"PS-Msg05"
    assert len(m5_nonce) == 12
    m5_encrypted = crypto_hap.chacha20poly1305_encrypt(
        encrypt_key, m5_nonce, m5_sub_tlv
    )

    # --- M5 : State=5, EncryptedData ---------------------------------------
    m6 = await char.write_ktlvs(
        [
            (uuids.TLVType.STATE, bytes([5])),
            (uuids.TLVType.ENCRYPTED_DATA, m5_encrypted),
        ]
    )
    _check_error(m6)
    if m6.get(uuids.TLVType.STATE) != bytes([6]):
        raise PairSetupError(
            f"État inattendu en M6 : {m6.get(uuids.TLVType.STATE)!r} (6 attendu)."
        )

    # --- Déchiffrement + vérification de l'identité de l'accessoire -------
    m6_encrypted = m6[uuids.TLVType.ENCRYPTED_DATA]
    m6_nonce = bytes(4) + b"PS-Msg06"
    m6_sub_tlv_bytes = crypto_hap.chacha20poly1305_decrypt(
        encrypt_key, m6_nonce, m6_encrypted
    )
    m6_sub_tlv = tlv8.decode(m6_sub_tlv_bytes)

    accessory_pairing_id = m6_sub_tlv[uuids.TLVType.IDENTIFIER]
    accessory_ltpk = m6_sub_tlv[uuids.TLVType.PUBLIC_KEY]
    accessory_signature = m6_sub_tlv[uuids.TLVType.SIGNATURE]

    accessory_sign_key = crypto_hap.hkdf_sha512(
        session_key,
        uuids.HKDF_PAIR_SETUP_ACCESSORY_SIGN_SALT,
        uuids.HKDF_PAIR_SETUP_ACCESSORY_SIGN_INFO,
        length=32,
    )
    accessory_info = accessory_sign_key + accessory_pairing_id + accessory_ltpk
    # Lève SignatureError si l'accessoire ne peut pas prouver la possession
    # de sa clé longue durée (accessoire non authentique, ou données
    # corrompues en transit).
    crypto_hap.ed25519_verify(accessory_ltpk, accessory_info, accessory_signature)

    return PairingResult(
        controller_pairing_id=controller_pairing_id,
        controller_ltsk=controller_ltsk,
        controller_ltpk=controller_ltpk,
        accessory_pairing_id=accessory_pairing_id,
        accessory_ltpk=accessory_ltpk,
    )
