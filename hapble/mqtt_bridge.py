"""
Publication MQTT des événements de rotation, au format attendu par
l'intégration MQTT "event" de Home Assistant (découverte automatique).

Format vérifié sur la documentation officielle Home Assistant
(https://www.home-assistant.io/integrations/event.mqtt/) :
  - topic de découverte : <prefix>/event/<object_id>/config
  - payload de découverte : JSON avec au moins state_topic, event_types,
    name, unique_id (et un bloc "device" optionnel pour regrouper
    plusieurs entités sous un même appareil dans l'UI HA) ;
  - topic d'état : reçoit un JSON contenant la clé "event_type", qui doit
    être l'une des valeurs listées dans "event_types" ; aucun value_template
    n'est nécessaire tant que le payload a directement cette forme.
"""

import json
from dataclasses import dataclass

FACE_COUNT = 12  # nombre d'instances ProgrammableSwitchEvent (Phase 1/4)

DISCOVERY_PREFIX = "homeassistant"
OBJECT_ID = "nanoleaf_remote_rotation"
STATE_TOPIC = "nanoleaf_remote/rotation/state"
DISCOVERY_TOPIC = f"{DISCOVERY_PREFIX}/event/{OBJECT_ID}/config"


@dataclass
class MqttConfig:
    host: str = "localhost"
    port: int = 1883
    username: str | None = None
    password: str | None = None


def discovery_payload(device_identifier: str) -> str:
    """Construit le JSON de découverte HA pour l'entité "event" de
    rotation. `device_identifier` : un identifiant stable pour regrouper
    cette entité sous un appareil dans l'UI HA (ex: l'adresse HAP de
    l'accessoire, "D6:BD:09:C0:32:1D" dans notre cas — les deux-points sont
    retirés pour obtenir un identifiant propre)."""
    clean_id = device_identifier.replace(":", "").replace(" ", "_").lower()
    payload = {
        "name": "Nanoleaf Remote Position",
        "unique_id": f"nanoleaf_remote_{clean_id}_rotation",
        "state_topic": STATE_TOPIC,
        "event_types": [f"face_{i + 1}" for i in range(FACE_COUNT)],
        "device": {
            "identifiers": [f"nanoleaf_remote_{clean_id}"],
            "name": "Nanoleaf Remote",
            "manufacturer": "Nanoleaf",
            "model": "Remote",
        },
    }
    return json.dumps(payload)


def event_state_payload(face_index: int) -> str:
    """`face_index` : 0-indexé (comme partout dans ce projet — voir la
    correspondance confirmée en Phase 4 : index = numéro de face - 1)."""
    return json.dumps({"event_type": f"face_{face_index + 1}"})
