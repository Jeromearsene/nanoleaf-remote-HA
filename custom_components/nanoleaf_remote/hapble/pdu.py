"""
Framing des PDU HAP-BLE : en-tête de requête/réponse, Control Field,
et fragmentation des écritures GATT trop longues.

Vérifié directement à partir du code source de pyhomekit (ble.py, classes
HapBlePduRequestHeader / HapBlePduResponseHeader / fragment_tlvs), qui
implémente ce même framing (avec bluepy comme transport, ici on porte la
logique vers bleak).

Control Field (1 octet), MSB -> LSB :
    bit7 : continuation ("ceci est un fragment de suite")
    bits6-2 : réservé, toujours 0
    bit1 : response (0 = requête, 1 = réponse)
    bit0 : réservé, toujours 0

En-tête de requête (premier fragment, 5 octets) :
    control_field(1) + op_code(1) + transaction_id(1) + cid(2, little-endian)
En-tête de requête (fragment de suite, 2 octets) :
    control_field(1) + transaction_id(1)

En-tête de réponse (3 octets) :
    control_field(1) + transaction_id(1) + status_code(1)
Si la réponse contient un corps, il est précédé de body_length (2 octets LE).

Taille max d'une écriture GATT unique pour ce protocole : 512 octets
(au-delà, fragmentation avec le bit "continuation").
"""

import random
from dataclasses import dataclass
from struct import pack, unpack
from typing import List, Tuple

MAX_PDU_LEN = 512


def new_transaction_id() -> int:
    """Génère un Transaction ID (TID) aléatoire sur 8 bits."""
    return random.SystemRandom().getrandbits(8)


def _control_field(continuation: bool, response: bool) -> int:
    bits = f"{int(continuation)}00000{int(response)}0"
    return int(bits, 2)


@dataclass
class RequestHeader:
    cid: int
    op_code: int
    transaction_id: int
    continuation: bool = False

    @property
    def control_field(self) -> int:
        return _control_field(self.continuation, response=False)

    def to_bytes(self) -> bytes:
        if self.continuation:
            return pack("<BB", self.control_field, self.transaction_id)
        return pack(
            "<BBB", self.control_field, self.op_code, self.transaction_id
        ) + pack("<H", self.cid)


@dataclass
class ResponseHeader:
    status_code: int
    transaction_id: int
    continuation: bool
    response: bool

    @classmethod
    def from_bytes(cls, data: bytes) -> "ResponseHeader":
        if len(data) < 3:
            raise ValueError(
                f"Réponse HAP-BLE trop courte pour contenir un en-tête "
                f"({len(data)} octet(s), 3 attendus au minimum)."
            )
        control_field, tid, status_code = unpack("<BBB", data[:3])
        bits = bin(control_field)[2:].zfill(8)[::-1]
        continuation = bits[7] == "1"
        response = bits[1] == "1"
        if bits[0] + bits[2:7] != "000000":
            raise ValueError(
                f"Control Field de réponse invalide : {bits[::-1]} "
                f"(bits réservés non nuls)."
            )
        return cls(
            status_code=status_code,
            transaction_id=tid,
            continuation=continuation,
            response=response,
        )


def build_request_fragments(
    cid: int, op_code: int, transaction_id: int, body: bytes = b""
) -> List[bytes]:
    """Construit la ou les trames à écrire en GATT pour une requête HAP-BLE.

    - Sans corps (ex : simple lecture) : une seule trame, l'en-tête seul,
      SANS préfixe de longueur (comportement HAP-BLE pour une requête sans
      corps).
    - Avec corps : en-tête + longueur (2 octets LE) + corps, fragmenté par
      blocs de MAX_PDU_LEN octets si nécessaire (bit continuation sur les
      fragments suivants).
    """
    if not body:
        header = RequestHeader(cid=cid, op_code=op_code, transaction_id=transaction_id)
        return [header.to_bytes()]

    fragments: List[bytes] = []
    continuation = False
    offset = 0
    total = len(body)
    while offset < total or (offset == 0 and total == 0):
        header = RequestHeader(
            cid=cid,
            op_code=op_code,
            transaction_id=transaction_id,
            continuation=continuation,
        )
        # Place disponible dans cette trame pour le corps.
        header_len = 2 if continuation else 5
        room = MAX_PDU_LEN - header_len - 2  # -2 pour le champ longueur
        chunk = body[offset : offset + room]
        fragments.append(header.to_bytes() + pack("<H", len(chunk)) + chunk)
        offset += len(chunk)
        continuation = True
        if offset >= total:
            break
    return fragments


