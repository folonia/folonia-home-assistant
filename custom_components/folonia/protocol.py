"""Protocole de la liaison Folonia (protocole 1).

Ce module ne dépend pas de Home Assistant : il décrit ce qui circule sur la liaison
et se teste seul.
"""

from __future__ import annotations

import ipaddress
import json
import random
import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from .voicelock import normalize_lock_code, normalize_passphrase

PROTOCOL = 1

#: Alphabet de Crockford : ni I, ni L, ni O, ni U.
CODE_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
CODE_LENGTH = 8

#: Bornes du protocole, les mêmes que celles du serveur.
MAX_ENTITIES = 200
MAX_READ = 20
MAX_MESSAGE_BYTES = 256 * 1024
MAX_NAME = 100
MAX_STATE = 255
MAX_UNIT = 16
MAX_TEXT_ATTRIBUTE = 64
#: Alias d'une entité ou d'une pièce transmis au plus, et leur longueur : ceux d'Assist.
MAX_ALIASES = 8
MAX_ALIAS = 60
#: Alias d'une entité que la page Folonia peut enregistrer, au plus ; chacun borné comme un nom.
MAX_ALIASES_SET = 20

#: Codes de fermeture du serveur.
CLOSE_REPLACED = 4000
CLOSE_UNLINKED = 4001
CLOSE_PROTOCOL = 4002
CLOSE_CAPACITY = 4003

#: Les seuls attributs transmis : de quoi dire un état, rien de plus.
ATTRIBUTES = (
    "brightness",
    "current_position",
    "current_temperature",
    "temperature",
    "hvac_action",
    "humidity",
    "current_humidity",
    "percentage",
)


def normalize_code(text: str) -> str | None:
    """Code tel qu'il est saisi : tirets et espaces ignorés, O lu zéro, I et L lus un."""
    code = "".join(text.upper().split()).replace("-", "")
    code = code.replace("O", "0").replace("I", "1").replace("L", "1")
    if len(code) != CODE_LENGTH or any(char not in CODE_ALPHABET for char in code):
        return None
    return code


def _is_local(host: str | None) -> bool:
    if not host:
        return False
    if host == "localhost" or host.endswith(".local"):
        return True
    try:
        return ipaddress.ip_address(host).is_private
    except ValueError:
        return False


def base_url(text: str) -> str | None:
    """Adresse du service, sans chemin final : `https://folonia.fr`. `None` si invalide."""
    parts = urlsplit(text.strip())
    if parts.scheme not in ("https", "http") or not parts.netloc:
        return None
    if parts.query or parts.fragment or parts.username or parts.password:
        return None
    # Le secret de la liaison ne circule en clair que sur le réseau local (un laboratoire).
    if parts.scheme == "http" and not _is_local(parts.hostname):
        return None
    return urlunsplit((parts.scheme, parts.netloc, parts.path.rstrip("/"), "", ""))


def pair_url(base: str) -> str:
    return f"{base}/v1/home/pair"


def link_url(base: str) -> str:
    """La liaison WebSocket : `https` devient `wss`, `http` devient `ws`."""
    parts = urlsplit(base)
    scheme = "wss" if parts.scheme == "https" else "ws"
    return urlunsplit((scheme, parts.netloc, f"{parts.path}/v1/home/link", "", ""))


def backoff(attempt: int, rng: random.Random | None = None) -> float:
    """Délai avant la reconnexion n° `attempt` (1, 2, …) : d'une seconde à cinq minutes.

    Avec aléa : des maisons coupées en même temps ne reviennent pas toutes ensemble.
    """
    ceiling = min(300.0, float(2 ** min(9, max(0, attempt - 1))))
    return ceiling * (0.5 + 0.5 * (rng or random).random())


def outcome_of_close(code: int | None) -> str:
    """Ce que signifie une fermeture du serveur pour la suite."""
    if code == CLOSE_REPLACED:
        return "replaced"
    if code == CLOSE_UNLINKED:
        return "unlinked"
    if code == CLOSE_PROTOCOL:
        return "protocol"
    if code == CLOSE_CAPACITY:
        return "capacity"
    return "lost"


# --- Messages ------------------------------------------------------------------------


def hello(component: str) -> str:
    return json.dumps({"type": "hello", "protocol": PROTOCOL, "component": component})


def overloaded(text: str) -> str | None:
    """Réponse à une requête en trop : refusée sans être exécutée, si elle a un identifiant."""
    request = parse_request(text)
    return error(request.id, "failed") if request else None


def bye(reason: str) -> str:
    return json.dumps({"type": "bye", "reason": reason})


