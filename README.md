# Folonia pour Home Assistant

Au téléphone, demandez à Oscar si la porte du garage est fermée, quelle température il fait au
salon, ou d’éteindre la lumière de la cuisine. Cette intégration relie votre Home Assistant à
votre abonnement [Folonia](https://folonia.fr) : Oscar lit et commande les seuls appareils que
**vous** choisissez.

[![Ouvrir dans HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=folonia&repository=folonia-home-assistant&category=integration)

## Ce qu’Oscar peut faire

- **Lire** l’état des appareils que vous partagez : portes, fenêtres, volets, lumières,
  températures, chauffage, alarme, présence.
- **Commander** ceux que vous cochez en commande : allumer, éteindre, ouvrir, fermer, arrêter,
  verrouiller, armer, régler une température, une position ou une luminosité, lancer une scène.
- Rien d’autre : il ne voit ni ne commande ce que vous n’avez pas coché.

## Le code ou le mot de passe

Folonia, c’est d’abord le mains libres : le secret se dit à voix haute. Deux secrets possibles,
choisis dans les options de l’intégration ; l’un ou l’autre suffit :

- un **code chiffré** de quatre à huit chiffres, dit à voix haute ou **tapé sur le clavier du
  téléphone** (puis dièse) si vous n’êtes pas seul ;
- un **mot de passe parlé** : un mot ou une courte phrase, par exemple « dragon rouge ».
  Majuscules, accents et ponctuation ne comptent pas. Quatre lettres au moins ; six lettres ou
  deux mots sont conseillés.

Ils sont vérifiés **chez vous** : seule leur empreinte est gardée dans Home Assistant, chacun se
règle et s’efface séparément. Folonia ne les enregistre pas : ce que vous dites ou tapez est
transmis avec la demande, puis oublié.

## Les réglages

**Paramètres**, **Appareils et services**, **Folonia**, **Configurer** ouvre un menu en quatre
parties, avec un résumé (appareils lus, commandés, sans code ; secret réglé ou non) :
**Ce qu’Oscar peut lire**, **Ce qu’Oscar peut commander**, **Appareils sans code**, **Code et
protections**. Chaque partie s’enregistre seule et garde les autres réglages. Les appareils se
choisissent dans le sélecteur de Home Assistant, avec recherche ; les appareils sous protection
sont rappelés, avec leur valeur du moment (⚠), dans la description de l’étape. Une liste qui
demande un secret alors qu’aucun n’est réglé est enregistrée, puis **Code et protections**
s’ouvre : d’ici là, Oscar refuse ce qui demande un code.

Chaque protection est **cochée par défaut, expliquée, et se décoche** : nous proposons ce qu’il
faut pour la sécurité, mais si vous préférez faire autrement, c’est votre choix, sous votre
responsabilité.

| Réglage | Par défaut | Ce qu’il fait |
| --- | --- | --- |
| **Code pour déverrouiller, désarmer, ouvrir** | coché | Déverrouiller une serrure, désarmer l’alarme, ouvrir le portail ou la porte de garage demandent le code ou le mot de passe. Décoché, quiconque appelle depuis votre numéro peut le demander à Oscar. |
| **Code pour lire les appareils sensibles** | coché | La présence, une serrure, l’alarme, une porte ou une fenêtre (marquées d’un ⚠) disent quand votre maison est vide : Oscar n’en dit l’état qu’après le code ou le mot de passe. |
| **Appareils sans code** | aucun | Parmi les appareils partagés sous protection, ceux qu’Oscar lit et commande sans code, même cases cochées. Par exemple la porte du garage, pour demander « J’ai bien fermé le garage ? » sans code. |
| **Code chiffré**, **Mot de passe parlé** | aucun | Les secrets, l’un ou l’autre. Laissez le champ vide pour garder ce qui est réglé ; une case efface chacun. |

- Verrouiller, armer, fermer et arrêter ne demandent jamais de code.
- Un secret n’est exigé que si une protection cochée porte sur un appareil partagé et non
  exempté ; sinon, rien n’est imposé.
- Cinq essais faux en vingt-quatre heures, code et mot de passe ensemble, dits ou tapés, en
  lecture comme en commande, bloquent le verrou ; Home Assistant vous prévient. Éteignez puis
  rallumez « Accès d’Oscar », ou enregistrez un nouveau secret, pour débloquer.
- Une installation plus ancienne garde son code et ses choix ; les nouveaux réglages y prennent
  leur valeur par défaut.

## Vos garanties

- **Votre maison n’expose rien.** Home Assistant ouvre une connexion sortante vers Folonia :
  aucun port ouvert, aucune redirection de routeur.
- **Aucun jeton de Home Assistant ne sort.** La liaison est appariée une fois par un code de
  huit caractères, et ne permet que les questions et commandes prévues.
- **Par défaut, Oscar ne voit rien.** Vous choisissez un appareil à la fois, parmi ceux déjà
  exposés aux assistants vocaux. La règle est appliquée chez vous, à chaque demande.
- **Tout est au journal de bord.** Chaque lecture, chaque commande, chaque code refusé, jamais
  le code ni le mot de passe lui-même.
- **Un interrupteur coupe tout.** « Accès d’Oscar » éteint : la liaison est fermée, rien ne
  sort ; Oscar dit que l’accès est coupé.
- **Rien n’est conservé chez Folonia.** Ce qu’Oscar lit sert à répondre pendant l’appel, puis
  est oublié.

## Installer

Il faut un abonnement Folonia, Home Assistant 2025.2 ou plus récent, et
[HACS](https://hacs.xyz).

1. Touchez le bouton **Ouvrir dans HACS** ci-dessus, ou, dans HACS, menu (les trois points),
   **Dépôts personnalisés**, adresse `https://github.com/folonia/folonia-home-assistant`,
   catégorie **Intégration**. L’intégration rejoindra ensuite le magasin de HACS.
2. Installez **Folonia**, puis redémarrez Home Assistant.

## Relier votre maison

1. Sur [folonia.fr](https://folonia.fr), **Votre compte**, section **Maison** : **Obtenir un
   code** (dix minutes, une seule fois).
2. Dans Home Assistant : **Paramètres**, **Appareils et services**, **Ajouter une
   intégration**, **Folonia**, puis saisissez le code.
3. L’appareil **Folonia** apparaît, avec l’interrupteur **Accès d’Oscar** et le capteur
   **Liaison**.

## Choisir ce qu’Oscar lit et commande

1. Exposez les appareils voulus aux assistants vocaux : **Paramètres**, **Assistants vocaux**,
   onglet **Exposer**.
2. **Paramètres**, **Appareils et services**, **Folonia**, **Configurer** : choisissez ce
   qu’Oscar peut lire, puis ce qu’il peut commander ; dans **Code et protections**, choisissez un
   code, un mot de passe, ou les deux.

Pourquoi deux étapes ? Home Assistant expose d’office certains appareils nouveaux ; sans le
choix propre à Folonia, Oscar en verrait plus que vous ne l’avez décidé. Retirer l’exposition
retire aussi l’appareil à Oscar.

## Au téléphone

- « La porte du garage est fermée ? » (Oscar demande le code si la case est cochée et que la
  porte n’est pas exemptée.)
- « Il fait combien dans le salon ? »
- « Éteins la lumière de la cuisine. »
- « Ouvre le portail. » (Oscar demande le code ; vous le dites, ou vous dites « je le tape » et
  le tapez sur le clavier, puis dièse.)

Oscar ne répète jamais un code ni un mot de passe.

Si Home Assistant est éteint ou sans Internet, Oscar le dit tout de suite. Les proches de votre
abonnement et les appels d’essai n’ont pas accès à votre maison.

## Couper, délier

- **Couper, provisoirement** : éteignez **Accès d’Oscar**.
- **Délier depuis Folonia** : **Votre compte**, **Maison**, **Délier ma maison**.
- **Délier depuis Home Assistant** : supprimez l’intégration ; elle prévient Folonia.

## En cas de souci

- **« Code inconnu, expiré ou déjà utilisé »** : demandez un nouveau code dans votre espace.
- **« Folonia est injoignable »** : vérifiez l’accès à Internet de Home Assistant.
- **Rien à choisir** : aucun appareil n’est exposé aux assistants vocaux.
- **Liaison hors ligne** : elle se refait seule, avec un délai croissant (cinq minutes au plus).
- **Nouveau code demandé** : la maison a été déliée ; saisissez un nouveau code.
- **« Mettre à jour l’intégration Folonia »** : mettez-la à jour depuis HACS.

**Télécharger les diagnostics** donne l’état de la liaison et les dernières lignes du journal,
sans secret ni code.

## Données

Sortent de chez vous, seulement pendant un appel et sans être gardés par Folonia : le nom, la
pièce, le domaine et la classe des appareils cochés ; l’état des seuls appareils demandés
(quelques attributs : luminosité, position, températures, humidité) ; la version de
l’intégration. Folonia ne garde que la liaison (une empreinte de son secret, sa date), effacée
quand vous déliez votre maison. L’état lu passe, pendant l’appel, par le fournisseur
d’intelligence artificielle d’Oscar ; voir la politique de confidentialité de Folonia. Un code
ou un mot de passe dit à voix haute passe lui aussi par ce fournisseur ; un code tapé sur le
clavier, non : il ne passe que par Folonia, sans être enregistré.

## Développement

Protocole de la liaison : `custom_components/folonia/protocol.py`. Tests contre le cœur de Home
Assistant, avec un faux service Folonia :

```sh
uv venv --python 3.13 .venv
uv pip install --python .venv/bin/python -r requirements_test.txt
.venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/python -m pytest -q
```

Le banc de Home Assistant tourne sous Linux et macOS, pas sous Windows (WSL 2 ou la CI). En mode
avancé, le formulaire d’ajout propose l’adresse du service, pour un laboratoire.

## Licence

[Apache 2.0](LICENSE), © 2026 DEVGO.

---

## In English

Folonia links your Home Assistant to your Folonia subscription, so that Oscar, the phone
assistant, can read and control the devices **you** pick, among those already exposed to voice
assistants. Your home opens an outbound connection: no open port, no Home Assistant token leaves
your home. By default, unlocking, disarming, opening a gate or garage door, and reading
presence, locks, alarm, doors and windows require a secret checked locally: a four to eight
digit code, spoken or typed on the phone keypad, or a spoken password (a word or a short
phrase), either one. Each protection can be unticked and devices can be exempted: your choice,
your responsibility. Five wrong attempts in twenty-four hours block the lock. Every read and
command goes to the logbook; the “Oscar access” switch cuts everything. Install with HACS (custom repository for now, category Integration),
then add the Folonia integration with the eight-character code from your Folonia account.
Licensed under Apache 2.0.
