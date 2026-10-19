"""
Constantes du protocole HomeKit Accessory Protocol (HAP) sur BLE.

Sources vérifiées :
- UUID du service Pairing et des caractéristiques Pair Setup / Pair Verify /
  Pairing Features : pyhomekit (henridwyer/pyhomekit, constants.py)
- Valeurs TLV8 du service Pairing (kTLVType_*) : idem
- Format du Control Field / en-tête PDU HAP-BLE : pyhomekit (ble.py),
  classes HapBlePduRequestHeader / HapBlePduResponseHeader
- OpCodes et StatusCodes HAP-BLE : pyhomekit (constants.py)
- Salts/Infos HKDF pour Pair-Setup et Pair-Verify : plusieurs implémentations
  concordantes (aanon4/HomeKit, spec non-commerciale Apple HAP R2, forums
  développeurs Apple)
"""

# --- Service et caractéristiques du service "Pairing" -----------------

PAIRING_SERVICE_UUID = "00000055-0000-1000-8000-0026bb765291"
PAIR_SETUP_CHARACTERISTIC_UUID = "0000004c-0000-1000-8000-0026bb765291"
PAIR_VERIFY_CHARACTERISTIC_UUID = "0000004e-0000-1000-8000-0026bb765291"
PAIRING_FEATURES_CHARACTERISTIC_UUID = "0000004f-0000-1000-8000-0026bb765291"

# Service Stateless Programmable Switch et sa caractéristique d'événement.
# Repérés sur cet accessoire en Phase 1 : 8 instances du service, chacune
# avec cette même caractéristique (propriétés read+indicate+write).
STATELESS_PROGRAMMABLE_SWITCH_SERVICE_UUID = "00000089-0000-1000-8000-0026bb765291"
PROGRAMMABLE_SWITCH_EVENT_CHARACTERISTIC_UUID = "00000073-0000-1000-8000-0026bb765291"

# Descripteur GATT qui contient le "Characteristic Instance ID" (CID),
# nécessaire pour adresser une caractéristique dans une requête HAP-BLE.
CHARACTERISTIC_ID_DESCRIPTOR_UUID = "dc46f0fe-81d2-4616-b5d9-6abdd796939a"


# --- TLV8 : types utilisés par le service Pairing (kTLVType_*) --------


class TLVType:
    METHOD = 0x00
    IDENTIFIER = 0x01
    SALT = 0x02
    PUBLIC_KEY = 0x03
    PROOF = 0x04
    ENCRYPTED_DATA = 0x05
    STATE = 0x06
    ERROR = 0x07
    RETRY_DELAY = 0x08
    CERTIFICATE = 0x09
    SIGNATURE = 0x0A
    PERMISSIONS = 0x0B
    FRAGMENT_DATA = 0x0C
    FRAGMENT_LAST = 0x0D
    SEPARATOR = 0xFF


class PairMethod:
    RESERVED = 0
    PAIR_SETUP = 1
    PAIR_VERIFY = 2
    ADD_PAIRING = 3
    REMOVE_PAIRING = 4
    LIST_PAIRINGS = 5


class TLVError:
    UNKNOWN = 0x01
    AUTHENTICATION = 0x02
    BACKOFF = 0x03
    MAX_PEERS = 0x04
    MAX_TRIES = 0x05
    UNAVAILABLE = 0x06
    BUSY = 0x07


# --- HAP-BLE : paramètres génériques (HapParamTypes) -------------------


class HapParamType:
    VALUE = 1
    ADDITIONAL_AUTHORIZATION_DATA = 2
    ORIGIN_LOCAL_VS_REMOTE = 3
    CHARACTERISTIC_TYPE = 4
    CHARACTERISTIC_INSTANCE_ID = 5
    SERVICE_TYPE = 6
    SERVICE_INSTANCE_ID = 7
    TTL = 8
    RETURN_RESPONSE = 9


# --- HAP-BLE : OpCodes (dans l'en-tête de requête) ----------------------


class OpCode:
    CHARACTERISTIC_SIGNATURE_READ = 0x01
    CHARACTERISTIC_WRITE = 0x02
    CHARACTERISTIC_READ = 0x03
    CHARACTERISTIC_TIMED_WRITE = 0x04
    CHARACTERISTIC_EXECUTE_WRITE = 0x05
    SERVICE_SIGNATURE_READ = 0x06


# --- HAP-BLE : StatusCodes (dans l'en-tête de réponse) ------------------


class StatusCode:
    SUCCESS = 0x00
    UNSUPPORTED_PDU = 0x01
    MAX_PROCEDURES = 0x02
    INSUFFICIENT_AUTHORIZATION = 0x03
    INVALID_INSTANCE_ID = 0x04
    INSUFFICIENT_AUTHENTICATION = 0x05
    INVALID_REQUEST = 0x06


STATUS_MESSAGES = {
    0x00: "OK.",
    0x01: "PDU HAP non reconnue ou non supportée.",
    0x02: "L'accessoire a atteint sa limite de procédures simultanées.",
    0x03: "Authorization supplémentaire requise pour cette caractéristique.",
    0x04: "L'Instance ID de la caractéristique ne correspond pas.",
    0x05: "Une session sécurisée (pairing) est requise.",
    0x06: "L'accessoire n'a pas pu réaliser l'opération demandée.",
}


# --- Constantes cryptographiques HAP (Pair-Setup / Pair-Verify) --------
# Chaînes ASCII utilisées comme "salt"/"info" pour les dérivations HKDF-SHA512.
# Vérifiées par recoupement (implémentations tierces + forums développeurs Apple).

SRP_USERNAME = b"Pair-Setup"

# Pair-Setup : clé de session (utilisée pour chiffrer M5 / déchiffrer M6)
HKDF_PAIR_SETUP_ENCRYPT_SALT = b"Pair-Setup-Encrypt-Salt"
HKDF_PAIR_SETUP_ENCRYPT_INFO = b"Pair-Setup-Encrypt-Info"

# Pair-Setup : signature du controller (dans M5)
HKDF_PAIR_SETUP_CONTROLLER_SIGN_SALT = b"Pair-Setup-Controller-Sign-Salt"
HKDF_PAIR_SETUP_CONTROLLER_SIGN_INFO = b"Pair-Setup-Controller-Sign-Info"

# Pair-Setup : signature de l'accessoire (dans M6)
HKDF_PAIR_SETUP_ACCESSORY_SIGN_SALT = b"Pair-Setup-Accessory-Sign-Salt"
HKDF_PAIR_SETUP_ACCESSORY_SIGN_INFO = b"Pair-Setup-Accessory-Sign-Info"

# Pair-Verify : clé de session (chiffrement des sous-TLV M2 / M3)
HKDF_PAIR_VERIFY_ENCRYPT_SALT = b"Pair-Verify-Encrypt-Salt"
HKDF_PAIR_VERIFY_ENCRYPT_INFO = b"Pair-Verify-Encrypt-Info"

# Session de contrôle post pair-verify (chiffrement des échanges GATT courants)
HKDF_CONTROL_SALT = b"Control-Salt"
HKDF_CONTROL_WRITE_INFO = b"Control-Write-Encryption-Key"  # controller -> accessoire
HKDF_CONTROL_READ_INFO = b"Control-Read-Encryption-Key"  # accessoire -> controller
