"""
Encodage / décodage TLV8, tel qu'utilisé par le service Pairing HAP.

Format d'une entrée : [type: 1 octet][longueur: 1 octet][valeur: 0-255 octets]

Règle de fragmentation (spec HAP) : si une valeur logique dépasse 255 octets
(typiquement une clé publique SRP sur un groupe 3072 bits, qui fait 384
octets), elle est découpée en plusieurs entrées TLV consécutives portant le
MÊME tag, chacune de 255 octets maximum (la dernière pouvant être plus
courte, y compris vide). Au décodage, les valeurs consécutives portant le
même tag sont concaténées pour reconstituer la valeur logique.

Vérifié par recoupement avec pyhomekit (iterate_tvl + la logique de
concaténation dans HapCharacteristic._parse_response, qui fait
`val = attributes[key] + val` en cas de tag dupliqué).
"""

from typing import Dict, Iterable, List, Tuple

CHUNK_SIZE = 255


def encode(entries: Iterable[Tuple[int, bytes]]) -> bytes:
    """Encode une liste de tuples (tag, valeur) en TLV8.

    Une valeur vide produit quand même une entrée [tag, 0] (utile pour
    kTLVType_State ou pour "vider" un champ).
    """
    out = bytearray()
    for tag, value in entries:
        if not isinstance(value, (bytes, bytearray)):
            raise TypeError(f"La valeur pour le tag {tag} doit être bytes.")
        if len(value) == 0:
            out += bytes([tag & 0xFF, 0])
            continue
        offset = 0
        while offset < len(value):
            chunk = value[offset : offset + CHUNK_SIZE]
            out += bytes([tag & 0xFF, len(chunk)]) + bytes(chunk)
            offset += CHUNK_SIZE
    return bytes(out)


def encode_u8(tag: int, value: int) -> Tuple[int, bytes]:
    """Aide : construit une entrée (tag, valeur) pour un entier 8 bits."""
    return (tag, bytes([value & 0xFF]))


def decode(data: bytes) -> Dict[int, bytes]:
    """Décode des octets TLV8 en dict {tag: valeur reconstituée}.

    Les tags dupliqués consécutifs sont concaténés (fragmentation de valeur
    longue). L'ordre d'apparition n'est pas conservé dans le dict retourné ;
    utiliser decode_ordered() si l'ordre est important.
    """
    result: Dict[int, bytes] = {}
    for tag, value in decode_ordered(data):
        if tag in result:
            result[tag] += value
        else:
            result[tag] = value
    return result


def decode_ordered(data: bytes) -> List[Tuple[int, bytes]]:
    """Décode des octets TLV8 en liste ordonnée de (tag, valeur), sans
    fusionner les tags dupliqués (utile pour du debug)."""
    entries: List[Tuple[int, bytes]] = []
    i = 0
    n = len(data)
    while i < n:
        if i + 2 > n:
            raise ValueError("Trame TLV8 tronquée (en-tête incomplet).")
        tag = data[i]
        length = data[i + 1]
        value = data[i + 2 : i + 2 + length]
        if len(value) != length:
            raise ValueError("Trame TLV8 tronquée (valeur incomplète).")
        entries.append((tag, bytes(value)))
        i += 2 + length
    return entries
