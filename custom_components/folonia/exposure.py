"""Ce que la maison montre à Oscar, décidé ici, à chaque requête.

Une entité n'est visible que si elle est **à la fois** exposée aux assistants vocaux
(Paramètres → Assistants vocaux → Exposer, le mécanisme de Home Assistant) **et**
cochée dans la page Folonia. Home Assistant expose d'office certaines
entités nouvelles à Assist : sans la seconde condition, « par défaut, rien » ne
tiendrait pas.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from homeassistant.components.homeassistant.exposed_entities import async_should_expose
from homeassistant.core import HomeAssistant, State, callback
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from . import protocol
from .const import (
    ASSISTANT,
    CONF_CONTROL,
    CONF_EXEMPT,
    CONF_LOCK_OPEN,
    CONF_LOCK_READ,
    CONF_READ,
    CONTROL_DOMAINS,
    DEFAULT_LOCK_OPEN,
    DEFAULT_LOCK_READ,
    DOMAIN,
    LOCKED_COVER_CLASSES,
    LOCKED_COVER_SERVICES,
    LOCKED_DOMAINS,
    LOCKED_SERVICES,
    SENSITIVE_CLASSES,
    SENSITIVE_DOMAINS,
)
from .protocol import MAX_ENTITIES, state_payload


@callback
def _own(hass: HomeAssistant, entity_id: str) -> bool:
    """Les entités de l'intégration elle-même (son interrupteur, sa liaison) : jamais montrées.

    Home Assistant expose d'office les interrupteurs nouveaux à Assist : sans cette
    exclusion, « Accès d'Oscar » serait proposé à Oscar.
    """
    entry = er.async_get(hass).async_get(entity_id)
    return entry is not None and entry.platform == DOMAIN


@callback
def exposed_to_assist(hass: HomeAssistant) -> list[str]:
    """Les entités exposées aux assistants vocaux, triées : ce que l'utilisateur peut cocher."""
    return sorted(
        state.entity_id
        for state in hass.states.async_all()
        if async_should_expose(hass, ASSISTANT, state.entity_id) and not _own(hass, state.entity_id)
    )


