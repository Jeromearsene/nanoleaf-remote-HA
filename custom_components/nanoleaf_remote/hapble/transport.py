"""
Couche de transport : relie le framing HAP-BLE (pdu.py, tlv8.py) au GATT
réel via `bleak` (multiplateforme, fonctionne sous Windows contrairement à
bluepy/dbus).

Le motif d'échange HAP-BLE pour une requête/réponse est :
    1. écrire la (les) trame(s) de requête sur la caractéristique
       (write WITH response) ;
    2. relire ensuite la MÊME caractéristique (read) pour récupérer la
       réponse — HAP-BLE n'utilise pas les notifications pour ce
       mécanisme requête/réponse.

Ce comportement est repris tel quel de pyhomekit (ble.py), qui l'utilise
avec bluepy ; ici le transport est bleak mais la logique protocolaire est
identique.
"""

import asyncio
import logging
from typing import List, Optional

from bleak import BleakClient

from . import pdu, tlv8, uuids
from .ble_session import BleSecureSession

logger = logging.getLogger(__name__)


class HapBleError(Exception):
    """Levée quand l'accessoire répond avec un status_code != SUCCESS."""

    def __init__(self, status_code: int):
        message = uuids.STATUS_MESSAGES.get(status_code, "Erreur inconnue.")
        super().__init__(f"[HAP-BLE] status=0x{status_code:02x} : {message}")
        self.status_code = status_code


