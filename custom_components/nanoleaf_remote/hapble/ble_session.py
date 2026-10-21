"""
Session BLE sécurisée : une fois Pair-Verify réussi (hapble.pair_verify),
les échanges GATT ordinaires sur cette même connexion doivent être chiffrés
avec les clés de session (read_key/write_key).

Format confirmé via une crate Rust dédiée spécifiquement au transport
HAP-BLE (pas HAP-IP — la distinction compte, les deux transports ont des
conventions différentes) :
  - chaque opération GATT (une écriture, ou une lecture) chiffre/déchiffre
    la PDU HAP-BLE ENTIÈRE en un seul bloc ChaCha20-Poly1305 ;
  - AUCUNE donnée authentifiée additionnelle (AAD) ;
  - nonce = 4 octets nuls + compteur 64 bits little-endian ;
  - un compteur PAR DIRECTION (écriture et lecture comptent séparément),
    démarrant à 0, incrémenté à chaque opération.

Le format des PDU elles-mêmes (control field, op_code, TLV8...) ne change
pas : cette couche chiffre/déchiffre le résultat déjà construit par
hapble.pdu, elle ne le remplace pas.
"""

from dataclasses import dataclass

from . import crypto_hap


def _nonce(counter: int) -> bytes:
    return bytes(4) + counter.to_bytes(8, "little")


@dataclass
class BleSecureSession:
    read_key: bytes
    write_key: bytes
    send_counter: int = 0
    recv_counter: int = 0

    def seal(self, plaintext: bytes) -> bytes:
        """Chiffre une PDU sortante (avant écriture GATT). Incrémente le
        compteur d'envoi."""
        nonce = _nonce(self.send_counter)
        ciphertext = crypto_hap.chacha20poly1305_encrypt(
            self.write_key, nonce, plaintext
        )
        self.send_counter += 1
        return ciphertext

    def open(self, ciphertext: bytes) -> bytes:
        """Déchiffre une PDU entrante (après lecture GATT). Incrémente le
        compteur de réception. Lève crypto_hap.DecryptionError si le tag
        d'authentification ne correspond pas (désynchronisation de
        compteur, ou données altérées)."""
        nonce = _nonce(self.recv_counter)
        plaintext = crypto_hap.chacha20poly1305_decrypt(
            self.read_key, nonce, ciphertext
        )
        self.recv_counter += 1
        return plaintext
