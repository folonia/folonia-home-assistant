"""La liaison sortante vers Folonia.

C'est la maison qui appelle : une connexion WebSocket ouverte vers le service, gardée
ouverte, rouverte avec un délai croissant si elle tombe. Aucun port n'est ouvert chez
l'utilisateur et le service ne reçoit aucun jeton de Home Assistant : seulement les
réponses à ses requêtes, calculées ici, à chaque fois, d'après ce que l'utilisateur a
choisi de montrer.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Callable, Mapping
from typing import Any

import aiohttp
from homeassistant.components import persistent_notification
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store

from . import exposure, protocol
from .const import (
    CONF_LOCK_HASH,
    CONF_LOCK_SALT,
    CONF_PHRASE_HASH,
    CONF_PHRASE_SALT,
    CONF_SECRET,
    CONF_URL,
    CONF_VERIFY_SSL,
    DOMAIN,
    SERVICE_DATA,
    SERVICE_TIMEOUT,
    SERVICES,
    VERSION,
)
from .journal import Journal
from .voicelock import VoiceLock

_LOGGER = logging.getLogger(__name__)

STORAGE_VERSION = 1

#: Le service répond au `hello` aussitôt ; au-delà, la liaison est refaite.
HELLO_TIMEOUT = 10
#: Le service envoie un ping toutes les 25 s ; celui-ci détecte un service disparu.
HEARTBEAT = 60
#: Une autre installation a pris la place : on n'insiste pas tout de suite.
REPLACED_DELAY = 60


def voice_lock(options: Mapping[str, Any]) -> VoiceLock:
    """Le verrou d'après les options : code chiffré et mot de passe, l'un ou l'autre."""
    return VoiceLock(
        options.get(CONF_LOCK_HASH),
        options.get(CONF_LOCK_SALT),
        options.get(CONF_PHRASE_HASH),
        options.get(CONF_PHRASE_SALT),
    )


def storage_key(entry_id: str) -> str:
    return f"{DOMAIN}.{entry_id}"


