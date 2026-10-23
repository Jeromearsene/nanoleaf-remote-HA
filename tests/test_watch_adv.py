"""Décodage des annonces HomeKit utilisé par tools/watch_adv.py."""

from tools.watch_adv import (
    TYPE_ADVERTISEMENT,
    TYPE_ENCRYPTED_NOTIFICATION,
    describe,
    parse_apple_data,
)

# Début identique à la capture de la Remote (06 31 00 <id> 0f00 ...) ; le reste est fictif.
ADV = bytes.fromhex("06 31 00 d6bd09c0321d 0f00 0100 02 02 aabbccdd".replace(" ", ""))


def test_parse_advertisement():
    adv = parse_apple_data(ADV)
    assert adv.kind == TYPE_ADVERTISEMENT
    assert adv.device_id.hex() == "d6bd09c0321d"
    assert (adv.category, adv.gsn, adv.config_number) == (0x0F, 1, 2)


def test_parse_encrypted_notification():
    data = bytes([0x11, 0x00]) + bytes.fromhex("d6bd09c0321d") + b"\x01\x02\x03"
    adv = parse_apple_data(data)
    assert adv.kind == TYPE_ENCRYPTED_NOTIFICATION
    assert adv.device_id.hex() == "d6bd09c0321d"
    assert adv.payload == b"\x01\x02\x03"


def test_not_homekit_or_too_short():
    assert parse_apple_data(b"") is None
    assert parse_apple_data(b"\x10\x05\x00") is None
    assert parse_apple_data(b"\x06\x31\x00") is None


def test_gsn_change_is_flagged():
    first = parse_apple_data(ADV)
    changed = parse_apple_data(ADV[:11] + b"\x02\x00" + ADV[13:])
    assert "<-- GSN 1 -> 2" in describe(changed, first)
    assert "<--" not in describe(first, first)
