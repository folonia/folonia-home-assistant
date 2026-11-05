# Sécurité

Cette intégration tourne dans votre Home Assistant et commande de vrais appareils : serrures,
alarme, portail. Nous prenons au sérieux tout ce qui pourrait contourner vos choix.

## Signaler une faille

Ne l’exposez pas dans une issue publique. Écrivez à contact@folonia.fr, ou passez par **Report a
vulnerability** dans l’onglet **Security** de ce dépôt. Dites ce que vous observez, la version de
l’intégration et de Home Assistant, et comment le reproduire. Nous répondons sous sept jours et
nous vous tenons au courant du correctif.

## Ce qui nous intéresse d’abord

- Lire ou commander un appareil qui n’est pas coché, ou contourner le code ou le mot de passe.
- Récupérer un secret : le secret de la liaison, ou l’empreinte du code.
- Accéder à la page Folonia ou à ses commandes WebSocket sans être administrateur.
- Faire sortir de Home Assistant autre chose que ce que décrit la section **Données** du README.

## Versions suivies

Seule la dernière version publiée reçoit les correctifs. Si une version devient dangereuse, nous
la retirons et Home Assistant vous propose la mise à jour.

## Limites connues

- Oscar vous reconnaît à votre numéro : un numéro usurpé est traité comme le vôtre, d’où le code sur
  ce qui ouvre la maison.
- Le code ou le mot de passe passe par le service le temps de chaque demande. Folonia ne le garde
  pas, mais le verrou arrête un essai à l’aveugle, pas un service compromis qui l’aurait capté.
- Le code ne couvre que les appareils que Home Assistant déclare du bon type : voir le README.
