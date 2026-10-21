"""Petits outils communs aux tests."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from custom_components.folonia.const import DOMAIN


def entity_id(hass: HomeAssistant, entry: ConfigEntry, platform: str, key: str) -> str:
    """L'identifiant d'une entité de l'intégration, quelle que soit la langue du banc."""
    found = er.async_get(hass).async_get_entity_id(platform, DOMAIN, f"{entry.entry_id}-{key}")
    assert found is not None, f"{platform} {key} absent"
    return found