def is_welcome(text: str) -> bool:
    try:
        message = json.loads(text)
    except (ValueError, RecursionError):
        return False
    return (
        isinstance(message, dict)
        and message.get("type") == "welcome"
        and message.get("protocol") == PROTOCOL
    )


_SERVICE = re.compile(r"[a-z_]+\.[a-z_]+")
_ENTITY_ID = re.compile(r"[a-z0-9_]{1,127}\.[a-z0-9_]{1,127}")
#: Données d'un service, au plus.
MAX_DATA_KEYS = 4
#: Le secret du verrou vocal tel qu'il arrive, au plus : code chiffré ou mot de passe parlé.
MAX_SECRET = 128


def _secret_ok(code: object) -> bool:
    """Absent, ou un code de quatre à huit chiffres, ou un mot de passe possible.

    Un serveur qui n'envoie que des chiffres passe toujours ; un texte sans lettres ni
    chiffres, trop court ou trop long, rend la requête mal formée.
    """
    if code is None:
        return True
    if not isinstance(code, str) or not 0 < len(code) <= MAX_SECRET:
        return False
    if any(unicodedata.category(c).startswith("C") for c in code):
        return False
    return normalize_lock_code(code) is not None or normalize_passphrase(code) is not None


@dataclass(frozen=True)
class Request:
    """Une requête de la passerelle : liste, lecture d'états, ou commande."""

    id: str
    op: str
    entity_ids: tuple[str, ...] = ()
    entity_id: str = ""
    service: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    code: str | None = None


def parse_request(text: str) -> Request | None:
    """Une requête bien formée, ou `None` : tout le reste est ignoré."""
    try:
        message = json.loads(text)
    except (ValueError, RecursionError):
        return None
    if not isinstance(message, dict) or message.get("type") != "request":
        return None
    request_id = message.get("id")
    if not isinstance(request_id, str) or not 0 < len(request_id) <= 32:
        return None
    op = message.get("op")
    if op == "list":
        return Request(request_id, "list")
    if op == "read":
        ids = message.get("entity_ids")
        # Le secret du verrou, facultatif : seulement pour les entités sensibles. Code
        # chiffré ou mot de passe parlé (0.4.0) ; vérifié par le verrou, jamais ici.
        code = message.get("code")
        if (
            not isinstance(ids, list)
            or not 0 < len(ids) <= MAX_READ
            or not all(isinstance(i, str) and _ENTITY_ID.fullmatch(i) for i in ids)
            or not _secret_ok(code)
        ):
            return Request(request_id, "invalid")
        return Request(request_id, "read", tuple(ids), code=code)
    if op == "command":
        entity_id = message.get("entity_id")
        service = message.get("service")
        data = message.get("data", {})
        code = message.get("code")
        if (
            not isinstance(entity_id, str)
            or not _ENTITY_ID.fullmatch(entity_id)
            or not isinstance(service, str)
            or not _SERVICE.fullmatch(service)
            or not isinstance(data, dict)
            or len(data) > MAX_DATA_KEYS
            or not all(
                isinstance(k, str) and isinstance(v, (int, float, str)) and not isinstance(v, bool)
                for k, v in data.items()
            )
            or not _secret_ok(code)
        ):
            return Request(request_id, "invalid")
        return Request(request_id, "command", (), entity_id, service, dict(data), code)
    return Request(request_id, "invalid")


def ok(request_id: str, **payload: Any) -> str:
    return json.dumps({"type": "response", "id": request_id, "ok": True, **payload})


def error(request_id: str, reason: str) -> str:
    return json.dumps({"type": "response", "id": request_id, "ok": False, "error": reason})


# --- Ce que la maison montre -----------------------------------------------------------


def _text(value: Any, limit: int) -> str:
    return " ".join(str(value).split())[:limit]


def alias_texts(aliases: Iterable[Any]) -> list[str]:
    """Les alias écrits d'une entrée du registre, dans l'ordre choisi par l'utilisateur.

    Jusqu'à Home Assistant 2026.3, un ensemble de textes (rendu trié) ; depuis 2026.4, une
    liste ordonnée qui peut contenir une valeur spéciale, « le nom de l'entité »
    (`COMPUTED_NAME`) : ce n'est pas un texte, elle n'est jamais rendue comme tel.
    """
    texts = [alias for alias in aliases if isinstance(alias, str)]
    if isinstance(aliases, (set, frozenset)):
        texts.sort(key=str.casefold)
    return texts


