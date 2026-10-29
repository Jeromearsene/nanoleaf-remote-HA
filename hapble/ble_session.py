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

import logging
from dataclasses import dataclass

from . import crypto_hap

logger = logging.getLogger(__name__)


def _nonce(counter: int) -> bytes:
    return bytes(4) + counter.to_bytes(8, "little")


@dataclass
class BleSecureSession:
    read_key: bytes
    write_key: bytes
    send_counter: int = 0
    recv_counter: int = 0
    # How many counters either side of the expected one `open` also tries.
    # 0 (default) = strict. The Remote can deliver a response twice (as a GATT
    # indication and by read) or send one we did not see; with a window of 1
    # the stream recovers instead of failing with a tag error. The tag still
    # authenticates every message; only the nonce is searched.
    resync_window: int = 0

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
        """Déchiffre une PDU entrante (après lecture GATT). Avance le
        compteur de réception. Lève crypto_hap.DecryptionError si le tag
        d'authentification ne correspond à aucun compteur essayé
        (désynchronisation, ou données altérées).

        Avec `resync_window` > 0, essaie aussi les compteurs voisins : un
        message déjà vu (compteur plus petit : le compteur attendu ne recule
        pas) ou un message manqué (compteur plus grand : on saute)."""
        offsets = [0]
        for step in range(1, self.resync_window + 1):
            offsets += [-step, step]
        error: crypto_hap.DecryptionError | None = None
        for offset in offsets:
            counter = self.recv_counter + offset
            if counter < 0:
                continue
            try:
                plaintext = crypto_hap.chacha20poly1305_decrypt(
                    self.read_key, _nonce(counter), ciphertext
                )
            except crypto_hap.DecryptionError as exc:
                error = error or exc
                continue
            if offset:
                logger.info(
                    "Compteur de réception resynchronisé (attendu %d, reçu %d)",
                    self.recv_counter,
                    counter,
                )
            self.recv_counter = max(self.recv_counter, counter + 1)
            return plaintext
        assert error is not None
        raise error
