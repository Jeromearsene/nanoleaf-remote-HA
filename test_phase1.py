"""
Phase 1 — validation du transport/framing HAP-BLE, SANS aucune crypto.

Ce script :
  1. se connecte en GATT à la Nanoleaf Remote (bleak, fonctionne sous
     Windows) ;
  2. liste les services/caractéristiques découverts (pour vérifier que le
     service Pairing HomeKit est bien présent à l'UUID attendu) ;
  3. effectue une vraie requête HAP-BLE (Characteristic Read) sur la
     caractéristique "Pairing Features", qui est lisible SANS pairing ;
  4. affiche le résultat.

Si cette étape fonctionne, ça confirme que :
  - bleak arrive à parler GATT avec la Remote depuis Windows ;
  - notre décodage du Control Field / en-tête de PDU HAP-BLE est correct ;
  - notre encodage/décodage TLV8 est correct ;
  - le motif "écrire la requête, puis relire la caractéristique" fonctionne
    bien avec ce firmware précis.

Si ça fonctionne, l'étape suivante (Phase 2) sera d'implémenter Pair-Setup
(SRP-6a) en réutilisant exactement cette même couche de transport.

Note plateforme (important) : sous macOS, CoreBluetooth ne donne jamais la
vraie adresse MAC aux applications (par confidentialité) — bleak expose à
la place un UUID généré localement par la machine, qui ne correspond à rien
d'autre et n'est valable que sur CETTE machine. Se connecter directement à
une adresse MAC codée en dur (ex: capturée sous Windows/Linux) ne peut donc
PAS fonctionner sous macOS. Pour rester portable, ce script ne se connecte
plus par adresse fixe : il SCANNE et identifie la Remote par un contenu
stable de ses annonces BLE (son "Device ID" HAP, identifié dans le rapport
d'analyse initial), quel que soit l'OS.

Usage :
    pip install bleak
    python test_phase1.py

Sous macOS, si le scan ne trouve rien du tout (aucun appareil, pas
seulement la Remote), vérifier Réglages Système -> Confidentialité et
sécurité -> Bluetooth : le terminal (Terminal.app, iTerm, ou "Code Helper"
pour VSCode) doit y être coché.
"""

import asyncio
import logging
import sys

from bleak import BleakScanner
from bleak.backends.device import BLEDevice

from hapble.transport import HapBleAccessory, HapBleError

# Company ID Apple, utilisé par les annonces HomeKit.
APPLE_COMPANY_ID = 76

# Device ID stable identifié dans les trames "06" et "11" du rapport
# d'analyse BLE initial (offset 3 dans la trame 06, offset 2 dans la 11).
# C'est ce contenu, pas l'adresse BLE, qui identifie la Remote de façon
# fiable et portable entre systèmes d'exploitation.
KNOWN_DEVICE_ID = bytes.fromhex("d6bd09c0321d")

DISCOVERY_TIMEOUT_SECONDS = 15.0

# Passer à logging.DEBUG pour voir chaque trame écrite/lue en hexa.
LOG_LEVEL = logging.INFO


async def discover_remote(timeout: float = DISCOVERY_TIMEOUT_SECONDS) -> BLEDevice:
    """Scanne et retourne le BLEDevice de la Nanoleaf Remote, identifiée
    par son Device ID stable (pas par son adresse, non portable sous
    macOS)."""
    print(
        f"Scan BLE en cours (jusqu'à {timeout:.0f}s)... "
        f"pense à faire tourner légèrement la Remote pour la réveiller."
    )

    found = asyncio.get_running_loop().create_future()

    def on_detection(device: BLEDevice, advertisement_data) -> None:
        if found.done():
            return
        data = advertisement_data.manufacturer_data.get(APPLE_COMPANY_ID)
        if data and KNOWN_DEVICE_ID in bytes(data):
            found.set_result(device)

    async with BleakScanner(detection_callback=on_detection):
        try:
            device = await asyncio.wait_for(found, timeout=timeout)
        except asyncio.TimeoutError:
            raise RuntimeError(
                "Aucun appareil correspondant au Device ID connu n'a été "
                "détecté pendant le scan. Vérifications possibles :\n"
                '    - la Remote est-elle à portée et "réveillée" '
                "(bouge-la un peu) ?\n"
                "    - sous macOS : Réglages Système -> Confidentialité et "
                "sécurité -> Bluetooth -> le terminal est-il coché ?\n"
                "    - le Bluetooth de cette machine est-il bien activé ?"
            ) from None
    print(
        f"Remote trouvée : {device.name or '(sans nom)'} "
        f"[identifiant bleak: {device.address}]"
    )
    return device


async def main() -> int:
    logging.basicConfig(
        level=LOG_LEVEL,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    print("=" * 70)
    print("  Phase 1 — Test du transport HAP-BLE (bleak) sur la Remote")
    print("=" * 70)
    print()

    try:
        device = await discover_remote()
    except RuntimeError as exc:
        print()
        print(f"!!! {exc}")
        return 1

    print()

    try:
        async with HapBleAccessory(device) as accessory:
            # On tire en premier : l'accessoire coupe la connexion très vite
            # (~1s observé), donc toute impression de diagnostic AVANT la
            # vraie requête grignote une fenêtre déjà courte.
            print("-" * 70)
            print("Lecture de Pairing Features (requête HAP-BLE réelle)")
            print("-" * 70)
            features = await accessory.read_pairing_features()
            print(f"Pairing Features = 0x{features:02x} ({features:#010b})")
            print()
            print(">>> SUCCÈS : le framing HAP-BLE fonctionne avec cet appareil.")
            print(">>> On peut passer à la Phase 2 (Pair-Setup / SRP).")

            # Diagnostic optionnel, APRÈS coup : si la connexion tient encore.
            try:
                print()
                print("-" * 70)
                print("Services/caractéristiques découverts (info) :")
                print("-" * 70)
                await accessory.list_services()
            except Exception:
                print(
                    "(connexion coupée avant d'avoir pu tout lister — sans "
                    "importance, on a déjà notre réponse ci-dessus.)"
                )

            return 0

    except HapBleError as exc:
        print()
        print(f"!!! L'accessoire a répondu avec une erreur HAP-BLE : {exc}")
        print("    (Ça reste une bonne nouvelle : le framing des trames a")
        print("     fonctionné, l'accessoire a compris et répondu — il")
        print("     signale juste un statut d'erreur.)")
        return 1

    except RuntimeError as exc:
        print()
        print(f"!!! Erreur : {exc}")
        print("    Vérifie que le service Pairing HomeKit (UUID 00000055-...)")
        print("    apparaît bien dans la liste des services ci-dessus. Si ce")
        print("    n'est pas le cas, ce n'est peut-être pas le bon appareil,")
        print("    ou son firmware n'expose pas HomeKit sur cette interface.")
        return 1

    except Exception as exc:  # pylint: disable=broad-except
        print()
        print(f"!!! Erreur inattendue : {type(exc).__name__}: {exc}")
        print("    Relance avec LOG_LEVEL = logging.DEBUG en haut de ce")
        print("    fichier pour voir le détail des trames échangées.")
        return 1


def cli() -> None:
    """Point d'entrée synchrone, pour `poetry run` (voir pyproject.toml)."""
    sys.exit(asyncio.run(main()))


if __name__ == "__main__":
    cli()