class HapBleCharacteristic:
    """Enveloppe une caractéristique GATT pour dialoguer en HAP-BLE.

    Si `session` est fourni (une BleSecureSession issue d'un Pair-Verify
    réussi), chaque écriture/lecture GATT est chiffrée/déchiffrée avec
    ChaCha20-Poly1305 avant d'être traitée comme une PDU HAP-BLE normale —
    c'est le cas pour toute caractéristique en dehors du service Pairing,
    une fois la session établie."""

    def __init__(
        self,
        client: BleakClient,
        gatt_char,
        session: Optional[BleSecureSession] = None,
        lock: Optional[asyncio.Lock] = None,
    ):
        self._client = client
        self._gatt_char = gatt_char
        self._cid: Optional[int] = None
        self._session = session
        self._lock = lock

    @property
    def uuid(self) -> str:
        return self._gatt_char.uuid

    @property
    def gatt_char(self):
        """L'objet caractéristique natif de bleak (nécessaire pour
        s'abonner aux indications via client.start_notify())."""
        return self._gatt_char

    async def cid(self) -> int:
        """Lit (et met en cache) le Characteristic Instance ID (CID)."""
        if self._cid is None:
            descriptor = None
            for d in self._gatt_char.descriptors:
                if d.uuid.lower() == uuids.CHARACTERISTIC_ID_DESCRIPTOR_UUID:
                    descriptor = d
                    break
            if descriptor is None:
                raise RuntimeError(
                    f"Descripteur Characteristic Instance ID introuvable "
                    f"pour la caractéristique {self._gatt_char.uuid}."
                )
            raw = await self._client.read_gatt_descriptor(descriptor.handle)
            self._cid = int.from_bytes(bytes(raw), "little")
            logger.debug("CID de %s = %s", self._gatt_char.uuid, self._cid)
        return self._cid

    async def _write(self, plaintext: bytes) -> None:
        data = self._session.seal(plaintext) if self._session else plaintext
        await self._client.write_gatt_char(self._gatt_char, data, response=True)

    async def _read(self) -> bytes:
        raw = bytes(await self._client.read_gatt_char(self._gatt_char))
        return self._session.open(raw) if self._session else raw

    async def request(self, op_code: int, body: bytes = b"") -> bytes:
        """Envoie une requête HAP-BLE (op_code + corps optionnel) et
        retourne le corps de la réponse (déjà validée : lève HapBleError
        si status_code != SUCCESS).

        Si la réponse est trop volumineuse pour tenir dans une seule trame,
        effectue automatiquement des lectures GATT supplémentaires (sans
        nouvelle écriture) pour assembler la réponse complète — c'est le
        cas typique du message M2 du Pair-Setup (clé publique SRP de 384
        octets).

        Si une session chiffrée est active, chaque écriture/lecture
        individuelle est chiffrée/déchiffrée (une PDU/fragment = un bloc
        ChaCha20-Poly1305, avec son propre compteur de nonce).

        Si un verrou partagé (`lock`) a été fourni à la construction,
        toute la séquence écriture(s)+lecture(s) est sérialisée avec lui —
        nécessaire dès que plusieurs coroutines peuvent dialoguer sur la
        même connexion en même temps (ex: le pont MQTT, où la boucle de
        sondage et les callbacks d'indication tournent en parallèle) :
        sans ça, la réponse d'une requête pourrait être lue par une autre
        requête concurrente."""
        if self._lock is not None:
            async with self._lock:
                return await self._request_unlocked(op_code, body)
        return await self._request_unlocked(op_code, body)

    async def _request_unlocked(self, op_code: int, body: bytes) -> bytes:
        cid = await self.cid()
        transaction_id = pdu.new_transaction_id()
        fragments = pdu.build_request_fragments(cid, op_code, transaction_id, body)

        logger.debug(
            "Requête HAP-BLE -> %s : op_code=0x%02x cid=%s tid=%s (%d trame(s))%s",
            self._gatt_char.uuid,
            op_code,
            cid,
            transaction_id,
            len(fragments),
            " [chiffré]" if self._session else "",
        )
        for fragment in fragments:
            logger.debug("  écriture (clair) : %s", fragment.hex(" "))
            await self._write(fragment)

        raw_response = await self._read()
        logger.debug("  réponse (1er fragment, clair) : %s", raw_response.hex(" "))

        header, announced_length, partial_body = pdu.parse_first_response(
            raw_response, transaction_id
        )

        assembled = bytearray(partial_body)
        max_continuation_reads = 40  # garde-fou (~40 * 512o = 20 Ko max)
        reads_done = 0
        while len(assembled) < announced_length:
            if reads_done >= max_continuation_reads:
                raise RuntimeError(
                    f"Trop de lectures de continuation ({reads_done}) sans "
                    f"atteindre la longueur annoncée ({announced_length} "
                    f"octets, {len(assembled)} reçus) — abandon."
                )
            raw_continuation = await self._read()
            logger.debug(
                "  réponse (continuation, clair) : %s", raw_continuation.hex(" ")
            )
            assembled += pdu.parse_continuation_fragment(
                raw_continuation, transaction_id
            )
            reads_done += 1

        if len(assembled) != announced_length:
            raise ValueError(
                f"Longueur de corps incohérente après assemblage : "
                f"{len(assembled)} octet(s) reçus, {announced_length} "
                f"annoncés."
            )

        if header.status_code != uuids.StatusCode.SUCCESS:
            raise HapBleError(header.status_code)
        return bytes(assembled)

    async def read_value(self) -> bytes:
        """Characteristic Read HAP-BLE : retourne le contenu brut du tag
        HapParamType.VALUE dans la réponse (c'est la valeur "utile" de la
        caractéristique, ex: le contenu de Pairing Features)."""
        body = await self.request(uuids.OpCode.CHARACTERISTIC_READ)
        parsed = tlv8.decode(body)
        return parsed.get(uuids.HapParamType.VALUE, b"")

    async def write_ktlvs(self, ktlvs) -> dict:
        """Characteristic Write HAP-BLE transportant des kTLV (le "value"
        est lui-même un TLV8 imbriqué) — c'est le motif utilisé par Pair
        Setup et Pair Verify pour chaque message de leur échange.

        `ktlvs` : liste de tuples (tag, valeur) à encoder comme kTLV8.
        Retourne un dict {tag: valeur} des kTLV8 de la réponse.
        """
        inner = tlv8.encode(ktlvs)
        outer_body = tlv8.encode(
            [
                (uuids.HapParamType.RETURN_RESPONSE, bytes([1])),
                (uuids.HapParamType.VALUE, inner),
            ]
        )
        response_body = await self.request(
            uuids.OpCode.CHARACTERISTIC_WRITE, outer_body
        )
        outer_response = tlv8.decode(response_body)
        value = outer_response.get(uuids.HapParamType.VALUE, b"")
        return tlv8.decode(value)

    def try_decode_indication(self, raw: bytes) -> Optional[bytes]:
        """Tente de déchiffrer/parser le contenu brut d'une indication GATT
        comme s'il s'agissait d'une réponse HAP-BLE chiffrée classique, et
        d'en extraire le tag VALUE. Retourne None si ça ne ressemble pas à
        une PDU HAP-BLE valide (l'indication sert alors probablement juste
        de signal "va relire", sans porter la valeur elle-même) — dans ce
        cas, faire un read_value() explicite juste après.

        Ne consomme PAS le compteur de la session en cas d'échec (on ne
        peut pas savoir à l'avance si un paquet donné est un vrai fragment
        chiffré ou un simple signal ; on retente le déchiffrement sur une
        COPIE du compteur, et on ne l'incrémente pour de vrai qu'en cas de
        succès plausible)."""
        if not self._session:
            return None
        import copy

        session_copy = copy.copy(self._session)
        try:
            plaintext = session_copy.open(raw)
            header, announced_length, partial_body = pdu.parse_first_response(
                plaintext,
                expected_transaction_id=plaintext[1] if len(plaintext) > 1 else 0,
            )
            if len(partial_body) != announced_length:
                return None  # fragmenté / incomplet : pas exploitable ici
            parsed = tlv8.decode(bytes(partial_body))
            self._session.recv_counter = session_copy.recv_counter
            return parsed.get(uuids.HapParamType.VALUE, b"")
        except Exception:
            return None


