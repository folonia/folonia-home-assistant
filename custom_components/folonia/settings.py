"""Les réglages de Folonia : ce qui est permis, ce qui est enregistré, ce qui exige un secret.

La page Folonia n'est qu'un affichage : tout ce qu'elle envoie est recoupé ici avec la liste
permise (les entités exposées aux assistants vocaux), puis enregistré dans les options de
l'entrée. Les règles sont celles de 0.4.0 et 0.4.1 :

- Commander rend aussi lisible ; une exemption ne vaut que pour un appareil partagé qui peut
  être sous code (sensible, ou qui ouvre la maison), et tombe s'il ne l'est plus.
- Un secret n'est exigé que si une protection cochée porte sur un appareil partagé et non
  exempté. Des listes ou des protections qui le rendent nécessaire, faute d'en avoir un, sont
  enregistrées quand même : d'ici là, Oscar refuse ce qui demande un code, et la page le dit.
- Effacer le dernier secret alors qu'il protège encore quelque chose est refusé.
- Seules les empreintes des secrets sont gardées ; elles ne sortent jamais de ce module.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from typing import Any

from homeassistant.core import HomeAssistant, callback

from . import exposure
from .const import (
    CONF_CONTROL,
    CONF_EXEMPT,
    CONF_LOCK_HASH,
    CONF_LOCK_OPEN,
    CONF_LOCK_READ,
    CONF_LOCK_SALT,
    CONF_PHRASE_HASH,
    CONF_PHRASE_SALT,
    CONF_READ,
    CONTROL_DOMAINS,
)
from .voicelock import hash_code, normalize_lock_code, normalize_passphrase, passphrase_is_weak

#: Les deux secrets du verrou : nom dans la page, clés de l'empreinte, normalisation, erreur si
#: la saisie ne peut pas en être un.
SECRETS: dict[str, tuple[str, str, Callable[[str], str | None], str]] = {
    "code": (CONF_LOCK_HASH, CONF_LOCK_SALT, normalize_lock_code, "invalid_lock_code"),
    "phrase": (CONF_PHRASE_HASH, CONF_PHRASE_SALT, normalize_passphrase, "invalid_lock_phrase"),
}


#: Ce qui se lance sans avoir d'état propre.
STATELESS_DOMAINS = frozenset({"scene", "script", "button"})


class SettingsError(Exception):
    """Une saisie refusée : `code` est la clé du message (`invalid_lock_code`, …)."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@callback
def protectable(hass: HomeAssistant, entity_ids: Iterable[str]) -> list[str]:
    """Ce qui peut être sous code : sensible, ou qui ouvre la maison."""
    return [
        entity_id
        for entity_id in entity_ids
        if (state := hass.states.get(entity_id)) is not None
        and (exposure.is_sensitive(state) or exposure.opens_home(state))
    ]


@callback
def shared(
    hass: HomeAssistant, options: Mapping[str, Any]
) -> tuple[list[str], list[str], list[str]]:
    """Lu, commandé, sans code : les listes enregistrées, réduites à ce qui est permis.

    Une entité qui a perdu son exposition aux assistants vocaux en disparaît.
    """
    exposed = set(exposure.exposed_to_assist(hass))
    controllable = set(exposure.controllable(hass))
    read = [e for e in options.get(CONF_READ, []) if e in exposed]
    control = [e for e in options.get(CONF_CONTROL, []) if e in controllable]
    allowed = set(protectable(hass, {*read, *control}))
    exempt = [e for e in options.get(CONF_EXEMPT, []) if e in allowed]
    return read, control, exempt


@callback
def guarded(
    hass: HomeAssistant,
    read: list[str],
    control: list[str],
    exempt: set[str],
    lock_open: bool,
    lock_read: bool,
) -> bool:
    """Une protection cochée porte sur au moins un appareil partagé et non exempté."""
    for entity_id in dict.fromkeys((*control, *read)):
        state = hass.states.get(entity_id)
        if state is None or entity_id in exempt:
            continue
        if lock_open and entity_id in control and exposure.opens_home(state):
            return True
        if lock_read and exposure.is_sensitive(state):
            return True
    return False


@callback
def has_secret(options: Mapping[str, Any]) -> bool:
    return bool(options.get(CONF_LOCK_HASH) or options.get(CONF_PHRASE_HASH))


@callback
def needs_secret(hass: HomeAssistant, options: Mapping[str, Any]) -> bool:
    """Un secret manque : une protection cochée porte sur un appareil partagé, et aucun n'est
    réglé. Oscar refuse alors ce qui demande un code."""
    if has_secret(options):
        return False
    read, control, exempt = shared(hass, options)
    return guarded(
        hass, read, control, set(exempt), exposure.lock_open(options), exposure.lock_read(options)
    )


