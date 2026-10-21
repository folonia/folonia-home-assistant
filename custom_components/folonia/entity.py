"""Ce que les entités de l'intégration partagent : l'appareil « Folonia » et la liaison."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity import Entity

from .const import DOMAIN, VERSION
from .link import FoloniaLink


class FoloniaEntity(Entity):
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, link: FoloniaLink, key: str) -> None:
        self._link = link
        self._attr_translation_key = key
        self._attr_unique_id = f"{link.entry.entry_id}-{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, link.entry.entry_id)},
            name="Folonia",
            manufacturer="DEVGO",
            model="Liaison avec Oscar",
            entry_type=DeviceEntryType.SERVICE,
            sw_version=VERSION,
        )

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self._link.async_add_listener(self.async_write_ha_state))