class HapBleAccessory:
    """Représente une connexion HAP-BLE à un accessoire, via son adresse
    MAC BLE. Utilisation :

        async with HapBleAccessory(ADDRESS) as acc:
            features = await acc.read_pairing_features()
    """

    def __init__(
        self,
        device_or_address,
        connect_retries: int = 3,
        retry_delay_seconds: float = 1.5,
        client: Optional[BleakClient] = None,
    ):
        """`device_or_address` peut être soit une adresse (str), soit un
        objet BLEDevice déjà découvert par un scan. Passer directement le
        BLEDevice (plutôt qu'une adresse re-résolue en chaîne) est plus
        fiable, en particulier sous macOS où l'"adresse" est un identifiant
        interne à bleak et non une vraie adresse BLE.

        `connect_retries` : la connexion BLE réelle échoue parfois de
        façon intermittente (observé empiriquement avec cet accessoire :
        établissement de liaison lent et parfois interrompu par
        CoreBluetooth), sans rapport avec un bug de notre code. On
        réessaie donc automatiquement plutôt que de faire remonter
        l'échec au premier coup.
        """
        self.device_or_address = device_or_address
        self.connect_retries = connect_retries
        self.retry_delay_seconds = retry_delay_seconds
        self.client: Optional[BleakClient] = client
        self._owns_client = client is None
        self.request_lock = asyncio.Lock()

    async def __aenter__(self) -> "HapBleAccessory":
        # Home Assistant integrations can inject a client connected through
        # Home Assistant's Bluetooth manager/retry connector. In that case,
        # this wrapper must not create a second BLE connection.
        if self.client is not None:
            if not self.client.is_connected:
                raise ConnectionError("Le client BLE fourni n'est pas connecté.")
            return self

        last_error: Optional[Exception] = None
        for attempt in range(1, self.connect_retries + 1):
            # Une nouvelle instance de BleakClient à chaque tentative :
            # après un échec, l'état interne du backend (en particulier
            # CoreBluetooth sous macOS) n'est pas garanti réutilisable
            # proprement.
            self.client = BleakClient(self.device_or_address)
            try:
                logger.info(
                    "Connexion GATT à %s (tentative %d/%d)...",
                    self.device_or_address,
                    attempt,
                    self.connect_retries,
                )
                await self.client.connect()
                logger.info("Connecté. Découverte des services...")
                return self
            except Exception as exc:  # BleakError et apparentés
                last_error = exc
                logger.warning(
                    "Échec de connexion (tentative %d/%d) : %s",
                    attempt,
                    self.connect_retries,
                    exc,
                )
                if attempt < self.connect_retries:
                    await asyncio.sleep(self.retry_delay_seconds)

        raise ConnectionError(
            f"Échec de connexion après {self.connect_retries} tentatives. "
            f"Dernière erreur : {last_error}"
        ) from last_error

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self.client is not None and self._owns_client:
            await self.client.disconnect()

    def get_characteristic(
        self, service_uuid: str, char_uuid: str
    ) -> HapBleCharacteristic:
        assert self.client is not None, "Non connecté."
        service = self.client.services.get_service(service_uuid)
        if service is None:
            raise RuntimeError(
                f"Service {service_uuid} introuvable sur l'accessoire. "
                f"Vérifie que l'appareil est bien à portée et qu'il s'agit "
                f"d'un accessoire HomeKit BLE."
            )
        gatt_char = service.get_characteristic(char_uuid)
        if gatt_char is None:
            raise RuntimeError(
                f"Caractéristique {char_uuid} introuvable dans le service "
                f"{service_uuid}."
            )
        return HapBleCharacteristic(self.client, gatt_char, lock=self.request_lock)

    async def list_services(self) -> None:
        """Utilitaire de debug : affiche tous les services/caractéristiques
        découverts, pour vérifier que le service Pairing est bien exposé."""
        assert self.client is not None, "Non connecté."
        for service in self.client.services:
            print(f"Service {service.uuid}")
            for char in service.characteristics:
                props = ",".join(char.properties)
                print(f"  Caractéristique {char.uuid}  [{props}]")
                for d in char.descriptors:
                    print(f"    Descripteur {d.uuid}")

    async def read_pairing_features(self) -> int:
        """Lit la caractéristique Pairing Features (accessible sans
        pairing). Retourne l'octet de bitmap de fonctionnalités."""
        char = self.get_characteristic(
            uuids.PAIRING_SERVICE_UUID,
            uuids.PAIRING_FEATURES_CHARACTERISTIC_UUID,
        )
        raw = await char.read_value()
        if not raw:
            raise RuntimeError("Réponse vide pour Pairing Features.")
        return raw[0]

    def pair_setup_characteristic(self) -> HapBleCharacteristic:
        """Caractéristique Pair Setup, pour dialoguer les messages M1-M6
        de l'appairage (voir hapble.pairing)."""
        return self.get_characteristic(
            uuids.PAIRING_SERVICE_UUID,
            uuids.PAIR_SETUP_CHARACTERISTIC_UUID,
        )

    def pair_verify_characteristic(self) -> HapBleCharacteristic:
        """Caractéristique Pair Verify, pour dialoguer les messages M1-M4
        de l'établissement de session (voir hapble.pair_verify)."""
        return self.get_characteristic(
            uuids.PAIRING_SERVICE_UUID,
            uuids.PAIR_VERIFY_CHARACTERISTIC_UUID,
        )

    def get_all_characteristics(
        self,
        service_uuid: str,
        char_uuid: str,
        session: Optional[BleSecureSession] = None,
    ) -> List[HapBleCharacteristic]:
        """Comme get_characteristic(), mais retourne TOUTES les instances
        du service demandé (utile pour Stateless Programmable Switch,
        présent en plusieurs exemplaires — un par face/position — sur cet
        accessoire)."""
        assert self.client is not None, "Non connecté."
        result = []
        for service in self.client.services:
            if service.uuid.lower() != service_uuid.lower():
                continue
            gatt_char = service.get_characteristic(char_uuid)
            if gatt_char is not None:
                result.append(
                    HapBleCharacteristic(
                        self.client, gatt_char, session=session, lock=self.request_lock
                    )
                )
        return result

    def programmable_switch_event_characteristics(
        self, session: Optional[BleSecureSession] = None
    ) -> List[HapBleCharacteristic]:
        """Les caractéristiques ProgrammableSwitchEvent (une par instance du
        service Stateless Programmable Switch — 8 trouvées en Phase 1 sur
        cet accessoire). Nécessitent une session chiffrée (Pair-Verify)
        pour être lues."""
        return self.get_all_characteristics(
            uuids.STATELESS_PROGRAMMABLE_SWITCH_SERVICE_UUID,
            uuids.PROGRAMMABLE_SWITCH_EVENT_CHARACTERISTIC_UUID,
            session=session,
        )

    async def subscribe_switch_events(
        self, characteristics: List[HapBleCharacteristic], on_event
    ) -> int:
        """S'abonne aux indications GATT (CCCD standard) sur chacune des
        caractéristiques fournies. `on_event(index, decoded_value_or_None,
        raw_bytes)` est appelé à chaque indication reçue — `index` est la
        position dans la liste `characteristics` (donc probablement le
        numéro de face - 1, d'après nos observations en Phase 4).

        `decoded_value_or_None` : le contenu déjà déchiffré/extrait si
        l'indication ressemblait à une PDU HAP-BLE chiffrée valide, sinon
        None (dans ce cas, faire un read_value() explicite dans `on_event`
        si on veut la valeur — l'indication a alors juste servi de signal).

        Vérifie explicitement, après chaque abonnement, que le descripteur
        CCCD (0x2902) a bien été écrit avec la valeur "indicate" (0x0002) —
        et pas "notify" (0x0001), une confusion facile puisque bleak choisit
        automatiquement mais peut se tromper selon la plateforme/le
        firmware. Retourne le nombre d'abonnements confirmés comme
        "indicate" actif ; logge un avertissement clair pour chaque échec
        au lieu de laisser un abonnement silencieusement inactif."""
        assert self.client is not None, "Non connecté."

        CCCD_UUID = "00002902-0000-1000-8000-00805f9b34fb"
        confirmed = 0

        for index, char in enumerate(characteristics):

            def make_callback(idx: int, c: HapBleCharacteristic):
                def callback(_sender, data: bytearray) -> None:
                    raw = bytes(data)
                    logger.info(
                        "Indication brute recue [instance %d] : %s", idx, raw.hex(" ")
                    )
                    decoded = c.try_decode_indication(raw)
                    asyncio.create_task(_safe_call(on_event, idx, decoded, raw))

                return callback

            try:
                await self.client.start_notify(
                    char.gatt_char, make_callback(index, char)
                )
            except Exception as exc:  # pylint: disable=broad-except
                logger.warning(
                    "Échec de l'abonnement sur l'instance %d : %s", index, exc
                )
                continue

            # Vérification : le CCCD a-t-il bien été mis à "indicate" (0x02) ?
            cccd = next(
                (d for d in char.gatt_char.descriptors if d.uuid.lower() == CCCD_UUID),
                None,
            )
            if cccd is None:
                logger.warning(
                    "Instance %d : pas de descripteur CCCD trouvé "
                    "(abonnement non vérifiable).",
                    index,
                )
                confirmed += 1  # on suppose que start_notify a fait le nécessaire
                continue
            try:
                cccd_value = bytes(await self.client.read_gatt_descriptor(cccd.handle))
            except Exception as exc:  # pylint: disable=broad-except
                logger.warning(
                    "Instance %d : lecture du CCCD impossible (%s).", index, exc
                )
                confirmed += 1
                continue

            if cccd_value == bytes([0x02, 0x00]):
                logger.debug("Instance %d : CCCD confirmé en mode indicate.", index)
                confirmed += 1
            elif cccd_value == bytes([0x01, 0x00]):
                logger.warning(
                    "Instance %d : CCCD en mode NOTIFY (0x01) au lieu "
                    "d'INDICATE (0x02) — probablement inopérant pour cette "
                    "caractéristique.",
                    index,
                )
            else:
                logger.warning(
                    "Instance %d : CCCD a une valeur inattendue : %s",
                    index,
                    cccd_value.hex(" "),
                )

        return confirmed

    async def unsubscribe_switch_events(
        self, characteristics: List[HapBleCharacteristic]
    ) -> None:
        assert self.client is not None, "Non connecté."
        for char in characteristics:
            try:
                await self.client.stop_notify(char.gatt_char)
            except Exception:  # pylint: disable=broad-except
                pass  # déjà déconnecté, ou jamais abonné avec succès


async def _safe_call(on_event, index: int, decoded, raw: bytes) -> None:
    try:
        result = on_event(index, decoded, raw)
        if asyncio.iscoroutine(result):
            await result
    except Exception:  # pylint: disable=broad-except
        logger.exception("Erreur dans le callback on_event (index=%d)", index)
