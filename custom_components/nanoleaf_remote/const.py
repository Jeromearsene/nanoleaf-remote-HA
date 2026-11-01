"""Constants for the Nanoleaf Remote integration."""

DOMAIN = "nanoleaf_remote"
PLATFORMS = ["event", "sensor"]

CONF_ADDRESS = "address"
CONF_SETUP_CODE = "setup_code"
CONF_PAIRING = "pairing"
CONF_PAIRING_JSON = "pairing_json"
CONF_FACE_MAP = "face_map"
CONF_POWER_SAVING = "power_saving"

EVENT_TYPES = [f"face_{i}" for i in range(1, 13)]

# The Remote drops an idle connection after ~5 s, so reading the switch
# characteristics every 1.5 s doubles as a keep-alive.
POLL_INTERVAL = 1.5

# Battery saving mode: no standing connection. The Remote is only contacted
# when its advertised state counter changes, and released once it has been
# idle for ACTIVE_WINDOW seconds (which also re-arms the counter).
ACTIVE_WINDOW = 10.0
# After a session, advertisements only refresh the reference counter for this
# long (a session can move the counter by itself).
BASELINE_WINDOW = 6.0
# Never start two sessions closer than this (protects against a loop).
MIN_SESSION_GAP = 3.0
# One read of a switch characteristic must answer within this many seconds,
# otherwise the link is considered lost (a hung read would block the listener).
READ_TIMEOUT = 8.0
# Failed attempts after a wake-up before waiting for the next one.
POWER_SAVING_ATTEMPTS = 3

# Reconnection backoff, in seconds.
RECONNECT_MIN_DELAY = 3.0
RECONNECT_MAX_DELAY = 60.0

# The battery level changes slowly (a coin cell): read it once per session,
# and again only if a permanent (non power-saving) session stays open this
# long, instead of on every 1.5 s poll.
BATTERY_POLL_INTERVAL = 1800.0

# How long the setup flow waits for the Remote to be heard: it only
# advertises while it is awake, so the user turns it during this window.
WAIT_FOR_REMOTE = 30

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


def signal_battery(entry_id: str) -> str:
    """Dispatcher signal fired when one config entry's battery level is read."""
    return f"{DOMAIN}_battery_{entry_id}"
