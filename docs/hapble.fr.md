# hapble — client HAP-BLE maison pour la Nanoleaf Remote

> 📚 Ceci est le récit technique du travail sur le protocole derrière l'intégration. Pour installer et utiliser l'intégration Home Assistant, voir le [README principal](../README.fr.md).

[![CI](https://github.com/Jeromearsene/nanoleaf-remote-HA/actions/workflows/ci.yml/badge.svg)](https://github.com/Jeromearsene/nanoleaf-remote-HA/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

🇬🇧 [English](hapble.md) | 🇫🇷 Français (ce document)

> **Avertissement** : projet indépendant de reverse engineering, sans
> lien avec Apple ni Nanoleaf. Fourni tel quel, sans garantie — voir
> `LICENSE` et [`SECURITY.md`](../SECURITY.md).

Objectif : parler HomeKit Accessory Protocol (HAP) en Bluetooth LE
**directement depuis Windows**, via `bleak`, sans dépendre de bluepy/BlueZ
(donc sans Linux, sans VM, sans proxy ESPHome).

## Pourquoi ce projet existe

Toutes les implémentations Python existantes de HAP-BLE (`homekit_python`,
`pyhomekit`, et par ricochet `aiohomekit` utilisé par Home Assistant côté
BLE) reposent sur `bluepy`, qui lui-même dépend de **BlueZ via D-Bus** —
disponible uniquement sous Linux. `bleak`, en revanche, est multiplateforme
(Windows/Linux/macOS). Ce dépôt reprend la logique protocolaire de
`pyhomekit` (dont le code source a été consulté pour ce projet) mais avec
`bleak` comme transport à la place de `bluepy`.

## État d'avancement

### ✅ Phase 1 — Transport & framing (ce dépôt, prêt à tester)

- Connexion GATT via `bleak`.
- Encodage/décodage TLV8 (`tlv8.py`).
- En-têtes de requête/réponse HAP-BLE, Control Field, fragmentation
  (`pdu.py`).
- Une requête HAP-BLE réelle et sans risque : lecture de la caractéristique
  **Pairing Features**, qui est lisible sans pairing (`transport.py`).

C'est le test décisif : s'il passe, on sait que notre compréhension du
protocole (UUID, TLV8, framing des PDU) est correcte face au vrai firmware
de la Remote, **avant** d'investir du temps dans la cryptographie.

### ✅ Phase 2 — Pair-Setup (SRP-6a + Ed25519) — prêt à tester

- SRP-6a en pur Python (`srp.py`), groupe 3072 bits (RFC 5054), SHA-512,
  username `"Pair-Setup"`. Constante N vérifiée programmatiquement contre
  le texte brut de la RFC (une erreur de transcription manuelle a été
  détectée et corrigée de cette façon pendant le développement).
- HKDF-SHA512, Ed25519, X25519, ChaCha20-Poly1305 (`crypto_hap.py`), via
  la bibliothèque `cryptography`.
- Machine à états M1→M6 complète (`pairing.py`).
- Persistance du résultat (`pairing_store.py`) dans `pairing.json`.
- **Validé de bout en bout contre un faux accessoire simulé en Python pur**
  (`tests/test_pairing_e2e_fake.py`, ne nécessite aucun matériel) : le chemin
  nominal réussit avec vérifications croisées client/accessoire, et le
  chemin d'erreur (mauvais code) est correctement rejeté.
- **Fragmentation des réponses volumineuses au niveau PDU (bit
  `continuation`)** : le message M2 (qui contient la clé publique SRP de
  384 octets) dépasse largement une seule trame GATT. Ni `pyhomekit` ni
  aucune autre référence trouvée n'implémentaient ce cas (l'auteur de
  `pyhomekit` le note lui-même comme `NotImplementedError` dans son
  code) — il a donc fallu l'implémenter nous-mêmes : après une première
  lecture GATT annonçant une longueur totale, on effectue des lectures
  GATT supplémentaires (sans nouvelle écriture) jusqu'à assembler la
  longueur annoncée. Validé par un test d'intégration simulant exactement
  le motif observé contre le vrai appareil (240 octets reçus, 1151
  annoncés, assemblés sur 3 lectures).

**Correction appliquée après un second échec réel** : le mot de passe utilisé
dans le calcul SRP doit être le **code complet avec tirets** (`"543-97-113"`),
pas les 8 chiffres nus (`"54397113"`) — confirmé par 4 sources indépendantes,
dont `pyhomekit` elle-même (notre référence principale depuis le début du
projet), qui l'indique explicitement dans sa docstring. `normalize_setup_code()`
produit maintenant le format canonique `XXX-XX-XXX` quel que soit le format
saisi en entrée.

*(Tentative précédente, non concluante : remplissage minimal vs 384 octets
dans la formule M1/M2 — gardée par prudence dans `srp.py`, documentée par
une source par ailleurs fiable, mais qui ne suffisait pas à elle seule.)*

### ✅ Phase 3 — Pair-Verify — prêt à tester

- Implémenté directement depuis le texte **intégral et officiel** de la
  spec HAP (section 5.7), récupéré et lu en entier pour ce projet — aucune
  zone d'incertitude comme celle qui avait causé des allers-retours sur la
  preuve SRP de Pair-Setup.
- Validé de bout en bout contre un faux accessoire simulé
  (`tests/test_pair_verify_e2e_fake.py`) : clés de session identiques calculées
  indépendamment des deux côtés, et rejet correct d'un identifiant
  d'accessoire inattendu (protection contre un accessoire usurpé/différent).
- **Bonus** : le vecteur de test SRP *officiel* de la spec Apple
  (section 5.5.2) est maintenant un test de non-régression permanent
  (`tests/test_srp_official_vector.py`) — v, A, B, S, K vérifiés exactement
  contre les valeurs publiées par Apple elle-même, indépendamment de tout
  matériel. Les vecteurs sont reconstruits programmatiquement depuis le
  texte brut de la spec (pas retapés à la main, par prudence après le bug
  de transcription détecté plus tôt sur la constante N).

### ✅ Phase 4 — Session chiffrée + lecture de ProgrammableSwitchEvent — prêt à tester

- Format des PDU chiffrées confirmé via une crate Rust dédiée spécifiquement
  au transport HAP-BLE (pas HAP-IP, dont les conventions diffèrent) : chaque
  opération GATT chiffre/déchiffre une PDU HAP-BLE entière en un bloc
  ChaCha20-Poly1305, sans AAD, nonce = 4 octets nuls + compteur 64 bits LE,
  un compteur par direction (`ble_session.py`).
- Validé par un test d'intégration simulant un accessoire chiffré complet :
  écriture chiffrée, déchiffrement côté "accessoire" simulé, réponse
  chiffrée en retour, déchiffrement et parsing corrects côté client.
- Le format des PDU elles-mêmes (control field, TLV8) est inchangé : cette
  couche ne fait qu'ajouter chiffrement/déchiffrement autour de ce qui
  existait déjà.

**Limite connue, pas encore résolue** : les caractéristiques
`ProgrammableSwitchEvent` ont la propriété GATT `indicate` (repérée en
Phase 1) — une simple lecture directe pourrait ne rien renvoyer si
l'accessoire attend plutôt une souscription aux indications BLE (via le
descripteur CCCD `0x2902`), qui n'est pas encore implémentée. `tools/phase4.py`
tente d'abord la lecture directe (plus simple, réutilise tout ce qui existe)
et documente ce point si elle ne renvoie rien.

