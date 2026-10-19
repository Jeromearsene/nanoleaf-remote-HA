"""
Persistance simple du résultat de Pair-Setup dans un fichier JSON local,
pour pouvoir faire Pair-Verify (Phase 3) sans ressaisir le code à 8
chiffres à chaque connexion.

⚠️  Le fichier contient controller_ltsk : c'est un secret (clé privée
Ed25519). Il joue le même rôle qu'un mot de passe d'appairage — à traiter
avec les mêmes précautions (ne pas le committer, ne pas le partager).
"""

import json
from base64 import b64decode, b64encode
from pathlib import Path

from .pairing import PairingResult

DEFAULT_PATH = Path(__file__).resolve().parent.parent / "pairing.json"


def save(result: PairingResult, path: Path = DEFAULT_PATH) -> None:
    data = {
        "controller_pairing_id": b64encode(result.controller_pairing_id).decode(),
        "controller_ltsk": b64encode(result.controller_ltsk).decode(),
        "controller_ltpk": b64encode(result.controller_ltpk).decode(),
        "accessory_pairing_id": b64encode(result.accessory_pairing_id).decode(),
        "accessory_ltpk": b64encode(result.accessory_ltpk).decode(),
    }
    path.write_text(json.dumps(data, indent=2))


def load(path: Path = DEFAULT_PATH) -> PairingResult:
    data = json.loads(path.read_text())
    return PairingResult(
        controller_pairing_id=b64decode(data["controller_pairing_id"]),
        controller_ltsk=b64decode(data["controller_ltsk"]),
        controller_ltpk=b64decode(data["controller_ltpk"]),
        accessory_pairing_id=b64decode(data["accessory_pairing_id"]),
        accessory_ltpk=b64decode(data["accessory_ltpk"]),
    )


def exists(path: Path = DEFAULT_PATH) -> bool:
    return path.exists()
