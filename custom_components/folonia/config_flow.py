"""Appariement par le code de l'espace client ; choix de ce qu'Oscar peut lire et commander."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import aiohttp
import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    BooleanSelector,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from . import exposure
from .api import PairingFailed, PairingRateLimited, PairingRefused, async_pair
from .const import (
    CONF_CLEAR_CODE,
    CONF_CLEAR_PHRASE,
    CONF_CODE,
    CONF_CONTROL,
    CONF_EXEMPT,
    CONF_LINK_ID,
    CONF_LOCK_CODE,
    CONF_LOCK_HASH,
    CONF_LOCK_OPEN,
    CONF_LOCK_PHRASE,
    CONF_LOCK_READ,
    CONF_LOCK_SALT,
    CONF_PHRASE_HASH,
    CONF_PHRASE_SALT,
    CONF_READ,
    CONF_SECRET,
    CONF_URL,
    CONF_VERIFY_SSL,
    DEFAULT_LOCK_OPEN,
    DEFAULT_LOCK_READ,
    DEFAULT_URL,
    DOMAIN,
)
from .protocol import base_url, normalize_code
from .voicelock import hash_code, normalize_lock_code, normalize_passphrase

#: Les deux secrets du verrou : champ du formulaire, case qui l'efface, clés de l'empreinte,
#: normalisation, erreur si la saisie ne peut pas en être un.
SECRETS = (
    (
        CONF_LOCK_CODE,
        CONF_CLEAR_CODE,
        CONF_LOCK_HASH,
        CONF_LOCK_SALT,
        normalize_lock_code,
        "invalid_lock_code",
    ),
    (
        CONF_LOCK_PHRASE,
        CONF_CLEAR_PHRASE,
        CONF_PHRASE_HASH,
        CONF_PHRASE_SALT,
        normalize_passphrase,
        "invalid_lock_phrase",
    ),
)


class FoloniaConfigFlow(ConfigFlow, domain=DOMAIN):
    """Une maison, un code. Par défaut, Oscar ne voit rien."""

    VERSION = 1

    async def _pair(
        self, code_text: str, url_text: str, verify_ssl: bool
    ) -> tuple[dict[str, Any] | None, dict[str, str]]:
        base = base_url(url_text)
        if base is None:
            return None, {CONF_URL: "invalid_url"}
        code = normalize_code(code_text)
        if code is None:
            return None, {CONF_CODE: "invalid_code"}
        try:
            paired = await async_pair(self.hass, base, code, verify_ssl)
        except PairingRefused:
            return None, {CONF_CODE: "invalid_code"}
        except PairingRateLimited:
            return None, {"base": "rate_limited"}
        except (PairingFailed, aiohttp.ClientError, TimeoutError):
            return None, {"base": "cannot_connect"}
        return {
            CONF_URL: base,
            CONF_VERIFY_SSL: verify_ssl,
            CONF_LINK_ID: paired.link_id,
            CONF_SECRET: paired.secret,
        }, {}

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            data, errors = await self._pair(
                user_input[CONF_CODE],
                user_input.get(CONF_URL, DEFAULT_URL),
                user_input.get(CONF_VERIFY_SSL, True),
            )
            if data is not None:
                return self.async_create_entry(
                    title="Folonia",
                    data=data,
                    options={
                        CONF_READ: [],
                        CONF_CONTROL: [],
                        CONF_LOCK_OPEN: DEFAULT_LOCK_OPEN,
                        CONF_LOCK_READ: DEFAULT_LOCK_READ,
                        CONF_EXEMPT: [],
                    },
                )
        fields: dict[Any, Any] = {vol.Required(CONF_CODE): str}
        if self.show_advanced_options:
            fields[vol.Optional(CONF_URL, default=DEFAULT_URL)] = str
            fields[vol.Optional(CONF_VERIFY_SSL, default=True)] = bool
        return self.async_show_form(step_id="user", data_schema=vol.Schema(fields), errors=errors)

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        """Le service a délié cette maison : un nouveau code la relie de nouveau."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            data, errors = await self._pair(
                user_input[CONF_CODE],
                entry.data[CONF_URL],
                entry.data.get(CONF_VERIFY_SSL, True),
            )
            if data is not None:
                return self.async_update_reload_and_abort(entry, data_updates=data)
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_CODE): str}),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return FoloniaOptionsFlow()


