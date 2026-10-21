"""Appels HTTP au service Folonia : l'appariement, et le déliement."""

from __future__ import annotations

import re
from dataclasses import dataclass

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import VERSION
from .protocol import pair_url

_SECRET = re.compile(r"^fol_[A-Za-z0-9_-]{43}$")
_TIMEOUT = aiohttp.ClientTimeout(total=15)


class PairingRefused(Exception):
    """Code inconnu, expiré ou déjà servi."""


class PairingRateLimited(Exception):
    """Trop d'essais depuis cette adresse."""


class PairingFailed(Exception):
    """Le service n'a pas répondu comme prévu."""


@dataclass(frozen=True)
class Paired:
    link_id: str
    secret: str


async def async_pair(hass: HomeAssistant, base: str, code: str, verify_ssl: bool) -> Paired:
    """Échange le code de l'espace client contre le secret de liaison, rendu une seule fois."""
    session = async_get_clientsession(hass, verify_ssl=verify_ssl)
    async with session.post(
        pair_url(base), json={"code": code, "component": VERSION}, timeout=_TIMEOUT
    ) as response:
        if response.status == 429:
            raise PairingRateLimited
        if response.status in (400, 404, 410, 422):
            raise PairingRefused
        if response.status != 201:
            raise PairingFailed(response.status)
        body = await response.json(content_type=None)
    link_id = body.get("link_id") if isinstance(body, dict) else None
    secret = body.get("link_secret") if isinstance(body, dict) else None
    if not isinstance(link_id, str) or not isinstance(secret, str) or not _SECRET.match(secret):
        raise PairingFailed("réponse inattendue")
    return Paired(link_id, secret)


async def async_unlink(hass: HomeAssistant, base: str, secret: str, verify_ssl: bool) -> bool:
    """Délie la maison chez Folonia. Au mieux : une erreur réseau n'empêche rien localement."""
    session = async_get_clientsession(hass, verify_ssl=verify_ssl)
    try:
        async with session.delete(
            f"{base}/v1/home/link",
            headers={"Authorization": f"Bearer {secret}"},
            timeout=_TIMEOUT,
        ) as response:
            return response.status in (204, 401)
    except (aiohttp.ClientError, TimeoutError):
        return False
