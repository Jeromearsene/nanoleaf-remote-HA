"""Constants for the Nanoleaf Remote integration."""

DOMAIN = "nanoleaf_remote"
PLATFORMS = ["event"]

CONF_ADDRESS = "address"
CONF_SETUP_CODE = "setup_code"
CONF_PAIRING = "pairing"

EVENT_TYPES = [f"face_{i}" for i in range(1, 13)]

# The Remote drops an idle connection after ~5 s, so reading the switch
# characteristics every 1.5 s doubles as a keep-alive.
POLL_INTERVAL = 1.5

# Reconnection backoff, in seconds.
RECONNECT_MIN_DELAY = 3.0
RECONNECT_MAX_DELAY = 60.0

# Bounds the pairing handshake so a stalled link cannot hang the flow.
PAIRING_TIMEOUT = 60.0
VERIFY_TIMEOUT = 30.0

LOCAL_NAME_PREFIX = "Nanoleaf Remote"


def signal_event(entry_id: str) -> str:
    """Dispatcher signal carrying a rotation event for one config entry."""
    return f"{DOMAIN}_event_{entry_id}"


def signal_state(entry_id: str) -> str:
    """Dispatcher signal fired when one config entry's connection changes."""
    return f"{DOMAIN}_state_{entry_id}"
