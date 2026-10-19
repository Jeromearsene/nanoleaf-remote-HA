"""
Enveloppe autour de `cryptography` pour les primitives utilisées par HAP :

- HKDF-SHA512 (dérivation de clé, RFC 5869) — pour Pair-Setup et Pair-Verify.
- Ed25519 (génération de clé, signature, vérification) — identité longue
  durée du controller et de l'accessoire (LTSK/LTPK).
- X25519 (Curve25519, ECDH) — pour Pair-Verify (Phase 3), inclus ici par
  anticipation.
- ChaCha20-Poly1305 (AEAD, variante IETF, nonce 96 bits) — chiffrement des
  sous-TLV de M5/M6.

Rien d'ici n'est "fait maison" : tout repose sur les implémentations de la
bibliothèque `cryptography` (basée sur OpenSSL). Ce module ne fait que
choisir les bons paramètres pour correspondre à ce que HAP attend.
"""

from cryptography.exceptions import InvalidSignature, InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.hazmat.primitives.asymmetric.x25519 import (
    X25519PrivateKey,
    X25519PublicKey,
)
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
from cryptography.hazmat.primitives.kdf.hkdf import HKDF


class DecryptionError(Exception):
    """Échec d'authentification ChaCha20-Poly1305 (tag invalide) — les
    données ont été altérées, ou la mauvaise clé/nonce a été utilisée."""


class SignatureError(Exception):
    """Signature Ed25519 invalide."""


# --- HKDF-SHA512 --------------------------------------------------------


def hkdf_sha512(
    key_material: bytes, salt: bytes, info: bytes, length: int = 32
) -> bytes:
    """HKDF-SHA512 (extract-and-expand, RFC 5869). C'est la fonction
    utilisée partout dans HAP pour dériver des clés de session à partir
    d'un secret partagé (SRP ou ECDH) et de chaînes salt/info fixes."""
    hkdf = HKDF(algorithm=hashes.SHA512(), length=length, salt=salt, info=info)
    return hkdf.derive(key_material)


# --- Ed25519 --------------------------------------------------------------


def generate_ed25519_keypair() -> tuple[bytes, bytes]:
    """Retourne (clé_privée_32o, clé_publique_32o), au format brut ("raw"),
    tel qu'attendu dans les TLV HAP (pas de PEM/DER)."""
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key()
    from cryptography.hazmat.primitives.serialization import (
        Encoding,
        NoEncryption,
        PrivateFormat,
        PublicFormat,
    )

    priv_bytes = private_key.private_bytes(
        Encoding.Raw, PrivateFormat.Raw, NoEncryption()
    )
    pub_bytes = public_key.public_bytes(Encoding.Raw, PublicFormat.Raw)
    return priv_bytes, pub_bytes


def ed25519_sign(private_key_bytes: bytes, message: bytes) -> bytes:
    """Signe `message` avec une clé privée Ed25519 brute (32 octets).
    Retourne une signature de 64 octets."""
    private_key = Ed25519PrivateKey.from_private_bytes(private_key_bytes)
    return private_key.sign(message)


def ed25519_verify(public_key_bytes: bytes, message: bytes, signature: bytes) -> None:
    """Vérifie une signature Ed25519. Lève SignatureError si invalide."""
    public_key = Ed25519PublicKey.from_public_bytes(public_key_bytes)
    try:
        public_key.verify(signature, message)
    except InvalidSignature as exc:
        raise SignatureError(
            "Signature Ed25519 invalide — l'accessoire n'a pas pu prouver "
            "la possession de sa clé longue durée."
        ) from exc


# --- X25519 (pour Pair-Verify, Phase 3) -----------------------------------


def generate_x25519_keypair() -> tuple[bytes, bytes]:
    """Retourne (clé_privée_32o, clé_publique_32o) X25519, format brut."""
    private_key = X25519PrivateKey.generate()
    public_key = private_key.public_key()
    from cryptography.hazmat.primitives.serialization import (
        Encoding,
        NoEncryption,
        PrivateFormat,
        PublicFormat,
    )

    priv_bytes = private_key.private_bytes(
        Encoding.Raw, PrivateFormat.Raw, NoEncryption()
    )
    pub_bytes = public_key.public_bytes(Encoding.Raw, PublicFormat.Raw)
    return priv_bytes, pub_bytes


def x25519_exchange(private_key_bytes: bytes, peer_public_key_bytes: bytes) -> bytes:
    """Calcule le secret partagé ECDH X25519 (32 octets)."""
    private_key = X25519PrivateKey.from_private_bytes(private_key_bytes)
    peer_public_key = X25519PublicKey.from_public_bytes(peer_public_key_bytes)
    return private_key.exchange(peer_public_key)


# --- ChaCha20-Poly1305 ------------------------------------------------------


def chacha20poly1305_encrypt(
    key: bytes, nonce: bytes, plaintext: bytes, aad: bytes = b""
) -> bytes:
    """Chiffre `plaintext` (AEAD). Retourne ciphertext || tag (16 octets),
    tel qu'attendu dans un TLV EncryptedData de HAP."""
    aead = ChaCha20Poly1305(key)
    return aead.encrypt(nonce, plaintext, aad if aad else None)


def chacha20poly1305_decrypt(
    key: bytes, nonce: bytes, ciphertext_with_tag: bytes, aad: bytes = b""
) -> bytes:
    """Déchiffre + vérifie l'authenticité. Lève DecryptionError si le tag
    ne correspond pas (mauvaise clé, données altérées, ou mauvais nonce)."""
    aead = ChaCha20Poly1305(key)
    try:
        return aead.decrypt(nonce, ciphertext_with_tag, aad if aad else None)
    except InvalidTag as exc:
        raise DecryptionError(
            "Échec de déchiffrement ChaCha20-Poly1305 (tag invalide)."
        ) from exc