@callback
def _visible(hass: HomeAssistant, chosen: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    found: list[str] = []
    for entity_id in chosen:
        if (
            entity_id in seen
            or hass.states.get(entity_id) is None
            or not async_should_expose(hass, ASSISTANT, entity_id)
            or _own(hass, entity_id)
        ):
            continue
        seen.add(entity_id)
        found.append(entity_id)
    return found[:MAX_ENTITIES]


@callback
def allowed_control(hass: HomeAssistant, options: Mapping[str, Any]) -> list[str]:
    """Les entités qu'Oscar peut commander à cet instant : cochées, présentes, exposées."""
    chosen: Iterable[str] = options.get(CONF_CONTROL, [])
    return [e for e in _visible(hass, chosen) if e.split(".", 1)[0] in CONTROL_DOMAINS]


@callback
def allowed(hass: HomeAssistant, options: Mapping[str, Any]) -> list[str]:
    """Les entités qu'Oscar peut lire à cet instant : cochées (en lecture ou en commande)."""
    chosen: Iterable[str] = options.get(CONF_READ, [])
    return _visible(hass, [*chosen, *allowed_control(hass, options)])


@callback
def controllable(hass: HomeAssistant) -> list[str]:
    """Parmi les entités exposées à Assist, celles d'un domaine qu'Oscar sait commander."""
    return [e for e in exposed_to_assist(hass) if e.split(".", 1)[0] in CONTROL_DOMAINS]


@callback
def opens_home(state: State) -> bool:
    """Serrures, alarme, portail, porte de garage : ce qui ouvre la maison."""
    return state.domain in LOCKED_DOMAINS or (
        state.domain == "cover" and state.attributes.get("device_class") in LOCKED_COVER_CLASSES
    )


@callback
def needs_code(state: State, service: str, data: Mapping[str, Any]) -> bool:
    """Ce qui ouvre la maison : déverrouiller, désarmer, ouvrir une porte ou un portail.

    Verrouiller, armer une alarme désarmée, fermer, arrêter : sans code. Changer le mode d'une
    alarme armée ou déclenchée, oui : c'est l'affaiblir ou la faire taire. `service` est
    `domaine.service`. Les réglages (`lock_open`, exemptions) sont appliqués par
    `command_guarded`.
    """
    if not opens_home(state):
        return False
    if service.startswith("alarm_control_panel.alarm_arm_"):
        return state.state != "disarmed"
    if service in LOCKED_SERVICES:
        return True
    if service not in LOCKED_COVER_SERVICES:
        return False
    if service == "cover.set_cover_position":
        position = data.get("position", 0)
        return not isinstance(position, (int, float)) or position > 0
    return True


@callback
def lock_read(options: Mapping[str, Any]) -> bool:
    """Code vocal à la lecture des appareils sensibles : coché tant que rien ne dit le contraire."""
    return bool(options.get(CONF_LOCK_READ, DEFAULT_LOCK_READ))


@callback
def lock_open(options: Mapping[str, Any]) -> bool:
    """Code pour déverrouiller, désarmer, ouvrir : coché tant que rien ne dit le contraire."""
    return bool(options.get(CONF_LOCK_OPEN, DEFAULT_LOCK_OPEN))


@callback
def exempt(options: Mapping[str, Any]) -> frozenset[str]:
    """Les appareils que l'utilisateur a choisi de laisser sans code, lus et commandés."""
    chosen = options.get(CONF_EXEMPT, [])
    if not isinstance(chosen, list):
        return frozenset()
    return frozenset(e for e in chosen if isinstance(e, str))


@callback
def read_guarded(state: State, options: Mapping[str, Any]) -> bool:
    """L'état de cette entité ne sort qu'avec le bon code : sensible, case cochée, non exemptée."""
    return lock_read(options) and is_sensitive(state) and state.entity_id not in exempt(options)


@callback
def command_guarded(
    state: State, service: str, data: Mapping[str, Any], options: Mapping[str, Any]
) -> bool:
    """Cette commande exige le code : elle ouvre la maison, case cochée, appareil non exempté."""
    return (
        lock_open(options)
        and state.entity_id not in exempt(options)
        and needs_code(state, service, data)
    )


@callback
def area_entry(hass: HomeAssistant, entity_id: str) -> ar.AreaEntry | None:
    """La pièce de l'entité, ou à défaut celle de son appareil."""
    entry = er.async_get(hass).async_get(entity_id)
    if entry is None:
        return None
    area_id = entry.area_id
    if area_id is None and entry.device_id:
        device = dr.async_get(hass).async_get(entry.device_id)
        area_id = device.area_id if device else None
    if area_id is None:
        return None
    return ar.async_get(hass).async_get_area(area_id)


@callback
def area_name(hass: HomeAssistant, entity_id: str) -> str | None:
    """Le nom de la pièce de l'entité, ou à défaut de celle de son appareil."""
    area = area_entry(hass, entity_id)
    return area.name if area else None


@callback
def entity_aliases(hass: HomeAssistant, entity_id: str) -> list[str]:
    """Les alias d'Assist de l'entité, tels que l'utilisateur les a écrits ; aucun sans registre.

    La valeur spéciale de Home Assistant 2026.4 et suivants (« le nom de l'entité ») n'est pas
    un alias écrit : elle n'est pas rendue.
    """
    entry = er.async_get(hass).async_get(entity_id)
    return protocol.alias_texts(entry.aliases) if entry else []


@callback
def describe(hass: HomeAssistant, entity_id: str, mode: str = "read") -> dict[str, Any] | None:
    """L'entité telle qu'Oscar la voit : nom, pièce, alias, relus à chaque liste."""
    state = hass.states.get(entity_id)
    if state is None:
        return None
    area = area_entry(hass, entity_id)
    return protocol.entity_payload(
        entity_id,
        state.name,
        area.name if area else None,
        state.attributes.get("device_class"),
        mode,
        entity_aliases(hass, entity_id),
        area.aliases if area else (),
    )


@callback
def snapshot(state: State) -> dict[str, Any]:
    return state_payload(
        state.entity_id,
        state.state,
        state.attributes.get("unit_of_measurement"),
        dict(state.attributes),
        state.last_changed.isoformat(),
    )


@callback
def is_sensitive(state: State) -> bool:
    """Présence, serrures, alarme, ouvertures : ce qui dit quand la maison est vide."""
    return state.domain in SENSITIVE_DOMAINS or (
        state.attributes.get("device_class") in SENSITIVE_CLASSES
    )


KIND_LABELS: dict[str, str] = {
    "light": "lumière",
    "switch": "interrupteur",
    "cover": "volet ou porte",
    "climate": "chauffage",
    "sensor": "capteur",
    "binary_sensor": "détecteur",
    "lock": "serrure",
    "alarm_control_panel": "alarme",
    "person": "présence",
    "device_tracker": "présence",
    "media_player": "lecteur",
    "fan": "ventilateur",
    "humidifier": "humidificateur",
    "water_heater": "chauffe-eau",
    "vacuum": "aspirateur",
    "scene": "scène",
    "script": "script",
    "input_boolean": "interrupteur virtuel",
    "weather": "météo",
}
CLASS_LABELS: dict[str, str] = {
    "door": "porte",
    "garage_door": "porte de garage",
    "window": "fenêtre",
    "motion": "mouvement",
    "occupancy": "présence",
    "presence": "présence",
    "opening": "ouverture",
    "temperature": "température",
    "humidity": "humidité",
    "battery": "batterie",
    "power": "puissance",
    "energy": "énergie",
    "illuminance": "luminosité",
    "smoke": "fumée",
    "gas": "gaz",
    "moisture": "fuite d’eau",
    "lock": "serrure",
    "shutter": "volet",
    "blind": "store",
    "gate": "portail",
}
STATE_LABELS: dict[str, str] = {
    "on": "allumé",
    "off": "éteint",
    "open": "ouvert",
    "closed": "fermé",
    "opening": "en ouverture",
    "closing": "en fermeture",
    "locked": "verrouillé",
    "unlocked": "déverrouillé",
    "home": "à la maison",
    "not_home": "absent",
    "unknown": "inconnu",
    "unavailable": "indisponible",
    "idle": "au repos",
    "playing": "en lecture",
    "paused": "en pause",
    "heat": "chauffe",
    "cool": "refroidit",
    "auto": "automatique",
    "armed_away": "armée",
    "armed_home": "armée à la maison",
    "disarmed": "désarmée",
    "cleaning": "en nettoyage",
    "docked": "sur sa base",
}


@callback
def kind_label(state: State) -> str:
    """« porte de garage », « température », « lumière » : ce que c'est, en un mot."""
    device_class = state.attributes.get("device_class")
    if isinstance(device_class, str) and device_class in CLASS_LABELS:
        return CLASS_LABELS[device_class]
    return KIND_LABELS.get(state.domain, state.domain)


@callback
def value_label(state: State) -> str:
    """La valeur du moment, dite en français : « fermé », « 21,5 °C », « 42 % »."""
    raw = state.state
    if raw in STATE_LABELS:
        label = STATE_LABELS[raw]
        if state.domain == "binary_sensor" and raw in ("on", "off"):
            device_class = state.attributes.get("device_class")
            if device_class in ("door", "window", "garage_door", "opening", "gate"):
                return "ouvert" if raw == "on" else "fermé"
            if device_class in ("motion", "occupancy", "presence"):
                return "détecté" if raw == "on" else "rien"
            if device_class in ("smoke", "gas", "moisture"):
                return "alerte" if raw == "on" else "normal"
        return label
    unit = state.attributes.get("unit_of_measurement")
    try:
        number = float(raw)
    except (TypeError, ValueError):
        return raw
    text = (
        f"{number:.1f}".rstrip("0").rstrip(".").replace(".", ",")
        if number != int(number)
        else str(int(number))
    )
    return f"{text} {unit}" if unit else text


@callback
def choice_label(hass: HomeAssistant, entity_id: str) -> str:
    """« Porte du garage — Garage · porte de garage : fermé », avec un repère si sensible."""
    state = hass.states.get(entity_id)
    if state is None:
        return entity_id
    area = area_name(hass, entity_id)
    label = f"{state.name} — {area}" if area else state.name
    label = f"{label} · {kind_label(state)} : {value_label(state)}"
    return f"{label} ⚠" if is_sensitive(state) else label
