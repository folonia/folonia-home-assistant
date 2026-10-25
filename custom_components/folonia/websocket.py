"""Les commandes de la page Folonia, sur la connexion WebSocket de Home Assistant.

Réservées aux administrateurs. La page ne décide de rien : ce qu'elle envoie est recoupé ici
avec la liste permise (`settings`), puis enregistré dans les options de l'entrée, que la
liaison applique dès la requête suivante. Aucune empreinte de secret n'est jamais rendue :
seulement « réglé » ou non. Les alias d'un appareil, eux, sont ceux d'Assist : écrits dans le
registre des entités de Home Assistant, relus par la liaison à chaque liste.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er

from . import exposure, settings
from .const import CONF_LOCK_HASH, CONF_PHRASE_HASH, DOMAIN, LOCK_FAILURES, VERSION
from .link import FoloniaLink
from .protocol import MAX_ALIASES_SET, MAX_ENTITIES, MAX_NAME

#: Une liste d'identifiants d'entités, telle que la page l'envoie ; recoupée ensuite.
_ENTITY_IDS = vol.All([str], vol.Length(max=10_000))
#: Un secret à régler (texte) ou à effacer (`None`).
_SECRET = vol.Any(None, vol.All(str, vol.Length(max=256)))
#: Les alias voulus pour un appareil, tels que la page les envoie ; nettoyés ensuite.
_ALIASES = vol.All([vol.All(str, vol.Length(max=MAX_NAME))], vol.Length(max=MAX_ALIASES_SET))


@callback
def async_register(hass: HomeAssistant) -> None:
    websocket_api.async_register_command(hass, ws_settings)
    websocket_api.async_register_command(hass, ws_save)
    websocket_api.async_register_command(hass, ws_secret)
    websocket_api.async_register_command(hass, ws_journal)
    websocket_api.async_register_command(hass, ws_aliases)


@callback
def _entry(hass: HomeAssistant) -> ConfigEntry[FoloniaLink] | None:
    """L'installation Folonia chargée : une seule par maison."""
    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.state is ConfigEntryState.LOADED:
            return entry
    return None