**Autre limite pratique** : la fenêtre de connexion courte de l'accessoire
(~1s, voir Phase 1) ne permet probablement pas de lire les 8 instances
d'affilée en une seule connexion — le script continue après un échec
partiel plutôt que d'abandonner.

### ✅ Phase 5 — Écoute hybride (indications + sondage de maintien) — validé contre le vrai appareil

Confirmé empiriquement (Phase 4) : **index dans la liste des 12 instances
= numéro de face − 1**, et la valeur de l'instance active repasse à
`"null"` après lecture (signal transitoire, pas un état persistant).

**Diagnostic du premier essai (abonnement seul, sans sondage)** : le CCCD a
été confirmé en mode *indicate* sur les 12 instances (donc pas un problème
de mode notify/indicate), mais l'accessoire a coupé la connexion après
~5 secondes d'écoute passive, avant qu'aucune rotation n'ait pu être
détectée — confirmant l'hypothèse de la Phase 1 : cet accessoire déconnecte
une connexion qu'il juge inactive, et rester silencieusement abonné ne
compte pas comme de l'activité à ses yeux.

**Solution validée en conditions réelles** : un sondage léger (~1.5s) tourne
en parallèle de l'abonnement aux indications. Résultat sur un essai de 30s
avec plusieurs rotations : connexion tenue sur toute la durée, **et les deux
mécanismes ont capturé un événement chacun** — une vraie indication GATT est
arrivée (payload vide, confirmant que l'accessoire notifie bien activement
mais sans la valeur dedans ; la relecture déclenchée en réaction l'a
récupérée avec une latence minimale), et le sondage a indépendamment
capturé un second événement. Le système hybride fonctionne comme prévu :
rapide quand l'indication passe, garanti sinon (latence max ~1.5s).

