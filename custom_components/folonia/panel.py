"""La page Folonia, dans la barre latérale de Home Assistant.

Un panneau personnalisé, réservé aux administrateurs : un seul module JavaScript, servi par
l'intégration, sans compilation ni dépendance. La version est dans l'adresse du module : une
mise à jour de l'intégration n'est pas masquée par le cache du navigateur. Le panneau est
aussi la page de configuration de l'intégration (« Configurer » y mène).
"""

from __future__ import annotations

from pathlib import Path

from homeassistant.components import frontend, panel_custom
from homeassistant.components.http import StaticPathConfig
from homeassistant.core import HomeAssistant, callback

from .const import DOMAIN, PANEL_ICON, PANEL_TITLE, PANEL_URL, VERSION

#: Le nom de l'élément personnalisé défini par le module.
ELEMENT = "folonia-panel"
MODULE = Path(__file__).parent / "frontend" / f"{ELEMENT}.js"
MODULE_URL = f"/{DOMAIN}_static/{VERSION}/{ELEMENT}.js"
_SERVED = f"{DOMAIN}_static_served"


async def async_register_module(hass: HomeAssistant) -> None:
    """Le module servi une fois par démarrage : une route ne se retire pas."""
    if hass.data.get(_SERVED):
        return
    await hass.http.async_register_static_paths(
        [StaticPathConfig(MODULE_URL, str(MODULE), cache_headers=True)]
    )
    hass.data[_SERVED] = True


async def async_register_panel(hass: HomeAssistant) -> None:
    await async_register_module(hass)
    await panel_custom.async_register_panel(
        hass,
        frontend_url_path=PANEL_URL,
        webcomponent_name=ELEMENT,
        sidebar_title=PANEL_TITLE,
        sidebar_icon=PANEL_ICON,
        module_url=MODULE_URL,
        require_admin=True,
        config_panel_domain=DOMAIN,
    )


@callback
def async_remove_panel(hass: HomeAssistant) -> None:
    frontend.async_remove_panel(hass, PANEL_URL, warn_if_unknown=False)
