"""
Observe les annonces BLE de la Remote, SANS se connecter.

But : savoir si la Remote signale ses rotations dans ses annonces, comme le
fait HomeKit. Deux mécanismes :

  - annonce type 0x06 : contient le Global State Number (GSN). Si le GSN
    change quand on tourne la Remote, une intégration peut se contenter
    d'écouter les annonces et ne se connecter qu'après un changement ;
  - annonce type 0x11 : notification chiffrée (broadcast). Si elle apparaît
    quand on tourne la Remote, la valeur est dans l'annonce elle-même.

Ce script n'affiche une ligne que lorsque le contenu des annonces change.

Usage :
    poetry run watch_adv [durée_en_secondes] [--all]

Réveille la Remote (prends-la en main), laisse tourner le script, puis
tourne-la d'une face à l'autre en notant l'heure. La Remote n'annonce que
lorsqu'elle est réveillée : c'est normal de ne rien voir quand elle dort.

Option --all : affiche toutes les annonces HomeKit (06 et 11) vues, pas
seulement celles de la Remote (utile si l'identifiant est différent chez toi).

Sous macOS, CoreBluetooth peut regrouper des annonces identiques : seules les
annonces dont le contenu change sont fiables, ce qui est justement ce qu'on
cherche ici.
"""

import asyncio
import struct
import sys
import time
from dataclasses import dataclass

from bleak import BleakScanner

APPLE_COMPANY_ID = 76
TYPE_ADVERTISEMENT = 0x06
TYPE_ENCRYPTED_NOTIFICATION = 0x11
# Identifiant HAP de la Remote (voir tools/phase1.py).
KNOWN_DEVICE_ID = bytes.fromhex("d6bd09c0321d")


@dataclass(frozen=True)
class Advertisement:
    kind: int
    device_id: bytes
    # Type 0x06 seulement :
    flags: int | None = None
    category: int | None = None
    gsn: int | None = None
    config_number: int | None = None
    # Type 0x11 seulement :
    payload: bytes | None = None


def parse_apple_data(data: bytes) -> Advertisement | None:
    """Décode les données constructeur Apple d'une annonce HomeKit, sinon None."""
    if not data:
        return None
    if data[0] == TYPE_ADVERTISEMENT and len(data) >= 15:
        category, gsn, config_number, _compat = struct.unpack("<HHBB", data[9:15])
        return Advertisement(
            kind=TYPE_ADVERTISEMENT,
            device_id=bytes(data[3:9]),
            flags=data[2],
            category=category,
            gsn=gsn,
            config_number=config_number,
        )
    if data[0] == TYPE_ENCRYPTED_NOTIFICATION and len(data) >= 8:
        return Advertisement(
            kind=TYPE_ENCRYPTED_NOTIFICATION,
            device_id=bytes(data[2:8]),
            payload=bytes(data[8:]),
        )
    return None


def describe(adv: Advertisement, previous: Advertisement | None) -> str:
    """Une ligne lisible ; signale un changement de GSN par rapport au précédent."""
    ident = adv.device_id.hex(":")
    if adv.kind == TYPE_ADVERTISEMENT:
        text = (
            f"06 annonce  id={ident} flags={adv.flags:#04x} "
            f"catégorie={adv.category} GSN={adv.gsn} config={adv.config_number}"
        )
        if (
            previous is not None
            and previous.gsn is not None
            and previous.gsn != adv.gsn
        ):
            text += f"   <-- GSN {previous.gsn} -> {adv.gsn}"
        return text
    return f"11 broadcast chiffré  id={ident} payload={adv.payload.hex(' ')}"


async def main(argv: list[str]) -> int:
    show_all = "--all" in argv
    numbers = [a for a in argv if a.replace(".", "", 1).isdigit()]
    duration = float(numbers[0]) if numbers else 120.0

    last: dict[tuple[str, int], Advertisement] = {}
    seen_raw: dict[tuple[str, int], bytes] = {}
    start = time.monotonic()

    def on_adv(device, advertisement_data) -> None:
        data = advertisement_data.manufacturer_data.get(APPLE_COMPANY_ID)
        adv = parse_apple_data(data) if data else None
        if adv is None:
            return
        if not show_all and adv.device_id != KNOWN_DEVICE_ID:
            return
        key = (adv.device_id.hex(), adv.kind)
        if seen_raw.get(key) == bytes(data):
            return  # contenu inchangé
        seen_raw[key] = bytes(data)
        elapsed = time.monotonic() - start
        print(f"[{elapsed:6.1f}s] {describe(adv, last.get(key))}", flush=True)
        last[key] = adv

    print(
        f"Écoute pendant {duration:.0f} s (Ctrl+C pour arrêter). "
        "Réveille la Remote puis tourne-la d'une face à l'autre."
    )
    async with BleakScanner(on_adv):
        try:
            await asyncio.sleep(duration)
        except asyncio.CancelledError:
            pass
    if not seen_raw:
        print(
            "Aucune annonce de la Remote vue. Est-elle réveillée (elle s'allume "
            "quand on la prend en main) ? Essaie --all."
        )
        return 1
    return 0


def cli() -> None:
    """Point d'entrée synchrone, pour `poetry run` (voir pyproject.toml)."""
    try:
        sys.exit(asyncio.run(main(sys.argv[1:])))
    except KeyboardInterrupt:
        sys.exit(0)


if __name__ == "__main__":
    cli()
