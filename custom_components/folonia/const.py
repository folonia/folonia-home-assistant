"""Constantes de l'intégration Folonia."""

from __future__ import annotations

DOMAIN = "folonia"
VERSION = "0.4.0"

#: Le service Folonia ; modifiable en mode avancé (laboratoire).
DEFAULT_URL = "https://folonia.fr"

CONF_CODE = "code"
CONF_URL = "url"
CONF_VERIFY_SSL = "verify_ssl"
CONF_LINK_ID = "link_id"
CONF_SECRET = "link_secret"
#: Entités qu'Oscar peut lire.
CONF_READ = "read"
#: Entités qu'Oscar peut commander ; elles sont aussi lisibles.
CONF_CONTROL = "control"
#: Deux secrets possibles pour le verrou vocal, l'un ou l'autre suffit : un code chiffré et un
#: mot de passe parlé, saisis dans les options ; seules leurs empreintes sont gardées.
CONF_LOCK_CODE = "lock_code"
CONF_LOCK_HASH = "lock_hash"
CONF_LOCK_SALT = "lock_salt"
CONF_LOCK_PHRASE = "lock_phrase"
CONF_PHRASE_HASH = "phrase_hash"
CONF_PHRASE_SALT = "phrase_salt"
#: Cases du formulaire qui effacent l'un ou l'autre secret ; elles ne sont pas gardées.
CONF_CLEAR_CODE = "clear_lock_code"
CONF_CLEAR_PHRASE = "clear_lock_phrase"
#: Code aussi pour lire les appareils sensibles : coché par défaut, y compris pour une
#: installation dont les options n'ont pas la clé ; décochable.
CONF_LOCK_READ = "lock_read"
DEFAULT_LOCK_READ = True
#: Code pour déverrouiller, désarmer, ouvrir : coché par défaut, y compris pour une installation
#: d'avant la case (0.3.0) ; décochable, sous la responsabilité de l'utilisateur.
CONF_LOCK_OPEN = "lock_open"
DEFAULT_LOCK_OPEN = True
#: Appareils partagés lus et commandés sans code, même cases cochées. Vide par défaut.
CONF_EXEMPT = "exempt"

#: Le mécanisme existant de Home Assistant : « exposer aux assistants vocaux » (Assist).
ASSISTANT = "conversation"

#: Ce qui dit quand une maison est vide : un avertissement les accompagne, et leur état n'est
#: rendu qu'avec le code vocal tant que `lock_read` est coché.
SENSITIVE_DOMAINS = frozenset({"lock", "alarm_control_panel", "person", "device_tracker"})
SENSITIVE_CLASSES = frozenset(
    {
        "door",
        "garage_door",
        "garage",
        "gate",
        "window",
        "opening",
        "lock",
        "motion",
        "occupancy",
        "presence",
    }
)

#: Les seuls services qu'Oscar peut demander, par domaine. Rien d'autre ne passe.
SERVICES: dict[str, frozenset[str]] = {
    "light": frozenset({"turn_on", "turn_off"}),
    "switch": frozenset({"turn_on", "turn_off"}),
    "input_boolean": frozenset({"turn_on", "turn_off"}),
    "fan": frozenset({"turn_on", "turn_off"}),
    "humidifier": frozenset({"turn_on", "turn_off"}),
    "water_heater": frozenset({"turn_on", "turn_off"}),
    "media_player": frozenset({"turn_on", "turn_off", "media_pause"}),
    "vacuum": frozenset({"start", "return_to_base"}),
    "cover": frozenset({"open_cover", "close_cover", "stop_cover", "set_cover_position"}),
    "climate": frozenset({"turn_on", "turn_off", "set_temperature"}),
    "lock": frozenset({"lock", "unlock"}),
    "alarm_control_panel": frozenset({"alarm_arm_away", "alarm_arm_home", "alarm_disarm"}),
    "scene": frozenset({"turn_on"}),
    "script": frozenset({"turn_on"}),
}
#: Les seules données acceptées avec un service : la clé, et ses bornes.
SERVICE_DATA: dict[str, tuple[str, float, float]] = {
    "light.turn_on": ("brightness_pct", 0, 100),
    "cover.set_cover_position": ("position", 0, 100),
    "climate.set_temperature": ("temperature", 5, 35),
}
#: Domaines qu'Oscar peut commander : ce qui est proposé dans les options.
CONTROL_DOMAINS = frozenset(SERVICES)

#: Ce qui ouvre la maison : serrures, alarme, et les ouvertures qui y donnent accès.
LOCKED_DOMAINS = frozenset({"lock", "alarm_control_panel"})
LOCKED_COVER_CLASSES = frozenset({"garage", "garage_door", "gate", "door"})
#: Sous code tant que `lock_open` est coché (par défaut) : déverrouiller, désarmer, ouvrir une
#: porte ou un portail (`set_cover_position` au-dessus de zéro aussi). Verrouiller, armer,
#: fermer et arrêter passent sans code.
LOCKED_SERVICES = frozenset({"lock.unlock", "alarm_control_panel.alarm_disarm"})
LOCKED_COVER_SERVICES = frozenset({"cover.open_cover", "cover.set_cover_position"})

#: Le mot de passe parlé : au moins quatre lettres ou chiffres (six, ou deux mots, conseillés),
#: soixante-quatre caractères au plus une fois normalisé.
PHRASE_MIN = 4
PHRASE_ADVISED = 6
PHRASE_MAX = 64

#: Codes et mots de passe faux tolérés en vingt-quatre heures avant le blocage du verrou.
LOCK_FAILURES = 5
LOCK_WINDOW_SECONDS = 24 * 3600
#: Un service Home Assistant qui ne répond pas dans ce délai : la commande est dite échouée.
SERVICE_TIMEOUT = 10

#: Lignes gardées en mémoire pour le diagnostic, en plus du journal de bord.
JOURNAL_SIZE = 200
