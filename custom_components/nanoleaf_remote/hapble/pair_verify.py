"""
Pair-Verify HAP : les 4 messages (M1 -> M4) échangés sur la caractéristique
Pair Verify pour établir une session chiffrée à partir d'un appairage déjà
effectué (Pair-Setup) — à refaire à CHAQUE connexion, contrairement à
Pair-Setup qui ne se fait qu'une fois.

Implémenté directement depuis le texte intégral et officiel de la spec HAP
(Release R2, section 5.7 "Pair Verify"), récupéré et lu en entier pour ce
projet — pas de zone d'incertitude ici comme ça avait été le cas pour la
preuve SRP de Pair-Setup.

Résumé du flot :

  M1 (nous  -> accessoire) : State=1, PublicKey=<notre clé X25519 éphémère>
  M2 (accessoire -> nous)  : State=2, PublicKey=<clé X25519 éphémère accessoire>,
                             EncryptedData=chiffré(Identifier=accessory_id,
                                                    Signature=accessory_signature)
  M3 (nous  -> accessoire) : State=3, EncryptedData=chiffré(Identifier=notre_id,
                                                    Signature=notre_signature)
  M4 (accessoire -> nous)  : State=4 (succès) ou State=4 + Error

Notes importantes de la spec, vérifiées dans le texte :
- Les sous-TLV de M2/M3 ne contiennent PAS la clé publique longue durée
  (contrairement à Pair-Setup) : l'accessoire connaît déjà notre LTPK depuis
  Pair-Setup, et nous connaissons déjà la sienne.
- AccessoryInfo = clé_X25519_accessoire || accessory_pairing_id || notre_clé_X25519
  (dans cet ordre précis).
- iOSDeviceInfo (notre signature, symétrique) = notre_clé_X25519 ||
  notre_pairing_id || clé_X25519_accessoire.
- On DOIT vérifier que l'Identifier reçu dans M2 correspond à l'accessoire
  qu'on pense appairer (celui de pairing.json) avant de faire confiance à sa
  signature — la spec dit explicitement "look up... If not found, abort".
"""

from dataclasses import dataclass

from . import crypto_hap, tlv8, uuids
from .pairing import PairingResult
from .transport import HapBleCharacteristic


class PairVerifyError(Exception):
    """Échec de Pair-Verify : identité inattendue, signature invalide, ou
    erreur TLV renvoyée par l'accessoire."""


@dataclass
class SessionKeys:
    """Clés de session dérivées après un Pair-Verify réussi, pour chiffrer
    les échanges GATT ultérieurs (lecture de ProgrammableSwitchEvent, etc.)."""

    read_key: bytes  # déchiffre ce que l'accessoire nous envoie
    write_key: bytes  # chiffre ce que nous envoyons à l'accessoire
    shared_secret: bytes  # conservé pour dérivations ultérieures si besoin


def _check_error(ktlvs: dict) -> None:
    if uuids.TLVType.ERROR in ktlvs:
        code = ktlvs[uuids.TLVType.ERROR][0]
        message = {
            uuids.TLVError.AUTHENTICATION: (
                "Échec d'authentification — signature invalide ou identité inconnue."
            ),
        }.get(code, f"Code d'erreur TLV inconnu: 0x{code:02x}")
        raise PairVerifyError(f"L'accessoire a refusé Pair-Verify : {message}")


