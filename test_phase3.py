"""
Phase 3 — Pair-Verify contre la Nanoleaf Remote, en utilisant l'appairage
déjà établi (pairing.json, produit par test_phase2.py).

Ne redemande PAS le code à 8 chiffres : c'est justement l'intérêt de
Pair-Verify. Si pairing.json n'existe pas ou est invalide, ce script
s'arrête avec un message clair plutôt que de planter.

À l'issue d'un Pair-Verify réussi, ce script affiche les clés de session
(read_key/write_key) — la Phase 4 (lecture de ProgrammableSwitchEvent avec
ces clés) reste à construire : le format exact des échanges GATT chiffrés
qui suivent M4 n'a pas encore été vérifié aussi précisément que le reste de
ce projet.

Usage :
    python test_phase3.py
"""

import asyncio
import logging
import sys

from hapble import pair_verify, pairing_store
from hapble.transport import HapBleAccessory, HapBleError
from test_phase1 import discover_remote  # noqa: E402

LOG_LEVEL = logging.INFO


async def main() -> int:
    logging.basicConfig(
        level=LOG_LEVEL,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    print("=" * 70)
    print("  Phase 3 — Pair-Verify (session chiffrée à partir de l'appairage)")
    print("=" * 70)
    print()

    if not pairing_store.exists():
        print(f"!!! Aucun appairage trouvé ({pairing_store.DEFAULT_PATH}).")
        print("    Lance d'abord test_phase2.py pour appairer la Remote.")
        return 1

    pairing = pairing_store.load()
    print(
        f"Appairage chargé : accessoire "
        f"{pairing.accessory_pairing_id.decode(errors='replace')}"
    )
    print()

    try:
        device = await discover_remote()
    except RuntimeError as exc:
        print(f"!!! {exc}")
        return 1

    print()

    try:
        async with HapBleAccessory(device) as accessory:
            char = accessory.pair_verify_characteristic()
            print("Échange Pair-Verify en cours (M1 -> M4)...")
            session_keys = await pair_verify.pair_verify(char, pairing)

        print()
        print(">>> SUCCÈS : session vérifiée et chiffrée établie !")
        print(f"    read_key  (hex) : {session_keys.read_key.hex()}")
        print(f"    write_key (hex) : {session_keys.write_key.hex()}")
        print()
        print(">>> Prochaine étape (Phase 4) : utiliser ces clés pour lire")
        print(">>> ProgrammableSwitchEvent en chiffré.")
        return 0

    except pair_verify.PairVerifyError as exc:
        print()
        print(f"!!! Échec de Pair-Verify : {exc}")
        return 1

    except HapBleError as exc:
        print()
        print(f"!!! Erreur HAP-BLE : {exc}")
        return 1

    except Exception as exc:  # pylint: disable=broad-except
        print()
        print(f"!!! Erreur inattendue : {type(exc).__name__}: {exc}")
        print("    Si c'est un BleakError lié à une déconnexion, relance")
        print("    simplement le script.")
        return 1


def cli() -> None:
    """Point d'entrée synchrone, pour `poetry run` (voir pyproject.toml)."""
    sys.exit(asyncio.run(main()))


if __name__ == "__main__":
    cli()
