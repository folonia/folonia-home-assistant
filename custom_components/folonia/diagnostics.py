"""Diagnostic : état de la liaison et dernières lignes du journal, secrets masqués."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from . import FoloniaConfigEntry
from .const import (
    CONF_LOCK_HASH,
    CONF_LOCK_SALT,
    CONF_PHRASE_HASH,
    CONF_PHRASE_SALT,
    CONF_SECRET,
)


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: FoloniaConfigEntry
) -> dict[str, Any]:
    link = entry.runtime_data
    return {
        "data": async_redact_data(dict(entry.data), {CONF_SECRET}),
        "options": async_redact_data(
            dict(entry.options),
            {CONF_LOCK_HASH, CONF_LOCK_SALT, CONF_PHRASE_HASH, CONF_PHRASE_SALT},
        ),
        "lock_code_configured": link.lock.code_configured,
        "lock_phrase_configured": link.lock.phrase_configured,
        "lock_failures": len(link.lock.failures),
        "enabled": link.enabled,
        "connected": link.connected,
        "stopped_reason": link.stopped_reason,
        "journal": list(link.journal.entries),
    }