async def pair_verify(
    char: HapBleCharacteristic, pairing: PairingResult
) -> SessionKeys:
    """Exécute Pair-Verify (M1->M4) et retourne les clés de session à
    utiliser pour les échanges chiffrés qui suivent."""

    # --- M1 : notre paire X25519 éphémère, envoi de notre clé publique ----
    ctrl_eph_priv, ctrl_eph_pub = crypto_hap.generate_x25519_keypair()

    m2 = await char.write_ktlvs(
        [
            (uuids.TLVType.STATE, bytes([1])),
            (uuids.TLVType.PUBLIC_KEY, ctrl_eph_pub),
        ]
    )
    _check_error(m2)
    if m2.get(uuids.TLVType.STATE) != bytes([2]):
        raise PairVerifyError(
            f"État inattendu en M2 : {m2.get(uuids.TLVType.STATE)!r} (2 attendu)."
        )

    acc_eph_pub = m2[uuids.TLVType.PUBLIC_KEY]  # 32 octets
    m2_encrypted = m2[uuids.TLVType.ENCRYPTED_DATA]

    # --- Secret partagé + clé de session pour M2/M3 -----------------------
    shared_secret = crypto_hap.x25519_exchange(ctrl_eph_priv, acc_eph_pub)
    session_key = crypto_hap.hkdf_sha512(
        shared_secret,
        uuids.HKDF_PAIR_VERIFY_ENCRYPT_SALT,
        uuids.HKDF_PAIR_VERIFY_ENCRYPT_INFO,
        length=32,
    )

    # --- Déchiffrement + vérification de l'identité de l'accessoire -------
    m2_nonce = bytes(4) + b"PV-Msg02"
    m2_sub_tlv_bytes = crypto_hap.chacha20poly1305_decrypt(
        session_key, m2_nonce, m2_encrypted
    )
    m2_sub_tlv = tlv8.decode(m2_sub_tlv_bytes)

    accessory_pairing_id = m2_sub_tlv[uuids.TLVType.IDENTIFIER]
    accessory_signature = m2_sub_tlv[uuids.TLVType.SIGNATURE]

    if accessory_pairing_id != pairing.accessory_pairing_id:
        raise PairVerifyError(
            "L'identifiant renvoyé par l'accessoire ne correspond pas à "
            "celui enregistré lors du Pair-Setup — abandon (accessoire "
            "différent, ou pairing.json corrompu/périmé)."
        )

    accessory_info = acc_eph_pub + accessory_pairing_id + ctrl_eph_pub
    # Lève SignatureError si invalide (accessoire non authentique, ou MITM).
    crypto_hap.ed25519_verify(
        pairing.accessory_ltpk, accessory_info, accessory_signature
    )

    # --- M3 : notre propre identité, signée et chiffrée --------------------
    controller_info = ctrl_eph_pub + pairing.controller_pairing_id + acc_eph_pub
    controller_signature = crypto_hap.ed25519_sign(
        pairing.controller_ltsk, controller_info
    )
    m3_sub_tlv = tlv8.encode(
        [
            (uuids.TLVType.IDENTIFIER, pairing.controller_pairing_id),
            (uuids.TLVType.SIGNATURE, controller_signature),
        ]
    )
    m3_nonce = bytes(4) + b"PV-Msg03"
    m3_encrypted = crypto_hap.chacha20poly1305_encrypt(
        session_key, m3_nonce, m3_sub_tlv
    )

    m4 = await char.write_ktlvs(
        [
            (uuids.TLVType.STATE, bytes([3])),
            (uuids.TLVType.ENCRYPTED_DATA, m3_encrypted),
        ]
    )
    _check_error(m4)
    if m4.get(uuids.TLVType.STATE) != bytes([4]):
        raise PairVerifyError(
            f"État inattendu en M4 : {m4.get(uuids.TLVType.STATE)!r} (4 attendu)."
        )

    # --- Dérivation des clés de session pour les échanges GATT suivants ----
    read_key = crypto_hap.hkdf_sha512(
        shared_secret,
        uuids.HKDF_CONTROL_SALT,
        uuids.HKDF_CONTROL_READ_INFO,
        length=32,
    )
    write_key = crypto_hap.hkdf_sha512(
        shared_secret,
        uuids.HKDF_CONTROL_SALT,
        uuids.HKDF_CONTROL_WRITE_INFO,
        length=32,
    )

    return SessionKeys(
        read_key=read_key, write_key=write_key, shared_secret=shared_secret
    )
