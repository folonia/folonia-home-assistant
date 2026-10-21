"""Protocole de la liaison Folonia (protocole 1).

Ce module ne dépend pas de Home Assistant : il décrit ce qui circule sur la liaison
et se teste seul.
"""

from __future__ import annotations

import json
import random
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit, urlunsplit

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


def base_url(text: str) -> str | None:
    """Adresse du service, sans chemin final : `https://folonia.fr`. `None` si invalide."""
    parts = urlsplit(text.strip())
    if parts.scheme not in ("https", "http") or not parts.netloc:
        return None
    if parts.query or parts.fragment:
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
    ceiling = min(300.0, float(2 ** max(0, attempt - 1)))
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


def bye(reason: str) -> str:
    return json.dumps({"type": "bye", "reason": reason})


def is_welcome(text: str) -> bool:
    try:
        message = json.loads(text)
    except ValueError:
        return False
    return (
        isinstance(message, dict)
        and message.get("type") == "welcome"
        and message.get("protocol") == PROTOCOL
    )


_SERVICE = re.compile(r"^[a-z_]+\.[a-z_]+$")
_LOCK_CODE = re.compile(r"^[0-9]{4,8}$")
#: Données d'un service, au plus.
MAX_DATA_KEYS = 4


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
    except ValueError:
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
        # Le code vocal, facultatif (21 octobre 2026) : seulement pour les entités sensibles.
        code = message.get("code")
        if (
            not isinstance(ids, list)
            or not 0 < len(ids) <= MAX_READ
            or not all(isinstance(i, str) and 0 < len(i) <= 255 for i in ids)
            or (code is not None and not (isinstance(code, str) and _LOCK_CODE.match(code)))
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
            or not 0 < len(entity_id) <= 255
            or not isinstance(service, str)
            or not _SERVICE.match(service)
            or not isinstance(data, dict)
            or len(data) > MAX_DATA_KEYS
            or not all(
                isinstance(k, str) and isinstance(v, (int, float, str)) and not isinstance(v, bool)
                for k, v in data.items()
            )
            or (code is not None and not (isinstance(code, str) and _LOCK_CODE.match(code)))
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


def entity_payload(
    entity_id: str,
    name: str,
    area: str | None,
    device_class: str | None,
    mode: str = "read",
) -> dict[str, Any]:
    """Une entité partagée : nom, pièce, domaine, classe. Jamais ses attributs."""
    return {
        "entity_id": entity_id,
        "name": _text(name, MAX_NAME) or entity_id,
        "area": _text(area, MAX_NAME) if area else None,
        "domain": entity_id.split(".", 1)[0],
        "device_class": device_class if isinstance(device_class, str) and device_class else None,
        "mode": mode,
    }


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
