"""
Phase 2 — Pair-Setup complet (SRP-6a + Ed25519) contre la Nanoleaf Remote.

Ce script :
  1. scanne et se connecte à la Remote (comme en Phase 1) ;
  2. exécute l'échange M1 -> M6 du Pair-Setup HAP, avec le code à 8
     chiffres fourni ;
  3. si succès : sauvegarde le résultat (nos clés + l'identité de
     l'accessoire) dans pairing.json, pour Pair-Verify (Phase 3).

⚠️  IMPORTANT sur la fenêtre de connexion courte (observée en Phase 1,
~1 seconde) : Pair-Setup demande 3 aller-retours GATT (M1/M2, M3/M4,
M5/M6), potentiellement plus lents qu'une simple lecture. Si l'accessoire
coupe la connexion en plein milieu, le script échouera avec une erreur
BleakError — dans ce cas, relance simplement (aucun état n'est corrompu
côté accessoire tant que M6 n'a pas été reçu avec succès).

Usage :
    python test_phase2.py                  # demande le code interactivement
    python test_phase2.py 123-45-678        # ou en argument
"""

import asyncio
import logging
import secrets
import sys

from hapble import pairing, pairing_store
from hapble.transport import HapBleAccessory, HapBleError

# Réutilise la logique de découverte de la Phase 1.
from test_phase1 import discover_remote  # noqa: E402

LOG_LEVEL = logging.INFO


def _get_or_create_controller_id() -> bytes:
    """Notre identifiant de controller doit être STABLE d'une exécution à
    l'autre (c'est notre "identité" du point de vue de l'accessoire, une
    fois appairés). On le génère une fois et on le réutilise si un
    pairing.json existe déjà avec un appairage précédent ; sinon on en
    crée un nouveau (ex: un UUID-like aléatoire de 36 octets)."""
    if pairing_store.exists():
        try:
            existing = pairing_store.load()
            return existing.controller_pairing_id
        except Exception:
            pass
    # Format libre côté HAP (juste un identifiant unique) : on prend un
    # UUID textuel, comme le font la plupart des implémentations.
    import uuid

    return str(uuid.uuid4()).encode("ascii")


async def main() -> int:
    logging.basicConfig(
        level=LOG_LEVEL,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    if len(sys.argv) > 1:
        setup_code = sys.argv[1]
    else:
        setup_code = input(
            "Code d'appairage à 8 chiffres (format XXX-XX-XXX ou 8 chiffres) : "
        ).strip()

    print("=" * 70)
    print("  Phase 2 — Pair-Setup (SRP-6a + Ed25519)")
    print("=" * 70)
    print()

    try:
        device = await discover_remote()
    except RuntimeError as exc:
        print(f"!!! {exc}")
        return 1

    controller_pairing_id = _get_or_create_controller_id()
    print(f"Identifiant controller utilisé : {controller_pairing_id.decode()}")
    print()

    try:
        async with HapBleAccessory(device) as accessory:
            char = accessory.pair_setup_characteristic()
            print("Échange Pair-Setup en cours (M1 -> M6)...")
            result = await pairing.pair_setup(char, setup_code, controller_pairing_id)

        print()
        print(">>> SUCCÈS : appairage complet !")
        print(
            f"    Identifiant accessoire : {result.accessory_pairing_id.decode(errors='replace')}"
        )
        print(f"    LTPK accessoire (hex)  : {result.accessory_ltpk.hex()}")
        print()

        pairing_store.save(result)
        print(f"Résultat sauvegardé dans : {pairing_store.DEFAULT_PATH}")
        print(
            "(nécessaire pour Pair-Verify, Phase 3 — ne pas partager ce "
            "fichier, il contient notre clé privée.)"
        )
        return 0

    except pairing.PairSetupError as exc:
        print()
        print(f"!!! Échec du Pair-Setup : {exc}")
        return 1

    except HapBleError as exc:
        print()
        print(f"!!! Erreur HAP-BLE : {exc}")
        return 1

    except Exception as exc:  # pylint: disable=broad-except
        print()
        print(f"!!! Erreur inattendue : {type(exc).__name__}: {exc}")
        print("    Si c'est un BleakError lié à une déconnexion en plein")
        print("    échange, relance simplement le script — rien n'est")
        print("    persisté tant que M6 n'a pas réussi.")
        return 1


def cli() -> None:
    """Point d'entrée synchrone, pour `poetry run` (voir pyproject.toml)."""
    sys.exit(asyncio.run(main()))


if __name__ == "__main__":
    cli()
