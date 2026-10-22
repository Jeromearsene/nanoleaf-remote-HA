"""
bridge.py — service tournant en continu qui publie les événements de
rotation de la Nanoleaf Remote vers MQTT, au format découverte
automatique de Home Assistant (intégration MQTT "event").

Reprend exactement la logique validée en Phase 5 (indications + sondage de
maintien), mais en boucle indéfiniment avec reconnexion automatique au lieu
de s'arrêter après une durée fixe — c'est la différence entre un script de
test et un service.

Configuration (environment variables, all optional — can also be set in a
`.env` file at the project root; see `.env.example`):
    MQTT_HOST       (default: localhost)
    MQTT_PORT       (default: 1883)
    MQTT_USERNAME   (default: no authentication)
    MQTT_PASSWORD
    FACE_MAP        (default: 1,2,...,12; table given by `poetry run calibrate`)

Usage:
    poetry run bridge
"""

import asyncio
import logging
import os
import sys

import aiomqtt
from dotenv import load_dotenv

from hapble import facemap, mqtt_bridge, pair_verify, pairing_store
from hapble.ble_session import BleSecureSession
from hapble.transport import HapBleAccessory
from test_phase1 import discover_remote  # noqa: E402

load_dotenv()  # no-op if there's no .env file — env vars still take priority

LOG_LEVEL = logging.INFO
POLL_INTERVAL_SECONDS = 1.5
RECONNECT_DELAY_SECONDS = 5.0

logger = logging.getLogger("bridge")


def _mqtt_config_from_env() -> dict:
    return {
        "hostname": os.environ.get("MQTT_HOST", "localhost"),
        "port": int(os.environ.get("MQTT_PORT", "1883")),
        "username": os.environ.get("MQTT_USERNAME") or None,
        "password": os.environ.get("MQTT_PASSWORD") or None,
    }


async def _ble_session(mqtt_client: aiomqtt.Client, pairing) -> None:
    """Une session BLE complète : connexion, Pair-Verify, puis écoute
    (indications + sondage) jusqu'à déconnexion. Lève une exception si
    quoi que ce soit échoue — l'appelant (run()) gère la reconnexion."""
    device = await discover_remote()

    async with HapBleAccessory(device) as accessory:
        char_verify = accessory.pair_verify_characteristic()
        logger.info("Pair-Verify en cours...")
        session_keys = await pair_verify.pair_verify(char_verify, pairing)
        logger.info("Session chiffrée établie.")

        session = BleSecureSession(
            read_key=session_keys.read_key,
            write_key=session_keys.write_key,
        )
        switch_chars = accessory.programmable_switch_event_characteristics(
            session=session
        )
        logger.info("%d instance(s) ProgrammableSwitchEvent.", len(switch_chars))

        face_map = facemap.parse_face_map(os.environ.get("FACE_MAP"))

        async def publish_event(face_index: int) -> None:
            await mqtt_client.publish(
                mqtt_bridge.STATE_TOPIC,
                mqtt_bridge.event_state_payload(face_index, face_map),
            )
            logger.info("Événement publié : face %d", face_map[face_index])

        def on_event(index: int, decoded, raw: bytes) -> None:
            # L'indication elle-même est vide en pratique (confirmé en
            # Phase 5) : on relit pour obtenir la vraie valeur.
            async def handle():
                try:
                    value = await switch_chars[index].read_value()
                except Exception:  # pylint: disable=broad-except
                    return
                if value and value != b"null":
                    await publish_event(index)

            asyncio.create_task(handle())

        confirmed = await accessory.subscribe_switch_events(switch_chars, on_event)
        logger.info(
            "%d/%d abonnement(s) confirmé(s) en mode indicate.",
            confirmed,
            len(switch_chars),
        )

        # Boucle de sondage indéfinie : sert à la fois de filet de
        # sécurité (au cas où une indication serait manquée) et de trafic
        # de maintien (l'accessoire déconnecte une liaison qu'il juge
        # inactive — voir Phase 1 et Phase 5).
        while True:
            await asyncio.sleep(POLL_INTERVAL_SECONDS)
            for i, char in enumerate(switch_chars):
                value = await char.read_value()  # lève si déconnecté
                if value and value != b"null":
                    await publish_event(i)


async def run() -> None:
    logging.basicConfig(
        level=LOG_LEVEL,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    if not pairing_store.exists():
        logger.error(
            "Aucun appairage trouvé (%s). Lance d'abord `poetry run phase2`.",
            pairing_store.DEFAULT_PATH,
        )
        sys.exit(1)
    pairing = pairing_store.load()

    mqtt_config = _mqtt_config_from_env()
    logger.info(
        "Connexion MQTT à %s:%s ...", mqtt_config["hostname"], mqtt_config["port"]
    )

    async with aiomqtt.Client(**mqtt_config) as mqtt_client:
        logger.info("Connecté à MQTT.")
        device_identifier = pairing.accessory_pairing_id.decode(errors="replace")
        await mqtt_client.publish(
            mqtt_bridge.DISCOVERY_TOPIC,
            mqtt_bridge.discovery_payload(device_identifier),
        )
        logger.info(
            "Configuration de découverte Home Assistant publiée (%s).",
            mqtt_bridge.DISCOVERY_TOPIC,
        )

        while True:
            try:
                await _ble_session(mqtt_client, pairing)
            except Exception as exc:  # pylint: disable=broad-except
                logger.warning(
                    "Session BLE interrompue (%s: %s) — reconnexion dans %.0fs.",
                    type(exc).__name__,
                    exc,
                    RECONNECT_DELAY_SECONDS,
                )
                await asyncio.sleep(RECONNECT_DELAY_SECONDS)


def cli() -> None:
    """Point d'entrée synchrone, pour `poetry run` (voir pyproject.toml)."""
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    cli()
