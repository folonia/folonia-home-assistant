"""L'interrupteur « Accès d'Oscar » : éteint, plus rien ne sort de la maison."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import Unauthorized
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import FoloniaConfigEntry
from .entity import FoloniaEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: FoloniaConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([AccessSwitch(entry.runtime_data, "access")])


class AccessSwitch(FoloniaEntity, SwitchEntity):
    # Pas exposé d'office aux assistants vocaux, comme la page réservé aux administrateurs : le
    # rallumer rouvre l'accès et débloque le verrou.
    _attr_entity_category = EntityCategory.CONFIG

    @property
    def is_on(self) -> bool:
        return self._link.enabled

    async def _require_admin(self) -> None:
        user_id = self._context.user_id if self._context else None
        if user_id is None:
            return
        user = await self.hass.auth.async_get_user(user_id)
        if user is not None and not user.is_admin:
            raise Unauthorized

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._require_admin()
        await self._link.async_set_enabled(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        # Couper reste ouvert à tous : dans le doute, n'importe quel habitant peut fermer.
        await self._link.async_set_enabled(False)
