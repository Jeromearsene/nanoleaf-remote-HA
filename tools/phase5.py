"""
Phase 5 — Écoute hybride : abonnement aux indications GATT (au cas où
l'accessoire les enverrait un jour avec un contenu exploitable) COMBINÉ à
un sondage léger régulier (~1.5s) des 12 instances.

Pourquoi l'hybride, et pas les indications seules : testé en conditions
réelles, l'abonnement seul ne suffit pas — cet accessoire coupe la
connexion s'il la juge inactive (déjà observé en Phase 1), et rester
silencieusement à l'écoute compte comme de l'inactivité à ses yeux. Le
sondage sert donc un double rôle : maintenir la connexion "vivante", ET
rattraper tout événement qu'une indication aurait manqué (latence bornée
à ~1.5s dans le pire cas).

Pour chaque indication reçue malgré tout (best-effort, latence plus
faible si ça marche) :
  - le contenu ressemble à une PDU HAP-BLE chiffrée valide -> affiché
    directement (déchiffré) ;
  - sinon -> une relecture explicite est faite juste après.

Usage :
    python -m tools.phase5 [durée_en_secondes]   (défaut : 30s)

Pendant l'exécution : fais tourner la Remote plusieurs fois, vers
différentes faces, pour voir plusieurs événements arriver.
"""

import asyncio
import logging
import sys

from hapble import pair_verify, pairing_store
from hapble.ble_session import BleSecureSession
from hapble.transport import HapBleAccessory
from tools.phase1 import discover_remote  # noqa: E402

LOG_LEVEL = logging.DEBUG
DEFAULT_LISTEN_SECONDS = 30.0


async def main() -> int:
    logging.basicConfig(
        level=LOG_LEVEL,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    listen_seconds = float(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_LISTEN_SECONDS

    print("=" * 70)
    print("  Phase 5 — Écoute des indications ProgrammableSwitchEvent")
    print("=" * 70)
    print()

    if not pairing_store.exists():
        print(f"!!! Aucun appairage trouvé ({pairing_store.DEFAULT_PATH}).")
        print("    Lance d'abord phase2.")
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
                f"{len(switch_chars)} instance(s) trouvée(s). Abonnement "
                f"aux indications..."
            )

            def on_event(index: int, decoded, raw: bytes) -> None:
                if decoded is not None:
                    print(
                        f"  >>> ÉVÉNEMENT [face {index + 1}] "
                        f"(depuis l'indication) : {decoded.hex(' ')}"
                    )
                else:
                    print(
                        f"  >>> Indication reçue [face {index + 1}] "
                        f"(brute, {len(raw)} octet(s)) — relecture..."
                    )
                    asyncio.create_task(_read_after_event(switch_chars[index], index))

            confirmed = await accessory.subscribe_switch_events(switch_chars, on_event)
            print(
                f">>> {confirmed}/{len(switch_chars)} abonnement(s) confirmé(s) "
                f"en mode 'indicate' (voir logs DEBUG ci-dessus pour le détail "
                f"par instance)."
            )

            print(
                f">>> À l'écoute pendant {listen_seconds:.0f}s — fais "
                f"tourner la Remote maintenant (plusieurs faces si tu veux)."
            )
            print(
                ">>> (sondage léger toutes les ~1.5s en parallèle : la "
                "Remote coupe la connexion si elle la juge inactive — "
                "voir Phase 1 — donc on entretient le lien tout en se "
                "donnant un filet de sécurité si une indication est ratée.)"
            )
            print()

            poll_interval = 1.5
            elapsed = 0.0
            while elapsed < listen_seconds:
                await asyncio.sleep(poll_interval)
                elapsed += poll_interval
                for i, char in enumerate(switch_chars):
                    try:
                        value = await char.read_value()
                    except Exception as exc:  # pylint: disable=broad-except
                        print()
                        print(
                            f"!!! Connexion perdue après {elapsed:.1f}s de "
                            f"sondage ({type(exc).__name__}: {exc})."
                        )
                        return 0
                    if value and value != b"null":
                        print(
                            f"  >>> ÉVÉNEMENT [face {i + 1}] (sondage) : "
                            f"{value.hex(' ')}"
                        )

            print()
            print(f">>> Fin de l'écoute ({elapsed:.0f}s tenues sans coupure).")
            return 0

    except pair_verify.PairVerifyError as exc:
        print()
        print(f"!!! Échec de Pair-Verify : {exc}")
        return 1

    except Exception as exc:  # pylint: disable=broad-except
        print()
        print(f"!!! Erreur inattendue : {type(exc).__name__}: {exc}")
        return 1


async def _read_after_event(char, index: int) -> None:
    try:
        value = await char.read_value()
        text = value.hex(" ") if value else "(vide)"
        print(f"      -> relecture [face {index + 1}] : {text}")
    except Exception as exc:  # pylint: disable=broad-except
        print(f"      -> échec de relecture [face {index + 1}] : {exc}")


def cli() -> None:
    """Point d'entrée synchrone, pour `poetry run` (voir pyproject.toml)."""
    sys.exit(asyncio.run(main()))


if __name__ == "__main__":
    cli()
