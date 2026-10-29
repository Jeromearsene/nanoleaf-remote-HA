"""BleSecureSession: strict by default, optional counter resynchronisation."""

import pytest

from hapble import crypto_hap
from hapble.ble_session import BleSecureSession

KEY = bytes(range(32))


def accessory() -> BleSecureSession:
    """The accessory's side: it encrypts what the controller will read."""
    return BleSecureSession(read_key=bytes(32), write_key=KEY)


def controller(window: int = 0) -> BleSecureSession:
    return BleSecureSession(read_key=KEY, write_key=bytes(32), resync_window=window)


def test_in_order_messages_decrypt() -> None:
    acc, ctl = accessory(), controller()
    for text in (b"one", b"two", b"three"):
        assert ctl.open(acc.seal(text)) == text


def test_strict_session_rejects_a_missed_message() -> None:
    acc, ctl = accessory(), controller()
    acc.seal(b"lost")
    with pytest.raises(crypto_hap.DecryptionError):
        ctl.open(acc.seal(b"next"))


def test_window_recovers_from_a_missed_message() -> None:
    acc, ctl = accessory(), controller(window=1)
    acc.seal(b"lost")
    assert ctl.open(acc.seal(b"next")) == b"next"
    assert ctl.open(acc.seal(b"after")) == b"after"


def test_window_accepts_a_message_delivered_twice() -> None:
    # The same response arrives as an indication and again by read.
    acc, ctl = accessory(), controller(window=1)
    response = acc.seal(b"response")
    assert ctl.open(response) == b"response"
    assert ctl.open(response) == b"response"  # duplicate: accepted, no advance
    assert ctl.recv_counter == 1
    assert ctl.open(acc.seal(b"next")) == b"next"


def test_window_does_not_hide_tampering() -> None:
    acc, ctl = accessory(), controller(window=1)
    sealed = bytearray(acc.seal(b"data"))
    sealed[0] ^= 1
    with pytest.raises(crypto_hap.DecryptionError):
        ctl.open(bytes(sealed))


def test_message_too_far_ahead_is_rejected() -> None:
    acc, ctl = accessory(), controller(window=1)
    acc.seal(b"a")
    acc.seal(b"b")
    with pytest.raises(crypto_hap.DecryptionError):
        ctl.open(acc.seal(b"c"))
