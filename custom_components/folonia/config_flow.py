"""Appariement par le code de l'espace client ; choix de ce qu'Oscar peut lire et commander."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

import aiohttp
import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    BooleanSelector,
    EntitySelector,
    EntitySelectorConfig,
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

#: Les quatre parties des options, chacune enregistrée seule.
MENU = ("read", "control", "exempt", "protections")
#: Au-delà, la liste des appareils sous protection, dans la description d'une étape, est abrégée.
LISTED = 20
#: Dans le résumé du menu : un secret réglé, ou aucun.
SET, UNSET = "✓", "—"


def _entities(include: list[str]) -> EntitySelector:
    """Le sélecteur natif, avec recherche, limité à la liste permise.

    Le formulaire ne fait pas foi : ce qu'il renvoie est recoupé avec la liste permise à
    l'enregistrement (un identifiant de registre, par exemple, passerait le sélecteur).
    """
    return EntitySelector(EntitySelectorConfig(multiple=True, include_entities=include))


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
    """Un menu en quatre parties, chacune enregistrée seule ; les autres réglages sont gardés.

    Ce qu'Oscar peut lire, ce qu'il peut commander : une entité à la fois, parmi celles déjà
    exposées aux assistants vocaux. Deux protections, cochées par défaut et décochables : le
    code pour ce qui ouvre la maison (`lock_open`), et pour lire un appareil sensible
    (`lock_read`) ; des appareils partagés peuvent en être exemptés. Deux secrets, l'un ou
    l'autre suffit : un code chiffré, un mot de passe parlé. Un secret n'est exigé que si une
    protection cochée porte sur un appareil partagé et non exempté. Seules les empreintes sont
    gardées, et Folonia ne les reçoit jamais.

    Une liste qui rend un secret nécessaire, faute d'en avoir un, est enregistrée quand même,
    et mène à « Code et protections » : d'ici là, Oscar refuse ce qui demande un code. Cette
    étape-là, comme avant, n'enregistre rien qui laisserait une protection cochée sans secret.
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

    @callback
    def _protectable(self, entity_ids: Iterable[str]) -> list[str]:
        """Ce qui peut être sous code : sensible, ou qui ouvre la maison."""
        return [
            entity_id
            for entity_id in entity_ids
            if (state := self.hass.states.get(entity_id)) is not None
            and (exposure.is_sensitive(state) or exposure.opens_home(state))
        ]

    @callback
    def _shared(self, options: Mapping[str, Any]) -> tuple[list[str], list[str], list[str]]:
        """Lu, commandé, sans code : les listes enregistrées, réduites à ce qui est permis.

        Une entité qui a perdu son exposition aux assistants vocaux en disparaît.
        """
        exposed = set(exposure.exposed_to_assist(self.hass))
        controllable = set(exposure.controllable(self.hass))
        read = [e for e in options.get(CONF_READ, []) if e in exposed]
        control = [e for e in options.get(CONF_CONTROL, []) if e in controllable]
        protectable = set(self._protectable({*read, *control}))
        exempt = [e for e in options.get(CONF_EXEMPT, []) if e in protectable]
        return read, control, exempt

    @callback
    def _needs_secret(self, options: Mapping[str, Any]) -> bool:
        """Les règles de 0.4.0 : un secret n'est exigé que s'il protège quelque chose."""
        if options.get(CONF_LOCK_HASH) or options.get(CONF_PHRASE_HASH):
            return False
        read, control, exempt = self._shared(options)
        return self._guarded(
            read, control, set(exempt), exposure.lock_open(options), exposure.lock_read(options)
        )

    @callback
    def _listed(self, entity_ids: Iterable[str]) -> str:
        """Les appareils sous protection, nature et valeur du moment, pour la description."""
        labels = sorted(
            (exposure.choice_label(self.hass, entity_id) for entity_id in entity_ids),
            key=str.casefold,
        )
        if not labels:
            return UNSET
        lines = [f"- {label}" for label in labels[:LISTED]]
        if len(labels) > LISTED:
            lines.append(f"- … (+{len(labels) - LISTED})")
        return "\n".join(lines)

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if not exposure.exposed_to_assist(self.hass):
            return self.async_abort(reason="nothing_exposed")
        current = self.config_entry.options
        read, control, exempt = self._shared(current)
        return self.async_show_menu(
            step_id="init",
            menu_options=list(MENU),
            description_placeholders={
                "read": str(len(read)),
                "control": str(len(control)),
                "exempt": str(len(exempt)),
                "lock_state": SET if current.get(CONF_LOCK_HASH) else UNSET,
                "phrase_state": SET if current.get(CONF_PHRASE_HASH) else UNSET,
            },
        )

    async def _save_list(self, key: str, chosen: list[str]) -> ConfigFlowResult:
        """Une liste enregistrée, les autres réglages gardés ; vers le secret s'il en faut un."""
        options = {**self.config_entry.options, key: list(dict.fromkeys(chosen))}
        # Une exemption ne vaut que pour un appareil partagé : un appareil retiré la perd, et
        # ne reviendrait pas sans code s'il était partagé de nouveau.
        shared = {*options.get(CONF_READ, []), *options.get(CONF_CONTROL, [])}
        options[CONF_EXEMPT] = [e for e in options.get(CONF_EXEMPT, []) if e in shared]
        if not self._needs_secret(options):
            return self.async_create_entry(data=options)
        # La liste n'est pas perdue : enregistrée tout de suite (Oscar refuse alors ce qui
        # demande un code, faute de secret), puis le secret ou la protection à régler.
        self.hass.config_entries.async_update_entry(self.config_entry, options=options)
        return self._protections_form({"base": "secret_needed"})

    async def async_step_read(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        exposed = exposure.exposed_to_assist(self.hass)
        if user_input is not None:
            permitted = set(exposed)
            return await self._save_list(
                CONF_READ, [e for e in user_input.get(CONF_READ, []) if e in permitted]
            )
        if not exposed:
            return self.async_abort(reason="nothing_exposed")
        read, _, _ = self._shared(self.config_entry.options)
        sensitive = [
            entity_id
            for entity_id in exposed
            if (state := self.hass.states.get(entity_id)) is not None
            and exposure.is_sensitive(state)
        ]
        return self.async_show_form(
            step_id="read",
            data_schema=vol.Schema({vol.Optional(CONF_READ, default=read): _entities(exposed)}),
            description_placeholders={"sensitive": self._listed(sensitive)},
        )

    async def async_step_control(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        controllable = exposure.controllable(self.hass)
        if user_input is not None:
            permitted = set(controllable)
            return await self._save_list(
                CONF_CONTROL, [e for e in user_input.get(CONF_CONTROL, []) if e in permitted]
            )
        if not controllable:
            return self.async_abort(reason="nothing_controllable")
        _, control, _ = self._shared(self.config_entry.options)
        opens = [
            entity_id
            for entity_id in controllable
            if (state := self.hass.states.get(entity_id)) is not None and exposure.opens_home(state)
        ]
        return self.async_show_form(
            step_id="control",
            data_schema=vol.Schema(
                {vol.Optional(CONF_CONTROL, default=control): _entities(controllable)}
            ),
            description_placeholders={"opens": self._listed(opens)},
        )

    async def async_step_exempt(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        # Exemptables : les appareils partagés qui peuvent être sous code.
        read, control, exempt = self._shared(self.config_entry.options)
        protectable = sorted(self._protectable({*read, *control}))
        if user_input is not None:
            permitted = set(protectable)
            return await self._save_list(
                CONF_EXEMPT, [e for e in user_input.get(CONF_EXEMPT, []) if e in permitted]
            )
        if not protectable:
            return self.async_abort(reason="nothing_to_exempt")
        return self.async_show_form(
            step_id="exempt",
            data_schema=vol.Schema(
                {vol.Optional(CONF_EXEMPT, default=sorted(exempt)): _entities(protectable)}
            ),
        )

    async def async_step_protections(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        current = self.config_entry.options
        if user_input is not None:
            options: dict[str, Any] = {
                **current,
                CONF_LOCK_OPEN: bool(user_input.get(CONF_LOCK_OPEN, DEFAULT_LOCK_OPEN)),
                CONF_LOCK_READ: bool(user_input.get(CONF_LOCK_READ, DEFAULT_LOCK_READ)),
            }
            for field, clear, hash_key, salt_key, normalize, error in SECRETS:
                if user_input.get(clear):
                    options.pop(hash_key, None)
                    options.pop(salt_key, None)
                text = user_input.get(field, "")
                if not text:
                    continue
                secret = normalize(text)
                if secret is None:
                    errors[field] = error
                else:
                    options[hash_key], options[salt_key] = hash_code(secret)
            # Un secret n'est exigé que s'il protège quelque chose ; sinon, rien n'est imposé.
            if not errors and self._needs_secret(options):
                errors[CONF_LOCK_CODE] = "lock_code_required"
            if not errors:
                return self.async_create_entry(data=options)
        return self._protections_form(errors)

    @callback
    def _protections_form(self, errors: dict[str, str]) -> ConfigFlowResult:
        current = self.config_entry.options
        password = TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))
        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_LOCK_OPEN, default=exposure.lock_open(current)
                ): BooleanSelector(),
                vol.Optional(
                    CONF_LOCK_READ, default=exposure.lock_read(current)
                ): BooleanSelector(),
                vol.Optional(CONF_LOCK_CODE, default=""): password,
                vol.Optional(CONF_CLEAR_CODE, default=False): BooleanSelector(),
                vol.Optional(CONF_LOCK_PHRASE, default=""): password,
                vol.Optional(CONF_CLEAR_PHRASE, default=False): BooleanSelector(),
            }
        )
        return self.async_show_form(
            step_id="protections",
            data_schema=schema,
            errors=errors,
            description_placeholders={
                "lock_state": SET if current.get(CONF_LOCK_HASH) else UNSET,
                "phrase_state": SET if current.get(CONF_PHRASE_HASH) else UNSET,
            },
        )