def parse_first_response(
    data: bytes, expected_transaction_id: int
) -> Tuple[ResponseHeader, int, bytes]:
    """Parse le PREMIER fragment d'une réponse HAP-BLE.

    Retourne (header, corps_annonce_total, corps_partiel_recu). Si
    `corps_partiel_recu` est plus court que `corps_annonce_total`, l'appelant
    doit effectuer des lectures GATT supplémentaires (SANS nouvelle écriture)
    et les passer à `parse_continuation_fragment()` jusqu'à avoir assemblé
    la longueur annoncée — c'est la fragmentation PDU HAP-BLE (bit
    `continuation`), distincte de la fragmentation TLV8 générique (>255
    octets) et du mécanisme kTLVType_FragmentData utilisé côté kTLV pairing.

    Contrairement à une version antérieure de cette fonction, elle ne lève
    plus d'erreur si le corps reçu est plus court que celui annoncé : c'est
    le cas normal d'une réponse volumineuse (ex: M2 du Pair-Setup, qui
    contient une clé publique SRP de 384 octets) qui ne tient pas dans une
    seule trame.
    """
    header = ResponseHeader.from_bytes(data)
    if not header.response:
        raise ValueError("Control Field invalide : ceci n'est pas une réponse.")
    if header.transaction_id != expected_transaction_id:
        raise ValueError(
            f"Transaction ID inattendu : reçu {header.transaction_id}, "
            f"attendu {expected_transaction_id}."
        )
    if header.continuation:
        raise ValueError(
            "Premier fragment de réponse marqué comme continuation=True : "
            "inattendu (devrait être False pour un premier fragment)."
        )
    if len(data) <= 3:
        return header, 0, b""
    body_length = unpack("<H", data[3:5])[0]
    partial_body = data[5:]
    return header, body_length, partial_body


def parse_continuation_fragment(data: bytes, expected_transaction_id: int) -> bytes:
    """Parse un fragment de SUITE d'une réponse HAP-BLE (obtenu par une
    simple relecture GATT, sans nouvelle écriture). En-tête de 2 octets :
    control_field + transaction_id, puis les octets de continuation bruts
    (pas de champ de longueur répété — la longueur totale a été annoncée
    dans le premier fragment)."""
    if len(data) < 2:
        raise ValueError(
            f"Fragment de continuation trop court ({len(data)} octet(s), "
            f"2 attendus au minimum)."
        )
    control_field = data[0]
    tid = data[1]
    bits = bin(control_field)[2:].zfill(8)[::-1]
    continuation = bits[7] == "1"
    response = bits[1] == "1"
    if bits[0] + bits[2:7] != "000000":
        raise ValueError(
            f"Control Field de continuation invalide : {bits[::-1]} "
            f"(bits réservés non nuls)."
        )
    if not response or not continuation:
        raise ValueError(
            f"Fragment de continuation attendu (response=1, continuation=1), "
            f"reçu response={response}, continuation={continuation}."
        )
    if tid != expected_transaction_id:
        raise ValueError(
            f"Transaction ID inattendu dans le fragment de continuation : "
            f"reçu {tid}, attendu {expected_transaction_id}."
        )
    return data[2:]