@callback
def apply_choices(
    hass: HomeAssistant,
    options: Mapping[str, Any],
    *,
    read: Iterable[str] | None = None,
    control: Iterable[str] | None = None,
    exempt: Iterable[str] | None = None,
    lock_open: bool | None = None,
    lock_read: bool | None = None,
) -> dict[str, Any]:
    """Les nouvelles options : ce qui est donné, recoupé avec la liste permise ; le reste gardé.

    Une liste donnée remplace l'ancienne ; une liste absente est gardée, réduite à ce qui est
    permis. Les secrets ne changent pas ici.
    """
    kept_read, kept_control, kept_exempt = shared(hass, options)
    exposed = set(exposure.exposed_to_assist(hass))
    controllable = set(exposure.controllable(hass))
    new_read = kept_read if read is None else list(dict.fromkeys(e for e in read if e in exposed))
    new_control = (
        kept_control
        if control is None
        else list(dict.fromkeys(e for e in control if e in controllable))
    )
    # Une exemption ne vaut que pour un appareil partagé qui peut être sous code : un appareil
    # retiré la perd, et ne reviendrait pas sans code s'il était partagé de nouveau.
    allowed = set(protectable(hass, {*new_read, *new_control}))
    chosen = kept_exempt if exempt is None else exempt
    new_exempt = list(dict.fromkeys(e for e in chosen if e in allowed))
    return {
        **options,
        CONF_READ: new_read,
        CONF_CONTROL: new_control,
        CONF_EXEMPT: new_exempt,
        CONF_LOCK_OPEN: exposure.lock_open(options) if lock_open is None else bool(lock_open),
        CONF_LOCK_READ: exposure.lock_read(options) if lock_read is None else bool(lock_read),
    }


@callback
def apply_secrets(
    hass: HomeAssistant, options: Mapping[str, Any], changes: Mapping[str, str | None]
) -> tuple[dict[str, Any], bool]:
    """Les options avec les secrets réglés (texte) ou effacés (`None`) ; rien n'est gardé en clair.

    Un texte vide garde ce qui est réglé. Tout est vérifié avant d'écrire quoi que ce soit :
    une saisie invalide, ou un effacement qui laisserait sans secret une protection qui porte
    sur un appareil partagé, lève `SettingsError`. Rend aussi : le mot de passe réglé est
    accepté mais déconseillé (court et d'un seul mot).
    """
    new = dict(options)
    cleared = False
    weak = False
    for name, value in changes.items():
        hash_key, salt_key, normalize, error = SECRETS[name]
        if value is None:
            cleared = cleared or hash_key in new
            new.pop(hash_key, None)
            new.pop(salt_key, None)
            continue
        if not value:
            continue
        secret = normalize(value)
        if secret is None:
            raise SettingsError(error)
        new[hash_key], new[salt_key] = hash_code(secret)
        if name == "phrase":
            weak = passphrase_is_weak(secret)
    if cleared and needs_secret(hass, new):
        raise SettingsError("lock_code_required")
    return new, weak


@callback
def describe_choices(hass: HomeAssistant, options: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Les appareils que la page propose : ceux exposés aux assistants vocaux, et leurs choix.

    Le type et la valeur du moment sont dits en français, comme dans le journal ; rien de ce
    qui est rendu ici ne sort de la maison.
    """
    read, control, exempt = shared(hass, options)
    read_set, control_set, exempt_set = set(read), set(control), set(exempt)
    devices: list[dict[str, Any]] = []
    for entity_id in exposure.exposed_to_assist(hass):
        state = hass.states.get(entity_id)
        if state is None:
            continue
        sensitive = exposure.is_sensitive(state)
        opens = exposure.opens_home(state)
        device_class = state.attributes.get("device_class")
        devices.append(
            {
                "entity_id": entity_id,
                "name": state.name,
                "area": exposure.area_name(hass, entity_id),
                "domain": state.domain,
                "device_class": device_class if isinstance(device_class, str) else None,
                "kind": exposure.kind_label(state),
                # Une scène ou un script n'a pas d'état à dire : leur « état » est une date.
                "state": None if state.domain in STATELESS_DOMAINS else exposure.value_label(state),
                "sensitive": sensitive,
                "opens_home": opens,
                "controllable": state.domain in CONTROL_DOMAINS,
                "protectable": sensitive or opens,
                "read": entity_id in read_set,
                "control": entity_id in control_set,
                "exempt": entity_id in exempt_set,
            }
        )
    return devices
