"""
calibrate.py — outil de calibration interactif : pour chaque essai, TU
indiques sur quelle face tu vas tourner, PUIS tu tournes, et le script
confirme (ou contredit) ce qui a été réellement détecté.

Jusqu'ici, la correspondance "index dans la liste des 12 instances =
numéro de face - 1" n'avait été vérifiée que sur 2 points de données
(faces 2 et 9, Phase 4) — cet outil permet de la vérifier explicitement,
face par face, autant de fois que voulu, avec un décompte final clair
(combien de faces confirmées, lesquelles ne correspondent pas si jamais).

Réutilise exactement la même logique de connexion/écoute que la Phase 5
(indications + sondage de maintien), mais les événements détectés sont
comparés à ce que tu annonces au lieu d'être simplement affichés.

Usage :
    poetry run calibrate
"""

import asyncio
import logging
import sys

from hapble import pair_verify, pairing_store
from hapble.ble_session import BleSecureSession
from hapble.transport import HapBleAccessory
from test_phase1 import discover_remote  # noqa: E402

LOG_LEVEL = logging.WARNING  # peu de bruit : on veut voir le dialogue clairement
POLL_INTERVAL_SECONDS = 1.5
EVENT_TIMEOUT_SECONDS = 20.0


async def _poll_loop(switch_chars, queue: asyncio.Queue) -> None:
    """Tourne indéfiniment en arrière-plan : sert de filet de sécurité ET
    de trafic de maintien (voir Phase 5) — pousse chaque face active
    détectée dans `queue`."""
    while True:
        await asyncio.sleep(POLL_INTERVAL_SECONDS)
        for i, char in enumerate(switch_chars):
            value = await char.read_value()
            if value and value != b"null":
                await queue.put(i)


def summarize(results: list[tuple[int, int]]) -> str:
    """Construit le texte de résumé à partir d'une liste de (attendu,
    détecté). Extrait en fonction séparée pour pouvoir être testée sans
    dépendre du matériel ni de l'interaction utilisateur."""
    lines = []
    if not results:
        lines.append("Aucun essai complété.")
        return "\n".join(lines)

    ok = [r for r in results if r[0] == r[1]]
    bad = [r for r in results if r[0] != r[1]]
    lines.append(f"{len(ok)}/{len(results)} essai(s) confirmé(s) correctement.")
    if bad:
        lines.append("")
        lines.append("Désaccords détectés :")
        for expected, detected in bad:
            lines.append(f"  - attendu face {expected}, détecté face {detected}")
        lines.append("")
        lines.append(">>> La correspondance simple 'index = face - 1' ne tient")
        lines.append(">>> apparemment pas partout — regardons ça ensemble avant de")
        lines.append(">>> se fier au pont MQTT pour de vraies automatisations.")
    else:
        lines.append("")
        lines.append(">>> Correspondance confirmée sur toutes les faces testées.")
    return "\n".join(lines)


async def main() -> int:
    logging.basicConfig(
        level=LOG_LEVEL,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    print("=" * 70)
    print("  Calibration — vérification face par face")
    print("=" * 70)
    print()
    print("Pour chaque essai : indique le numéro de la face (1-12) sur")
    print("laquelle tu vas tourner la Remote, PUIS tourne-la juste après.")
    print("Tape 'q' à la place d'un numéro pour arrêter et voir le résumé.")
    print()

    if not pairing_store.exists():
        print(f"!!! Aucun appairage trouvé ({pairing_store.DEFAULT_PATH}).")
        print("    Lance d'abord `poetry run phase2`.")
        return 1
    pairing = pairing_store.load()

    try:
        device = await discover_remote()
    except RuntimeError as exc:
        print(f"!!! {exc}")
        return 1

    print()

    results: list[tuple[int, int]] = []  # (attendu, détecté)

    try:
        async with HapBleAccessory(device) as accessory:
            char_verify = accessory.pair_verify_characteristic()
            print("Échange Pair-Verify en cours...")
            session_keys = await pair_verify.pair_verify(char_verify, pairing)
            print(">>> Session chiffrée établie.\n")

            session = BleSecureSession(
                read_key=session_keys.read_key,
                write_key=session_keys.write_key,
            )
            switch_chars = accessory.programmable_switch_event_characteristics(
                session=session
            )

            queue: asyncio.Queue = asyncio.Queue()

            def on_event(index: int, decoded, raw: bytes) -> None:
                asyncio.create_task(queue.put(index))

            confirmed = await accessory.subscribe_switch_events(switch_chars, on_event)
            poll_task = asyncio.create_task(_poll_loop(switch_chars, queue))
            print(
                f"({confirmed}/{len(switch_chars)} abonnements confirmés, "
                f"sondage de maintien actif en arrière-plan.)\n"
            )

            try:
                while True:
                    raw_input = await asyncio.to_thread(
                        input, "Numéro de face à tester (1-12, ou 'q') : "
                    )
                    raw_input = raw_input.strip().lower()
                    if raw_input == "q":
                        break
                    try:
                        expected_face = int(raw_input)
                        if not (1 <= expected_face <= len(switch_chars)):
                            raise ValueError
                    except ValueError:
                        print(
                            f"  (entrée non reconnue — un nombre entre 1 et "
                            f"{len(switch_chars)}, ou 'q')"
                        )
                        continue

                    # Purge les événements laissés par un essai précédent
                    # (ex: une rotation détectée après coup, ou l'usager qui
                    # a tourné avant d'avoir tapé son numéro).
                    while not queue.empty():
                        queue.get_nowait()

                    print(f"  -> tourne maintenant vers la face {expected_face}...")
                    try:
                        detected_index = await asyncio.wait_for(
                            queue.get(), timeout=EVENT_TIMEOUT_SECONDS
                        )
                    except asyncio.TimeoutError:
                        print(
                            f"  ⏱ Rien détecté en {EVENT_TIMEOUT_SECONDS:.0f}s — "
                            f"réessaie ce numéro (pas compté dans le résumé)."
                        )
                        continue

                    detected_face = detected_index + 1
                    results.append((expected_face, detected_face))
                    if detected_face == expected_face:
                        print(f"  ✅ Face {expected_face} confirmée.\n")
                    else:
                        print(
                            f"  ❌ DÉSACCORD : attendu face {expected_face}, "
                            f"détecté face {detected_face}.\n"
                        )
            finally:
                poll_task.cancel()
                try:
                    await poll_task
                except asyncio.CancelledError:
                    pass

    except pair_verify.PairVerifyError as exc:
        print(f"\n!!! Échec de Pair-Verify : {exc}")
        return 1
    except Exception as exc:  # pylint: disable=broad-except
        print(f"\n!!! Erreur inattendue : {type(exc).__name__}: {exc}")
        print(
            "    Si la connexion a été perdue, relance simplement — les "
            "essais déjà validés ci-dessus restent valables."
        )

    # --- Résumé -------------------------------------------------------
    print()
    print("=" * 70)
    print("  Résumé de la calibration")
    print("=" * 70)
    print(summarize(results))
    return 0


def cli() -> None:
    """Point d'entrée synchrone, pour `poetry run` (voir pyproject.toml)."""
    sys.exit(asyncio.run(main()))


if __name__ == "__main__":
    cli()
