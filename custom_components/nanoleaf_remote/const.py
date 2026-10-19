"""Constants for the Nanoleaf Remote integration."""

DOMAIN = "nanoleaf_remote"
PLATFORMS = ["event"]
CONF_ADDRESS = "address"
CONF_PAIRING = "pairing"
EVENT_SIGNAL = f"{DOMAIN}_event"
EVENT_TYPES = [f"face_{i}" for i in range(1, 13)]
POLL_INTERVAL = 1.5
