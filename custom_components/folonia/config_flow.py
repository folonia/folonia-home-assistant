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
    CONF_CODE,
    CONF_CONTROL,
    CONF_LINK_ID,
    CONF_LOCK_CODE,
    CONF_LOCK_HASH,
    CONF_LOCK_READ,
    CONF_LOCK_SALT,
    CONF_READ,
    CONF_SECRET,
    CONF_URL,
    CONF_VERIFY_SSL,
    DEFAULT_LOCK_READ,
    DEFAULT_URL,
    DOMAIN,
)
from .protocol import base_url, normalize_code
from .voicelock import hash_code, normalize_lock_code


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
                    options={CONF_READ: [], CONF_CONTROL: [], CONF_LOCK_READ: DEFAULT_LOCK_READ},
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

    Deux listes : ce qu'Oscar peut lire, ce qu'il peut commander. Un code du
    verrou vocal est exigé dès que ce qui ouvre la maison est coché en commande, et, la
    case « lock_read » cochée (par défaut), dès qu'un appareil sensible est partagé ; seule
    son empreinte est gardée, et Folonia ne la reçoit jamais.
    """

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
            lock_read = bool(user_input.get(CONF_LOCK_READ, DEFAULT_LOCK_READ))
            options: dict[str, Any] = {
                CONF_READ: read,
                CONF_CONTROL: control,
                CONF_LOCK_READ: lock_read,
            }
            code_text = user_input.get(CONF_LOCK_CODE, "")
            if current.get(CONF_LOCK_HASH):
                options[CONF_LOCK_HASH] = current[CONF_LOCK_HASH]
                options[CONF_LOCK_SALT] = current[CONF_LOCK_SALT]
            if code_text:
                code = normalize_lock_code(code_text)
                if code is None:
                    errors[CONF_LOCK_CODE] = "invalid_lock_code"
                else:
                    options[CONF_LOCK_HASH], options[CONF_LOCK_SALT] = hash_code(code)
            # Le code est exigé pour ce qui ouvre la maison, coché en commande, et, la case
            # cochée, pour tout appareil sensible partagé (les commandés se lisent aussi).
            locked = [
                e
                for e in control
                if (state := self.hass.states.get(e)) is not None and exposure.opens_home(state)
            ]
            if lock_read:
                locked += [
                    e
                    for e in (*read, *control)
                    if (state := self.hass.states.get(e)) is not None
                    and exposure.is_sensitive(state)
                ]
            if locked and not options.get(CONF_LOCK_HASH) and CONF_LOCK_CODE not in errors:
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
        read_now = [e for e in current.get(CONF_READ, []) if e in exposed]
        control_now = [e for e in current.get(CONF_CONTROL, []) if e in controllable]
        schema = vol.Schema(
            {
                vol.Optional(CONF_READ, default=read_now): SelectSelector(
                    SelectSelectorConfig(
                        options=choices, multiple=True, mode=SelectSelectorMode.LIST
                    )
                ),
                vol.Optional(CONF_CONTROL, default=control_now): SelectSelector(
                    SelectSelectorConfig(
                        options=control_choices, multiple=True, mode=SelectSelectorMode.LIST
                    )
                ),
                vol.Optional(CONF_LOCK_CODE, default=""): TextSelector(
                    TextSelectorConfig(type=TextSelectorType.PASSWORD)
                ),
                vol.Optional(
                    CONF_LOCK_READ, default=bool(current.get(CONF_LOCK_READ, DEFAULT_LOCK_READ))
                ): BooleanSelector(),
            }
        )
        return self.async_show_form(
            step_id="init",
            data_schema=schema,
            errors=errors,
            description_placeholders={
                "lock_state": "réglé" if current.get(CONF_LOCK_HASH) else "aucun"
            },
        )
