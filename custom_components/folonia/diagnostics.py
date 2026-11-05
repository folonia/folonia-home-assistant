"""Diagnostic : état de la liaison et dernières lignes du journal, secrets masqués."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from . import FoloniaConfigEntry
from .const import (
    CONF_CONTROL,
    CONF_EXEMPT,
    CONF_LINK_ID,
    CONF_LOCK_OPEN,
    CONF_LOCK_READ,
    CONF_READ,
    CONF_SECRET,
)


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: FoloniaConfigEntry
) -> dict[str, Any]:
    link = entry.runtime_data
    return {
        "data": async_redact_data(dict(entry.data), {CONF_SECRET, CONF_LINK_ID}),
        # Des totaux : ce fichier finit parfois joint à une demande publique.
        "shared": {
            key: len(entry.options.get(key, ())) for key in (CONF_READ, CONF_CONTROL, CONF_EXEMPT)
        },
        "protections": {key: entry.options.get(key) for key in (CONF_LOCK_OPEN, CONF_LOCK_READ)},
        "lock_code_configured": link.lock.code_configured,
        "lock_phrase_configured": link.lock.phrase_configured,
        "lock_failures": len(link.lock.failures),
        "enabled": link.enabled,
        "connected": link.connected,
        "stopped_reason": link.stopped_reason,
        "journal": [
            {key: line[key] for key in ("time", "refused")} for line in link.journal.entries
        ],
    }
