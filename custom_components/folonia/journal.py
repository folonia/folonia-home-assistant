"""Journal local de tout ce qu'Oscar a lu (et fait).

Chaque lecture devient une ligne du journal de bord de Home Assistant, rattachée à
l'entité, avec la valeur lue. Rien ne remonte chez Folonia : le journal reste dans la
maison, sous le contrôle de l'utilisateur. Les dernières lignes sont aussi gardées en
mémoire, pour la page Folonia et le diagnostic de l'intégration ; un refus y est marqué.
"""

from __future__ import annotations

from collections import deque
from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.util import dt as dt_util

from .const import DOMAIN, JOURNAL_SIZE

#: L'événement que le journal de bord écoute (`logbook.async_log_entry` fait de même).
EVENT_LOGBOOK_ENTRY = "logbook_entry"


class Journal:
    def __init__(self, hass: HomeAssistant) -> None:
        self._hass = hass
        self.entries: deque[dict[str, Any]] = deque(maxlen=JOURNAL_SIZE)

    @callback
    def record(self, message: str, entity_id: str | None = None, *, refused: bool = False) -> None:
        self.entries.append(
            {
                "time": dt_util.utcnow().isoformat(),
                "message": message,
                "entity_id": entity_id,
                "refused": refused,
            }
        )
        data: dict[str, Any] = {"name": "Oscar", "message": message, "domain": DOMAIN}
        if entity_id:
            data["entity_id"] = entity_id
        self._hass.bus.async_fire(EVENT_LOGBOOK_ENTRY, data)
