"""Appariement par le code de l'espace client ; les réglages sont dans la page Folonia."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import aiohttp
import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback

from .api import PairingFailed, PairingRateLimited, PairingRefused, async_pair
from .const import (
    CONF_CODE,
    CONF_CONTROL,
    CONF_EXEMPT,
    CONF_LINK_ID,
    CONF_LOCK_OPEN,
    CONF_LOCK_READ,
    CONF_READ,
    CONF_SECRET,
    CONF_URL,
    CONF_VERIFY_SSL,
    DEFAULT_LOCK_OPEN,
    DEFAULT_LOCK_READ,
    DEFAULT_URL,
    DOMAIN,
    PANEL_URL,
)
from .protocol import base_url, normalize_code

#: La page Folonia, où sont les réglages.
PANEL_PATH = f"/{PANEL_URL}"


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
    """Les réglages sont dans la page Folonia de la barre latérale : le formulaire y renvoie.

    « Configurer » mène d'ordinaire droit à la page, déclarée page de configuration de
    l'intégration ; ce formulaire ne sert que si Home Assistant l'ouvre par un autre chemin.
    """

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return self.async_abort(reason="use_panel", description_placeholders={"url": PANEL_PATH})
