# Nanoleaf Remote pour Home Assistant

[![CI](https://github.com/Jeromearsene/nanoleaf-remote-HA/actions/workflows/ci.yml/badge.svg)](https://github.com/Jeromearsene/nanoleaf-remote-HA/actions/workflows/ci.yml)
[![Validate](https://github.com/Jeromearsene/nanoleaf-remote-HA/actions/workflows/validate.yml/badge.svg)](https://github.com/Jeromearsene/nanoleaf-remote-HA/actions/workflows/validate.yml)
[![HACS](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://hacs.xyz)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

🇬🇧 [English](README.md) | 🇫🇷 Français (ce document)

Utilisez la **Nanoleaf Remote** (la télécommande HomeKit à 12 faces) dans Home Assistant **sans Apple Maison** : vous la tournez sur une face et Home Assistant reçoit un événement utilisable dans vos automatisations.

Elle dialogue directement avec la télécommande via le Bluetooth de Home Assistant (adaptateur local ou proxy Bluetooth ESPHome). Pas de broker MQTT, pas d'appareil Apple, pas de routeur Thread.

> **Avertissement** : projet indépendant, sans lien avec Apple ni Nanoleaf, fourni tel quel. Il repose sur une implémentation maison du protocole HomeKit sur Bluetooth LE qui n'a fait l'objet **d'aucun audit de sécurité indépendant**. Voir [`SECURITY.md`](SECURITY.md).

## Fonctionnalités

- Configuration depuis l'interface : découverte Bluetooth, appairage avec le code HomeKit à 8 chiffres, ou réutilisation d'un appairage existant.
- Une entité **Événement** avec les types `face_1` … `face_12`.
- Un capteur **Batterie**, lu directement sur la télécommande (si elle expose ce service HomeKit).
- Reconnexion automatique ; l'entité est indisponible quand la télécommande est hors de portée.
- **Calibration** guidée de la numérotation des faces (vous choisissez quelle face est 1, 2, 3…).
- Plusieurs télécommandes possibles, interface en français et en anglais.

## Prérequis

- Home Assistant 2025.1 ou plus récent, avec un adaptateur Bluetooth fonctionnel (ou un proxy Bluetooth ESPHome) à portée de la télécommande.
- [HACS](https://hacs.xyz).
- Une Nanoleaf Remote avec 2 piles AA, **supprimée d'Apple Maison** (elle n'accepte qu'un seul contrôleur).

## Installation

1. Dans HACS, ouvrez ⋮ → **Dépôts personnalisés**, ajoutez `https://github.com/Jeromearsene/nanoleaf-remote-HA` avec le type **Intégration**, puis **Télécharger** *Nanoleaf Remote* (ou utilisez le bouton : [![Ouvrir dans HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=Jeromearsene&repository=nanoleaf-remote-HA&category=integration)).
2. Redémarrez Home Assistant.
3. Dans **Paramètres → Appareils et services**, la télécommande peut apparaître dans *Découverts* ; sinon **Ajouter une intégration → Nanoleaf Remote**.
4. Choisissez **Appairer avec le code d'appairage** et saisissez le code à 8 chiffres imprimé sur la télécommande. Validez, puis **tournez la télécommande en continu** quelques secondes : elle n'émet que lorsqu'elle est éveillée, et Home Assistant l'attend jusqu'à 30 s.

### Déjà appairée avec les outils `hapble` ?

Si vous avez lancé les outils de recherche et possédez un `pairing.json`, la télécommande est toujours appairée avec lui et refuse un second appairage. Choisissez **Réutiliser un appairage existant** et collez le contenu de `pairing.json`. Home Assistant le vérifie d'abord auprès de la télécommande. Ne lancez pas les outils sur la même télécommande en même temps (une seule connexion à la fois).

## Utilisation

L'intégration crée un appareil avec une entité événement (par exemple `event.nanoleaf_remote_position` ; vérifiez l'identifiant exact dans vos entités) et un capteur de batterie (`sensor.nanoleaf_remote_battery`). À chaque fois que vous tournez la télécommande sur une face, l'entité enregistre un événement `face_N`. Le capteur de batterie est lu une fois par connexion (et toutes les 30 minutes en connexion permanente) et reste indisponible si la télécommande n'expose pas de service Batterie.

```yaml
automation:
  - alias: "Face 3 de la télécommande → scène du soir"
    triggers:
      - trigger: state
        entity_id: event.nanoleaf_remote_position
        attribute: event_type
        to: face_3
    actions:
      - action: scene.turn_on
        target:
          entity_id: scene.soiree
```

### Calibrer les faces

La télécommande signale ses faces dans son ordre interne, qui peut ne pas correspondre à la numérotation que vous attendez. Ouvrez **Paramètres → Appareils et services → Nanoleaf Remote → Configurer** :

- **Calibrer avec la télécommande** : pour chaque face, tournez la télécommande dessus, attendez une seconde, validez. Commencez par la face que vous voulez appeler 1 et suivez le même ordre pour les autres. Les automatisations sont suspendues pendant ce temps.
- **Coller une table** : 12 nombres séparés par des virgules, le Nᵉ étant la vraie face pour la Nᵉ position détectée (la table affichée par `poetry run calibrate`).

### Mode économie de piles (expérimental)

Par défaut, Home Assistant reste connecté à la télécommande et la lit toutes les 1,5 s. Dans **Configurer → Mode économie de piles (expérimental)**, il peut à la place écouter ses annonces Bluetooth et ne se connecter que lorsqu'on la tourne (comme Apple Maison), puis la relâcher après 10 s sans activité. Comptez 2 à 3 s de latence ; il faut un adaptateur Bluetooth qui entend la télécommande quand elle est réveillée. Cela devrait ménager les piles, mais ce n'est pas encore mesuré : dites-nous ce que vous observez. Désactivez-le pour revenir à la connexion permanente.

## Dépannage

| Symptôme | À vérifier |
| --- | --- |
| « Pas entendue par le Bluetooth de Home Assistant » | La télécommande n'émet que lorsqu'elle est éveillée : validez puis tournez-la en continu, près de l'adaptateur. Consultez le *moniteur d'annonces* de l'intégration Bluetooth. |
| « Refuse un nouvel appairage » | Elle est encore appairée ailleurs (Apple Maison, ou les outils `hapble`). Supprimez-la de là, ou utilisez **Réutiliser un appairage existant**. |
| « Appairage refusé » à l'import | La télécommande ne connaît plus cet appairage (par exemple après un reset). Appairez-la avec son code. |
| Elle clignote ou ne s'allume jamais | Deux piles AA neuves, placées en sens opposés comme indiqué. Elle doit s'allumer quand le couvercle se referme et changer de couleur quand on la tourne. En dernier recours : appuyez avec une épingle sur le bouton reset du logement des piles, puis ré-appairez. |
| Mauvais numéro de face | Lancez la calibration (ci-dessus). |

Activez les journaux de débogage avec `logger: logs: custom_components.nanoleaf_remote: debug` et joignez-les (sans secrets) à un ticket. Le téléchargement des diagnostics masque les clés d'appairage.

## Fonctionnement

La télécommande est un accessoire HomeKit Bluetooth avec 12 instances d'*interrupteur programmable*. L'intégration l'appaire une fois (HomeKit Pair-Setup), puis se connecte via le Bluetooth de Home Assistant, vérifie l'appairage (Pair-Verify) et lit les caractéristiques toutes les 1,5 s, ce qui maintient aussi la connexion (la télécommande coupe les connexions inactives après ~5 s). Le code du protocole est dans [`hapble/`](hapble/) et embarqué dans `custom_components/nanoleaf_remote/hapble/` (HACS n'installe que ce dossier). Le récit de la rétro-ingénierie est dans [`docs/hapble.fr.md`](docs/hapble.fr.md).

## Sécurité

Les clés d'appairage sont stockées dans l'entrée de configuration de Home Assistant, dans `.storage/`, **non chiffré**. Protégez votre dossier de configuration et vos sauvegardes. Détails et signalement de vulnérabilités : [`SECURITY.md`](SECURITY.md).

## Alternative : pont MQTT

Si Home Assistant ne peut pas joindre la télécommande en Bluetooth, un pont autonome peut tourner sur une autre machine et publier les événements en MQTT : voir [`docs/hapble.fr.md`](docs/hapble.fr.md#lancer-le-pont-mqtt-phase-6).

## Contribuer

Voir [`CONTRIBUTING.md`](CONTRIBUTING.md). Historique des versions : [`CHANGELOG.md`](CHANGELOG.md).

## Licence

[MIT](LICENSE).
