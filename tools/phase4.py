"""
Phase 4 — Pair-Verify puis lecture CHIFFRÉE de ProgrammableSwitchEvent, sur
chacune des 8 instances du service Stateless Programmable Switch repérées
en Phase 1 (probablement une par face/position de la Remote).

Important sur la fenêtre de connexion courte (voir Phase 1, ~1 seconde) :
chaque caractéristique lue demande sa propre lecture de CID (descripteur)
PLUS l'écriture/lecture de la requête elle-même — largement plus que ce qui
tient dans la fenêtre observée pour les 8 d'un coup. Ce script continue donc
après un échec sur une caractéristique plutôt que d'abandonner : les
résultats partiels sont normaux et utiles.

Si TOUTES les lectures reviennent vides (pas d'erreur, mais aucune valeur) :
c'est probablement parce que ces caractéristiques sont d'abord conçues pour
des indications BLE (souscription) plutôt que des lectures directes — la
propriété GATT observée en Phase 1 incluait "indicate". Prochaine étape dans
ce cas : souscrire (écrire le descripteur CCCD 0x2902) et écouter les
notifications pendant qu'on tourne la Remote — pas encore implémenté ici.

Usage :
    python -m tools.phase4
"""

import asyncio
import logging
import sys

from hapble import pair_verify, pairing_store
from hapble.ble_session import BleSecureSession
from hapble.transport import HapBleAccessory, HapBleError
from tools.phase1 import discover_remote  # noqa: E402

LOG_LEVEL = logging.INFO


async def main() -> int:
    logging.basicConfig(
        level=LOG_LEVEL,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    print("=" * 70)
    print("  Phase 4 — Lecture chiffrée de ProgrammableSwitchEvent")
    print("=" * 70)
    print()

    if not pairing_store.exists():
        print(f"!!! Aucun appairage trouvé ({pairing_store.DEFAULT_PATH}).")
        print("    Lance d'abord tools/phase2.py.")
        return 1

    pairing = pairing_store.load()

    try:
        device = await discover_remote()
    except RuntimeError as exc:
        print(f"!!! {exc}")
        return 1

    print()

    try:
        async with HapBleAccessory(device) as accessory:
            char_verify = accessory.pair_verify_characteristic()
            print("Échange Pair-Verify en cours (M1 -> M4)...")
            session_keys = await pair_verify.pair_verify(char_verify, pairing)
            print(">>> Session chiffrée établie.")
            print()

            session = BleSecureSession(
                read_key=session_keys.read_key,
                write_key=session_keys.write_key,
            )

            switch_chars = accessory.programmable_switch_event_characteristics(
                session=session
            )
            print(
                f"{len(switch_chars)} instance(s) de "
                f"ProgrammableSwitchEvent trouvée(s)."
            )
            print()

            any_value = False
            for i, char in enumerate(switch_chars):
                try:
                    value = await char.read_value()
                    any_value = True
                    print(f"  [{i}] {value.hex(' ') if value else '(vide)'}")
                except HapBleError as exc:
                    print(f"  [{i}] Erreur HAP-BLE : {exc}")
                except Exception as exc:  # pylint: disable=broad-except
                    print(
                        f"  [{i}] Arrêt ({type(exc).__name__}: {exc}) — "
                        f"probablement la fenêtre de connexion qui s'est "
                        f"fermée ; résultats ci-dessus tout de même valides."
                    )
                    break

            print()
            if not any_value:
                print(">>> Aucune valeur non-vide obtenue. C'est attendu si")
                print(">>> ces caractéristiques ne s'activent que par")
                print(">>> indication BLE (souscription) plutôt que lecture")
                print(">>> directe — prochaine étape à explorer.")
            return 0

    except pair_verify.PairVerifyError as exc:
        print()
        print(f"!!! Échec de Pair-Verify : {exc}")
        return 1

    except Exception as exc:  # pylint: disable=broad-except
        print()
        print(f"!!! Erreur inattendue : {type(exc).__name__}: {exc}")
        return 1


def cli() -> None:
    """Point d'entrée synchrone, pour `poetry run` (voir pyproject.toml)."""
    sys.exit(asyncio.run(main()))


if __name__ == "__main__":
    cli()
