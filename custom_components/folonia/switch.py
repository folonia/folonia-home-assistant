"""L'interrupteur « Accès d'Oscar » : éteint, plus rien ne sort de la maison."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
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
    @property
    def is_on(self) -> bool:
        return self._link.enabled

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._link.async_set_enabled(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._link.async_set_enabled(False)