@callback
def _not_loaded(connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    connection.send_error(
        msg["id"], "not_loaded", "L'intégration Folonia n'est pas chargée dans Home Assistant."
    )


@callback
def _own_entity(hass: HomeAssistant, entry: ConfigEntry, platform: str, key: str) -> str | None:
    return er.async_get(hass).async_get_entity_id(platform, DOMAIN, f"{entry.entry_id}-{key}")


@callback
def _payload(hass: HomeAssistant, entry: ConfigEntry[FoloniaLink]) -> dict[str, Any]:
    """Tout ce que la page affiche, d'après les options enregistrées et l'état de la liaison."""
    link = entry.runtime_data
    options = entry.options
    return {
        "version": VERSION,
        "link": {
            "enabled": link.enabled,
            "connected": link.connected,
            "stopped": link.stopped_reason,
            "switch": _own_entity(hass, entry, "switch", "access"),
            "sensor": _own_entity(hass, entry, "binary_sensor", "link"),
        },
        "devices": settings.describe_choices(hass, options),
        "max_shared": MAX_ENTITIES,
        "protections": {
            "lock_open": exposure.lock_open(options),
            "lock_read": exposure.lock_read(options),
        },
        "secrets": {
            "code": bool(options.get(CONF_LOCK_HASH)),
            "phrase": bool(options.get(CONF_PHRASE_HASH)),
        },
        "lock": {
            "locked": link.lock.is_locked(),
            "failures": len(link.lock.failures),
            "max_failures": LOCK_FAILURES,
        },
        "secret_needed": settings.needs_secret(hass, options),
    }


@callback
def _update(
    hass: HomeAssistant, entry: ConfigEntry[FoloniaLink], options: Mapping[str, Any]
) -> None:
    """Enregistre, et le verrou suit aussitôt : un secret changé le débloque.

    L'écouteur des options refait la même chose ensuite, sans effet de plus ; l'appeler ici
    permet de rendre tout de suite l'état du verrou à la page.
    """
    if hass.config_entries.async_update_entry(entry, options=dict(options)):
        entry.runtime_data.async_options_updated()


@websocket_api.websocket_command({vol.Required("type"): "folonia/settings"})
@websocket_api.require_admin
@callback
def ws_settings(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Les appareils exposés aux assistants vocaux et leurs choix, les protections, le verrou."""
    entry = _entry(hass)
    if entry is None:
        _not_loaded(connection, msg)
        return
    connection.send_result(msg["id"], _payload(hass, entry))


@websocket_api.websocket_command(
    {
        vol.Required("type"): "folonia/save",
        vol.Optional("read"): _ENTITY_IDS,
        vol.Optional("control"): _ENTITY_IDS,
        vol.Optional("exempt"): _ENTITY_IDS,
        vol.Optional("lock_open"): bool,
        vol.Optional("lock_read"): bool,
    }
)
@websocket_api.require_admin
@callback
def ws_save(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Lu, commandé, sans code, protections : recoupés avec la liste permise, puis enregistrés.

    Enregistrés même s'il faut alors un secret et qu'aucun n'est réglé : la réponse le dit
    (`secret_needed`), et Oscar refuse d'ici là ce qui demande un code.
    """
    entry = _entry(hass)
    if entry is None:
        _not_loaded(connection, msg)
        return
    options = settings.apply_choices(
        hass,
        entry.options,
        read=msg.get("read"),
        control=msg.get("control"),
        exempt=msg.get("exempt"),
        lock_open=msg.get("lock_open"),
        lock_read=msg.get("lock_read"),
    )
    _update(hass, entry, options)
    connection.send_result(msg["id"], _payload(hass, entry))


@websocket_api.websocket_command(
    {
        vol.Required("type"): "folonia/secret",
        vol.Optional("code"): _SECRET,
        vol.Optional("phrase"): _SECRET,
    }
)
@websocket_api.require_admin
@callback
def ws_secret(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Règle (texte) ou efface (`null`) le code chiffré, le mot de passe parlé, ou les deux.

    Tout ou rien : une saisie invalide, ou l'effacement du dernier secret alors qu'il protège
    encore un appareil partagé, n'enregistre rien. Seules les empreintes sont gardées.
    """
    entry = _entry(hass)
    if entry is None:
        _not_loaded(connection, msg)
        return
    changes = {name: msg[name] for name in settings.SECRETS if name in msg}
    try:
        options, weak = settings.apply_secrets(hass, entry.options, changes)
    except settings.SettingsError as err:
        connection.send_error(msg["id"], err.code, ERRORS[err.code])
        return
    _update(hass, entry, options)
    connection.send_result(msg["id"], {**_payload(hass, entry), "weak_phrase": weak})


@websocket_api.websocket_command({vol.Required("type"): "folonia/journal"})
@websocket_api.require_admin
@callback
def ws_journal(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Les dernières lignes du journal de l'intégration, les plus récentes d'abord."""
    entry = _entry(hass)
    if entry is None:
        _not_loaded(connection, msg)
        return
    lines = []
    for line in reversed(entry.runtime_data.journal.entries):
        entity_id = line.get("entity_id")
        state = hass.states.get(entity_id) if entity_id else None
        lines.append({**line, "name": state.name if state else entity_id})
    connection.send_result(msg["id"], {"entries": lines})


@websocket_api.websocket_command(
    {
        vol.Required("type"): "folonia/aliases",
        vol.Required("entity_id"): vol.All(str, vol.Length(max=255)),
        vol.Required("aliases"): _ALIASES,
    }
)
@websocket_api.require_admin
@callback
def ws_aliases(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Remplace les alias d'Assist d'un appareil que la page propose, puis rend la page.

    Écrits dans le registre des entités : Assist et Oscar les ont aussitôt, la liaison relit
    la liste à chaque appel.
    """
    entry = _entry(hass)
    if entry is None:
        _not_loaded(connection, msg)
        return
    try:
        settings.apply_aliases(hass, msg["entity_id"], msg["aliases"])
    except settings.SettingsError as err:
        connection.send_error(msg["id"], err.code, ERRORS[err.code])
        return
    connection.send_result(msg["id"], _payload(hass, entry))


#: Les messages des refus, tels que la page les montre si elle ne les connaît pas.
ERRORS = {
    "invalid_lock_code": "Le code est fait de quatre à huit chiffres.",
    "invalid_lock_phrase": (
        "Le mot de passe compte au moins quatre lettres ou chiffres, et soixante-quatre "
        "caractères au plus."
    ),
    "lock_code_required": (
        "Choisissez un code ou un mot de passe : une protection cochée porte sur un appareil "
        "partagé (serrure, alarme, portail, porte de garage, présence, porte ou fenêtre). "
        "Sinon, décochez-la, ou laissez l'appareil sans code."
    ),
    "alias_not_allowed": (
        "Cet appareil n'est pas exposé aux assistants vocaux : ses alias ne se modifient pas ici."
    ),
    "alias_not_editable": (
        "Cet appareil n'a pas d'identifiant unique dans Home Assistant : ses alias ne se "
        "modifient pas."
    ),
}