class FoloniaLink:
    """La liaison d'une installation, son interrupteur et son journal."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.journal = Journal(hass)
        #: Le verrou vocal, d'après les options ; rechargé quand elles changent (page Folonia).
        self.lock = voice_lock(entry.options)
        #: L'interrupteur « Accès d'Oscar ».
        self.enabled = True
        self.connected = False
        #: `unlinked` ou `protocol` : plus de reconnexion sans intervention.
        self.stopped_reason: str | None = None
        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, storage_key(entry.entry_id)
        )
        self._task: asyncio.Task[None] | None = None
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._listeners: list[Callable[[], None]] = []

    async def async_load(self) -> None:
        """L'état de l'interrupteur et les codes faux récents survivent aux redémarrages."""
        data = await self._store.async_load() or {}
        self.enabled = bool(data.get("enabled", True))
        failures = data.get("code_failures", [])
        if isinstance(failures, list):
            self.lock.failures.extend(float(t) for t in failures if isinstance(t, (int, float)))

    async def _save(self) -> None:
        await self._store.async_save(
            {"enabled": self.enabled, "code_failures": list(self.lock.failures)}
        )

    @callback
    def async_options_updated(self) -> None:
        """Nouvelles options : le verrou suit, et un secret changé (ou effacé) le débloque."""
        new = voice_lock(self.entry.options)
        if new.fingerprint == self.lock.fingerprint:
            new.failures.extend(self.lock.failures)
        else:
            self.journal.record("code ou mot de passe du verrou vocal modifié")
        self.lock = new

    @callback
    def async_add_listener(self, listener: Callable[[], None]) -> Callable[[], None]:
        self._listeners.append(listener)

        @callback
        def remove() -> None:
            self._listeners.remove(listener)

        return remove

    @callback
    def _notify(self) -> None:
        for listener in list(self._listeners):
            listener()

    @callback
    def _set_connected(self, connected: bool) -> None:
        if connected != self.connected:
            self.connected = connected
            self._notify()

    @callback
    def async_start(self) -> None:
        if self._task is None and self.enabled and self.stopped_reason is None:
            self._task = self.entry.async_create_background_task(
                self.hass, self._run(), f"{DOMAIN} liaison"
            )

    async def async_stop(self) -> None:
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        self._ws = None
        self._set_connected(False)

    async def async_set_enabled(self, enabled: bool) -> None:
        """Couper tout, ou rouvrir. Coupé : le service est prévenu, puis la liaison est fermée."""
        if enabled == self.enabled:
            return
        self.enabled = enabled
        if enabled:
            # Rallumer l'accès débloque aussi le verrou vocal.
            self.lock.reset()
            await self._save()
            self.journal.record("accès rouvert depuis Home Assistant")
            self.async_start()
        else:
            ws = self._ws
            if ws is not None and not ws.closed:
                with contextlib.suppress(aiohttp.ClientError, ConnectionError, RuntimeError):
                    await ws.send_str(protocol.bye("paused"))
                    await ws.close()
            await self.async_stop()
            self.journal.record("accès coupé depuis Home Assistant")
        self._notify()

    async def _run(self) -> None:
        attempt = 0
        while True:
            connected, outcome = False, "lost"
            try:
                connected, outcome = await self._session()
            except aiohttp.WSServerHandshakeError as err:
                outcome = "unlinked" if err.status == 401 else "lost"
            except (aiohttp.ClientError, TimeoutError, OSError) as err:
                _LOGGER.debug("Folonia injoignable : %s", err)
            if outcome in ("unlinked", "protocol"):
                self._halt(outcome)
                return
            attempt = 1 if connected else attempt + 1
            delay = protocol.backoff(attempt)
            if outcome == "replaced":
                delay = max(delay, REPLACED_DELAY)
            await asyncio.sleep(delay)

    @callback
    def _halt(self, reason: str) -> None:
        """Le service a délié cette maison, ou ne parle plus ce protocole : on s'arrête."""
        self.stopped_reason = reason
        self._task = None
        self._set_connected(False)
        if reason == "unlinked":
            self.journal.record(
                "liaison déliée par Folonia : un nouveau code est nécessaire", refused=True
            )
            self.entry.async_start_reauth(self.hass)
        else:
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                "protocol",
                is_fixable=False,
                severity=ir.IssueSeverity.ERROR,
                translation_key="protocol",
            )
        self._notify()

    async def _session(self) -> tuple[bool, str]:
        """Une liaison, de l'ouverture à la fermeture. Rend (a été établie, issue)."""
        data = self.entry.data
        session = async_get_clientsession(self.hass, verify_ssl=data.get(CONF_VERIFY_SSL, True))
        async with session.ws_connect(
            protocol.link_url(data[CONF_URL]),
            headers={"Authorization": f"Bearer {data[CONF_SECRET]}"},
            heartbeat=HEARTBEAT,
            max_msg_size=protocol.MAX_MESSAGE_BYTES,
        ) as ws:
            self._ws = ws
            try:
                await ws.send_str(protocol.hello(VERSION))
                first = await ws.receive(timeout=HELLO_TIMEOUT)
                if first.type != aiohttp.WSMsgType.TEXT or not protocol.is_welcome(first.data):
                    await ws.close()
                    return False, protocol.outcome_of_close(ws.close_code)
                self._set_connected(True)
                async for message in ws:
                    if message.type != aiohttp.WSMsgType.TEXT:
                        continue
                    reply = await self._answer(message.data)
                    if reply is not None:
                        await ws.send_str(reply)
                return True, protocol.outcome_of_close(ws.close_code)
            finally:
                self._ws = None
                self._set_connected(False)

    async def _answer(self, text: str) -> str | None:
        """La réponse à une requête : la règle est appliquée ici, à chaque requête."""
        request = protocol.parse_request(text)
        if request is None:
            return None
        if not self.enabled:
            return protocol.error(request.id, "paused")
        if request.op == "invalid":
            return protocol.error(request.id, "bad_request")
        if request.op == "command":
            try:
                return await self._command(request)
            except Exception:
                _LOGGER.exception("commande Folonia non traitée")
                return protocol.error(request.id, "internal")
        try:
            visible = exposure.allowed(self.hass, self.entry.options)
            if request.op == "list":
                control = set(exposure.allowed_control(self.hass, self.entry.options))
                entities = [
                    entity
                    for entity in (
                        exposure.describe(self.hass, eid, "control" if eid in control else "read")
                        for eid in visible
                    )
                    if entity is not None
                ]
                self.journal.record(f"a consulté la liste des appareils partagés ({len(entities)})")
                return protocol.ok(request.id, entities=entities)
            return await self._read(request, set(visible))
        except Exception:
            _LOGGER.exception("requête Folonia non traitée")
            return protocol.error(request.id, "internal")

    async def _read(self, request: protocol.Request, shown: set[str]) -> str:
        """Les états demandés ; ceux des entités sensibles, avec le bon code seulement.

        Le code n'est vérifié (et un code faux compté) que si la demande porte sur au moins
        une entité sensible : une question sur la cuisine ne réclame rien.
        """
        found = [
            state
            for entity_id in request.entity_ids
            if entity_id in shown and (state := self.hass.states.get(entity_id)) is not None
        ]
        options = self.entry.options
        sensitive = [s.entity_id for s in found if exposure.read_guarded(s, options)]
        verdict = "ok"
        if sensitive:
            verdict = await self._verify(request.code, sensitive[0])
            if verdict == "forbidden":
                verdict = "code_not_set"
        states = []
        withheld = []
        for state in found:
            if state.entity_id in sensitive and verdict != "ok":
                withheld.append(protocol.withheld_payload(state.entity_id, verdict))
                if verdict in ("code_required", "code_not_set"):
                    self.journal.record("lecture sous code vocal : code demandé", state.entity_id)
                continue
            states.append(exposure.snapshot(state))
            self.journal.record(f"a lu l'état : {state.state}", state.entity_id)
        if withheld:
            return protocol.ok(request.id, states=states, withheld=withheld)
        return protocol.ok(request.id, states=states)

    async def _verify(self, code: str | None, entity_id: str) -> str:
        """Le verrou vocal, pour une commande ou une lecture : les essais faux comptent pareil,
        code ou mot de passe, dit ou tapé."""
        verdict = self.lock.check(code)
        if verdict in ("code_invalid", "locked") and code:
            await self._save()
            self.journal.record("code du verrou vocal refusé", entity_id, refused=True)
        if verdict == "locked" and code:
            await self._notify_locked()
        return verdict

    async def _command(self, request: protocol.Request) -> str:
        """Une commande : entité cochée en commande, service permis, verrou si elle ouvre."""
        entity_id = request.entity_id
        if entity_id not in exposure.allowed_control(self.hass, self.entry.options):
            self.journal.record(
                "a tenté une commande sur un appareil non commandable", entity_id, refused=True
            )
            return protocol.error(request.id, "forbidden")
        state = self.hass.states.get(entity_id)
        domain, service = request.service.split(".", 1)
        if state is None or domain != state.domain or service not in SERVICES.get(domain, ()):
            return protocol.error(request.id, "forbidden")
        data: dict[str, Any] = {"entity_id": entity_id}
        allowed_key = SERVICE_DATA.get(request.service)
        for key, value in request.data.items():
            if allowed_key is None or key != allowed_key[0] or not isinstance(value, (int, float)):
                return protocol.error(request.id, "bad_request")
            if not allowed_key[1] <= value <= allowed_key[2]:
                return protocol.error(request.id, "bad_request")
            data[key] = value
        options = self.entry.options
        coded = exposure.command_guarded(state, request.service, data, options)
        if coded:
            verdict = await self._verify(request.code, entity_id)
            if verdict != "ok":
                return protocol.error(request.id, verdict)
        try:
            async with asyncio.timeout(SERVICE_TIMEOUT):
                await self.hass.services.async_call(domain, service, data, blocking=True)
        except Exception as err:  # tout refus de Home Assistant est un échec, dit à Oscar
            _LOGGER.warning("commande Folonia refusée par Home Assistant : %s", err)
            self.journal.record(f"commande refusée : {service}", entity_id, refused=True)
            return protocol.error(request.id, "failed")
        after = self.hass.states.get(entity_id)
        self.journal.record(
            f"a commandé : {service} → {after.state if after else 'inconnu'}", entity_id
        )
        # L'état d'une entité sensible ne sort qu'avec le bon code, après une commande aussi.
        hidden = not coded and exposure.read_guarded(state, options)
        if after is None or hidden:
            return protocol.ok(request.id)
        return protocol.ok(request.id, result=exposure.snapshot(after))

    async def _notify_locked(self) -> None:
        """Verrou bloqué : l'utilisateur en est averti dans Home Assistant."""
        self.journal.record(
            "verrou vocal bloqué après cinq codes faux en vingt-quatre heures", refused=True
        )
        try:
            persistent_notification.async_create(
                self.hass,
                (
                    "Cinq codes ou mots de passe faux ont été donnés au téléphone en "
                    "vingt-quatre heures. Oscar ne fait plus rien de ce qui est sous code : ni "
                    "déverrouiller, ni désarmer, ni ouvrir le portail ou la porte de garage, ni "
                    "dire l'état des appareils sensibles. Pour débloquer : éteignez puis "
                    "rallumez « Accès d'Oscar », ou enregistrez un nouveau code ou mot de passe "
                    "dans la page Folonia de la barre latérale (Code et protections)."
                ),
                title="Folonia : verrou vocal bloqué",
                notification_id=f"{DOMAIN}_lock",
            )
        except Exception:
            _LOGGER.exception("notification du verrou non créée")