### ✅ Calibration — vérification interactive face par face

La correspondance "index = face - 1" n'avait été vérifiée que sur 2 points
de données (Phase 4 : faces 2 et 9). `tools/calibrate.py` permet de la vérifier
explicitement, autant de fois qu'on veut, avant de s'y fier pour de vraies
automatisations Home Assistant : à chaque essai, on indique le numéro de
la face qu'on s'apprête à tester, puis on tourne — le script confirme ou
signale un désaccord, et donne un résumé final (X/Y essais corrects, liste
des désaccords s'il y en a).

Réutilise la même logique de connexion que la Phase 5 (indications +
sondage de maintien) ; la logique de résumé (`summarize()`) est testée
indépendamment de tout matériel.

### ✅ Phase 6 — Pont MQTT vers Home Assistant — prêt à tester

Transforme le script de test (Phase 5) en service tournant en continu :
reconnexion automatique en boucle (au lieu de s'arrêter après une durée
fixe), et publication de chaque événement vers MQTT au format découverte
automatique de Home Assistant (intégration
[MQTT Event](https://www.home-assistant.io/integrations/event.mqtt/)) —
vérifié sur la documentation officielle, puis testé contre un **vrai
broker Mosquitto local**, avec un abonné indépendant simulant Home
Assistant pour confirmer le format des messages reçus.

- `hapble/mqtt_bridge.py` : construit le payload de découverte (topic
  `homeassistant/event/nanoleaf_remote_rotation/config`, 12 `event_types`
  `face_1`...`face_12`, regroupé sous un appareil "Nanoleaf Remote" dans
  l'UI Home Assistant) et le payload d'état (`{"event_type": "face_N"}`).
- `tools/bridge.py` : boucle de reconnexion BLE indéfinie autour de la logique de
  la Phase 5, avec publication MQTT à chaque événement détecté (indication
  ou sondage).
- **Correctif de concurrence** ajouté à cette occasion : la boucle de
  sondage et les callbacks déclenchés par une indication peuvent désormais
  dialoguer en même temps sur la même connexion (ce qui n'arrivait jamais
  dans les scripts de test précédents, tous séquentiels) — un verrou
  partagé (`HapBleAccessory.request_lock`) sérialise les échanges pour
  éviter qu'une réponse soit lue par la mauvaise requête. Vérifié par un
  test dédié : sans verrou, l'entrelacement se produit bien (confirmant
  que le test est pertinent) ; avec verrou, chaque écriture est toujours
  immédiatement suivie de sa propre lecture.

Configuration via variables d'environnement (`MQTT_HOST`, `MQTT_PORT`,
`MQTT_USERNAME`, `MQTT_PASSWORD` — toutes optionnelles, défaut
`localhost:1883` sans authentification), ou via un fichier `.env` à la
racine du projet (voir `.env.example` — pratique pour ne pas avoir à les
`export` à chaque session de terminal).

**Pas encore vérifié** : le comportement sur une durée de fonctionnement de
plusieurs heures/jours (fuite mémoire, dérive du compteur de nonce après un
très grand nombre de messages, robustesse du broker MQTT distant en cas de
coupure réseau prolongée).

## Installation

Ce projet utilise [Poetry](https://python-poetry.org/) pour l'environnement,
les dépendances, et les scripts à lancer.

```bash
poetry install
```

Ça crée un environnement virtuel dans `.venv/` (config dans `poetry.toml`,
donc visible et rangé dans le dossier du projet plutôt que caché dans le
cache global de Poetry) et y installe `bleak` et `cryptography`.

Pour lancer une commande dedans, deux façons équivalentes :

```bash
poetry run <commande>      # une commande ponctuelle
poetry shell                # ou : active le venv pour toute la session shell
```

## Lancer le test Phase 1

```bash
poetry run phase1
```

Résultat attendu : la liste des services/caractéristiques GATT de la
Remote (avec le service `00000055-0000-1000-8000-0026bb765291` qui doit
apparaître dedans), puis la valeur de `Pairing Features`.

Pour voir chaque trame échangée en hexadécimal (utile en cas de souci) :
mettre `LOG_LEVEL = logging.DEBUG` en haut de `tools/phase1.py`.

## Lancer le test Phase 2 (Pair-Setup)

D'abord, sans matériel, pour valider la logique interne :

```bash
poetry run pytest tests/test_pairing_e2e_fake.py
```

Puis contre le vrai appareil (code à 8 chiffres requis — étiquette sous la
Remote ou app Nanoleaf) :

```bash
poetry run phase2
# ou directement : poetry run phase2 123-45-678
```

En cas d'échec à cause d'une déconnexion en plein échange (fenêtre de
connexion courte de l'accessoire, voir Phase 1) : relancer simplement,
rien n'est persisté avant la fin réussie de M6.

## Lancer le test Phase 3 (Pair-Verify)

D'abord, sans matériel :

```bash
poetry run pytest tests/test_pair_verify_e2e_fake.py
```

Puis contre le vrai appareil (nécessite un `pairing.json` existant, produit
par `phase2` — ne redemande PAS le code à 8 chiffres) :

```bash
poetry run phase3
```

Egalement recommandé, à tout moment (aucun matériel requis, vérifie la
conformité de `srp.py` au vecteur de test officiel de la spec Apple) :

```bash
poetry run pytest tests/test_srp_official_vector.py
```

## Lancer le test Phase 4 (session chiffrée + lecture d'événement)

```bash
poetry run phase4
```

Réutilise `pairing.json` (Pair-Verify, pas de code à ressaisir), puis tente
de lire chacune des 8 instances de `ProgrammableSwitchEvent`. Essaie de
faire tourner la Remote juste avant/pendant l'exécution.

## Récapitulatif des commandes

| Commande               | Nécessite du matériel ? | Ce qu'elle fait                          |
|-------------------------|:------------------------:|-------------------------------------------|
| `poetry run pytest tests/test_srp_official_vector.py` | Non                      | Vérifie `srp.py` contre le vecteur officiel Apple |
| `poetry run pytest tests/test_pairing_e2e_fake.py` | Non                     | Pair-Setup complet contre un faux accessoire |
| `poetry run pytest tests/test_pair_verify_e2e_fake.py`  | Non                     | Pair-Verify complet contre un faux accessoire |
| `poetry run phase1`     | Oui                      | Transport/framing HAP-BLE (Pairing Features) |
| `poetry run phase2 <code>` | Oui                   | Pair-Setup réel (code à 8 chiffres)       |
| `poetry run phase3`     | Oui                      | Pair-Verify réel (réutilise `pairing.json`) |
| `poetry run phase4`     | Oui                      | Session chiffrée + lecture d'événement    |
| `poetry run phase5 [durée]` | Oui                  | Abonnement aux indications (écoute en direct) |
| `poetry run calibrate` | Oui                        | Vérification interactive face par face |
| `poetry run bridge`     | Oui                      | Service continu : publie les événements vers MQTT/Home Assistant |

## Lancer le test Phase 5 (indications, écoute en direct)

```bash
poetry run phase5          # ecoute 30s par defaut
poetry run phase5 60       # ou une duree personnalisee, en secondes
```

Fais tourner la Remote vers plusieurs faces différentes pendant la fenêtre
d'écoute pour voir plusieurs événements arriver.

## Lancer la calibration (vérification face par face)

```bash
poetry run calibrate
```

Pour chaque essai : tape le numéro de la face (1-12), puis tourne la
Remote vers cette face. Tape `q` pour arrêter et voir le résumé.

## Lancer le pont MQTT (Phase 6)

Nécessite un broker MQTT accessible (ex : l'add-on Mosquitto de Home
Assistant, ou tout broker MQTT existant). Configuration par variables
d'environnement :

```bash
export MQTT_HOST=192.168.1.10      # adresse de ton broker (defaut: localhost)
export MQTT_PORT=1883              # (defaut: 1883)
export MQTT_USERNAME=...           # optionnel
export MQTT_PASSWORD=...           # optionnel

poetry run bridge
```

Tourne indéfiniment (Ctrl+C pour arrêter), se reconnecte automatiquement en
cas de coupure BLE. Home Assistant devrait découvrir automatiquement une
entité **"Nanoleaf Remote Position"** (type *event*) — chaque rotation y
apparaît comme un événement `face_1` à `face_12`, exploitable directement
dans une automatisation HA (déclencheur "État" sur cette entité, filtré par
attribut `event_type`).

## Sources utilisées pour les constantes du protocole

- UUID du service Pairing / caractéristiques Pair Setup, Pair Verify,
  Pairing Features, et valeurs TLV8 (`kTLVType_*`) : code source de
  [pyhomekit](https://github.com/henridwyer/pyhomekit) (`constants.py`).
- Format de l'en-tête PDU HAP-BLE (Control Field, fragmentation) :
  idem, `ble.py` (`HapBlePduRequestHeader`/`HapBlePduResponseHeader`).
- Chaînes de salt/info HKDF pour Pair-Setup et Pair-Verify : recoupées
  entre plusieurs implémentations indépendantes (dont `aanon4/HomeKit`) et
  des échanges du forum développeurs Apple sur les pièges non documentés
  du HAP non-commercial.

Comme toujours en reverse engineering : ces constantes sont vérifiées par
recoupement de sources, mais seul un test contre le vrai appareil (Phase 1)
confirmera qu'elles s'appliquent bien au firmware de cette Remote précise.

## Contribuer

Les issues et pull requests sont bienvenues, en français comme en anglais —
voir `CONTRIBUTING.md` (en anglais) pour la configuration de développement
et les vérifications à faire tourner localement.

## Sécurité

`pairing.json` contient une clé privée : voir [`SECURITY.md`](../SECURITY.md) avant de le
partager ou de le coller dans une issue. Pour signaler une faille dans
l'implémentation cryptographique elle-même, merci d'utiliser la
déclaration privée de vulnérabilité de GitHub plutôt qu'une issue publique
— détails dans [`SECURITY.md`](../SECURITY.md).

## Licence

[MIT](../LICENSE). Voir aussi [`CHANGELOG.md`](../CHANGELOG.md) pour l'historique des versions.