def clean_aliases(
    aliases: Iterable[Any],
    name: str | None = None,
    *,
    count: int = MAX_ALIASES,
    length: int = MAX_ALIAS,
) -> list[str]:
    """Des alias nettoyés : une ligne chacun, sans doublon ni le nom lui-même, bornés."""
    seen = {_text(name, MAX_NAME).casefold()} if name else set()
    found: list[str] = []
    for alias in alias_texts(aliases):
        text = _text(alias, length)
        if not text or text.casefold() in seen:
            continue
        seen.add(text.casefold())
        found.append(text)
        if len(found) == count:
            break
    return found


def merge_aliases(old: Iterable[Any], wanted: list[str]) -> list[Any]:
    """Les alias à écrire : ceux voulus, et les valeurs spéciales de Home Assistant gardées.

    `wanted` est déjà nettoyé. Un alias gardé reste à sa place, avec l'orthographe voulue ; un
    alias nouveau vient à la fin ; une valeur spéciale (« le nom de l'entité ») reste où elle
    était.
    """
    spelling = {alias.casefold(): alias for alias in wanted}
    kept: list[Any] = []
    seen: set[str] = set()
    for alias in old:
        if not isinstance(alias, str):
            kept.append(alias)
            continue
        key = _text(alias, MAX_NAME).casefold()
        if key in spelling and key not in seen:
            seen.add(key)
            kept.append(spelling[key])
    return kept + [alias for alias in wanted if alias.casefold() not in seen]


def entity_payload(
    entity_id: str,
    name: str,
    area: str | None,
    device_class: str | None,
    mode: str = "read",
    aliases: Iterable[Any] = (),
    area_aliases: Iterable[Any] = (),
) -> dict[str, Any]:
    """Une entité partagée : nom, pièce, domaine, classe, alias. Jamais ses attributs.

    Les alias sont ceux d'Assist, de l'entité et de sa pièce : « le portillon » pour
    « Portail ». Un serveur plus ancien les ignore.
    """
    clean_name = _text(name, MAX_NAME) or entity_id
    clean_area = _text(area, MAX_NAME) if area else None
    return {
        "entity_id": entity_id,
        "name": clean_name,
        "area": clean_area,
        "domain": entity_id.split(".", 1)[0],
        "device_class": device_class if isinstance(device_class, str) and device_class else None,
        "mode": mode,
        "aliases": clean_aliases(aliases, clean_name),
        "area_aliases": clean_aliases(area_aliases, clean_area) if clean_area else [],
    }


def entities_reply(request_id: str, entities: list[dict[str, Any]]) -> str:
    """La liste des entités ; si elle dépasse la taille d'une trame, sans les alias.

    Le serveur ferme une liaison qui envoie une trame trop grande : mieux vaut une liste sans
    alias, ceux des pièces d'abord, qu'une maison muette.
    """
    text = ok(request_id, entities=entities)
    for keys in (("area_aliases",), ("area_aliases", "aliases")):
        if len(text.encode()) <= MAX_MESSAGE_BYTES:
            break
        entities = [{**entity, **{key: [] for key in keys}} for entity in entities]
        text = ok(request_id, entities=entities)
    return text


def pick_attributes(attributes: dict[str, Any]) -> dict[str, Any]:
    """Les seuls attributs de la liste, nombres ou textes courts."""
    picked: dict[str, Any] = {}
    for key in ATTRIBUTES:
        value = attributes.get(key)
        if isinstance(value, bool) or value is None:
            continue
        if isinstance(value, (int, float)):
            picked[key] = value
        elif isinstance(value, str):
            picked[key] = _text(value, MAX_TEXT_ATTRIBUTE)
    return picked


#: À la place de l'état d'une entité sensible : le code manque, est faux, le verrou est
#: bloqué, ou aucun code n'est réglé dans Home Assistant.
WITHHELD_REASONS = ("code_required", "code_invalid", "locked", "code_not_set")


def withheld_payload(entity_id: str, reason: str) -> dict[str, Any]:
    """Une entité sensible dont l'état n'est pas rendu, et pourquoi.

    Rendu à part (`withheld`), jamais dans `states` : un serveur plus ancien l'ignore.
    """
    return {"entity_id": entity_id, "reason": reason}


def state_payload(
    entity_id: str,
    state: str,
    unit: str | None,
    attributes: dict[str, Any],
    changed: str | None,
) -> dict[str, Any]:
    """L'état d'une entité, tel que la passerelle l'attend."""
    return {
        "entity_id": entity_id,
        "state": _text(state, MAX_STATE),
        "unit": _text(unit, MAX_UNIT) if isinstance(unit, str) and unit else None,
        "attributes": pick_attributes(attributes),
        "changed": changed,
    }