class FoloniaOptionsFlow(OptionsFlow):
    """Une entité à la fois, parmi celles déjà exposées aux assistants vocaux.

    Deux listes : ce qu'Oscar peut lire, ce qu'il peut commander. Deux protections, cochées
    par défaut et décochables : le code pour ce qui ouvre la maison (`lock_open`), et pour
    lire un appareil sensible (`lock_read`) ; des appareils peuvent en être exemptés. Deux
    secrets, l'un ou l'autre suffit : un code chiffré, un mot de passe parlé. Un secret n'est
    exigé que si une protection cochée porte sur un appareil partagé et non exempté. Seules
    les empreintes sont gardées, et Folonia ne les reçoit jamais.
    """

    def _guarded(
        self,
        read: list[str],
        control: list[str],
        exempt: set[str],
        lock_open: bool,
        lock_read: bool,
    ) -> bool:
        """Une protection cochée porte sur au moins un appareil partagé et non exempté."""
        for entity_id in dict.fromkeys((*control, *read)):
            state = self.hass.states.get(entity_id)
            if state is None or entity_id in exempt:
                continue
            if lock_open and entity_id in control and exposure.opens_home(state):
                return True
            if lock_read and exposure.is_sensitive(state):
                return True
        return False

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        exposed = exposure.exposed_to_assist(self.hass)
        if not exposed:
            return self.async_abort(reason="nothing_exposed")
        controllable = set(exposure.controllable(self.hass))
        current = self.config_entry.options
        if user_input is not None:
            read = [e for e in user_input.get(CONF_READ, []) if e in exposed]
            control = [e for e in user_input.get(CONF_CONTROL, []) if e in controllable]
            shared = {*read, *control}
            lock_open = bool(user_input.get(CONF_LOCK_OPEN, DEFAULT_LOCK_OPEN))
            lock_read = bool(user_input.get(CONF_LOCK_READ, DEFAULT_LOCK_READ))
            # Une exemption ne vaut que pour un appareil partagé.
            exempt = [e for e in user_input.get(CONF_EXEMPT, []) if e in shared]
            options: dict[str, Any] = {
                CONF_READ: read,
                CONF_CONTROL: control,
                CONF_LOCK_OPEN: lock_open,
                CONF_LOCK_READ: lock_read,
                CONF_EXEMPT: exempt,
            }
            for field, clear, hash_key, salt_key, normalize, error in SECRETS:
                if current.get(hash_key) and not user_input.get(clear):
                    options[hash_key] = current[hash_key]
                    options[salt_key] = current[salt_key]
                text = user_input.get(field, "")
                if not text:
                    continue
                secret = normalize(text)
                if secret is None:
                    errors[field] = error
                else:
                    options[hash_key], options[salt_key] = hash_code(secret)
            # Un secret n'est exigé que s'il protège quelque chose ; sinon, rien n'est imposé.
            has_secret = bool(options.get(CONF_LOCK_HASH) or options.get(CONF_PHRASE_HASH))
            if (
                not errors
                and not has_secret
                and self._guarded(read, control, set(exempt), lock_open, lock_read)
            ):
                errors[CONF_LOCK_CODE] = "lock_code_required"
            if not errors:
                return self.async_create_entry(data=options)
        choices = sorted(
            (
                SelectOptionDict(value=entity_id, label=exposure.choice_label(self.hass, entity_id))
                for entity_id in exposed
            ),
            key=lambda choice: choice["label"].casefold(),
        )
        control_choices = [c for c in choices if c["value"] in controllable]
        # Exemptables : ce qui peut être sous code, sensible ou qui ouvre la maison.
        protectable = {
            entity_id
            for entity_id in exposed
            if (state := self.hass.states.get(entity_id)) is not None
            and (exposure.is_sensitive(state) or exposure.opens_home(state))
        }
        exempt_choices = [c for c in choices if c["value"] in protectable]
        read_now = [e for e in current.get(CONF_READ, []) if e in exposed]
        control_now = [e for e in current.get(CONF_CONTROL, []) if e in controllable]
        exempt_now = [e for e in exposure.exempt(current) if e in protectable]

        def entities(options: list[SelectOptionDict]) -> SelectSelector:
            return SelectSelector(
                SelectSelectorConfig(options=options, multiple=True, mode=SelectSelectorMode.LIST)
            )

        password = TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))
        schema = vol.Schema(
            {
                vol.Optional(CONF_READ, default=read_now): entities(choices),
                vol.Optional(CONF_CONTROL, default=control_now): entities(control_choices),
                vol.Optional(
                    CONF_LOCK_OPEN, default=exposure.lock_open(current)
                ): BooleanSelector(),
                vol.Optional(
                    CONF_LOCK_READ, default=exposure.lock_read(current)
                ): BooleanSelector(),
                vol.Optional(CONF_EXEMPT, default=sorted(exempt_now)): entities(exempt_choices),
                vol.Optional(CONF_LOCK_CODE, default=""): password,
                vol.Optional(CONF_CLEAR_CODE, default=False): BooleanSelector(),
                vol.Optional(CONF_LOCK_PHRASE, default=""): password,
                vol.Optional(CONF_CLEAR_PHRASE, default=False): BooleanSelector(),
            }
        )
        return self.async_show_form(
            step_id="init",
            data_schema=schema,
            errors=errors,
            description_placeholders={
                "lock_state": "réglé" if current.get(CONF_LOCK_HASH) else "aucun",
                "phrase_state": "réglé" if current.get(CONF_PHRASE_HASH) else "aucun",
            },
        )
