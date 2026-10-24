"""Folonia : la maison, lue et commandée par Oscar au téléphone.

L'intégration ouvre une liaison sortante vers le service Folonia, appariée une fois par un
code de l'espace client. Par défaut, Oscar ne voit rien : l'utilisateur choisit, dans la page
Folonia de la barre latérale, une entité à la fois, ce qu'il peut lire et ce qu'il peut
commander, parmi celles qu'il expose déjà aux assistants vocaux. Par défaut, déverrouiller,
désarmer, ouvrir le portail ou la porte de garage, et lire un appareil sensible (présence,
serrure, alarme, ouverture), exigent un code ou un mot de passe donné au téléphone et vérifié
ici ; chaque protection se décoche, et des appareils peuvent en être exemptés. Chaque lecture
et chaque commande sont inscrites au journal de bord ; un interrupteur coupe tout.
"""

from __future__ import annotations

from functools import partial

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.storage import Store
from homeassistant.helpers.typing import ConfigType

from . import panel, websocket
from .api import async_unlink
from .const import CONF_SECRET, CONF_URL, CONF_VERIFY_SSL, DOMAIN
from .link import STORAGE_VERSION, FoloniaLink, storage_key

PLATFORMS = [Platform.BINARY_SENSOR, Platform.SWITCH]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

type FoloniaConfigEntry = ConfigEntry[FoloniaLink]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Les commandes de la page Folonia ; elles répondent tant qu'une maison est reliée."""
    websocket.async_register(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: FoloniaConfigEntry) -> bool:
    link = FoloniaLink(hass, entry)
    await link.async_load()
    entry.runtime_data = link
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(link.async_stop)
    entry.async_on_unload(entry.add_update_listener(_options_updated))
    # La page Folonia : présente tant que l'intégration est chargée.
    await panel.async_register_panel(hass)
    entry.async_on_unload(partial(panel.async_remove_panel, hass))
    link.async_start()
    return True


async def _options_updated(hass: HomeAssistant, entry: FoloniaConfigEntry) -> None:
    """Les options s'appliquent à la requête suivante ; seul le verrou a un état à suivre."""
    entry.runtime_data.async_options_updated()


async def async_unload_entry(hass: HomeAssistant, entry: FoloniaConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass: HomeAssistant, entry: FoloniaConfigEntry) -> None:
    """Intégration retirée : la maison se délie chez Folonia (au mieux) et oublie son état."""
    await async_unlink(
        hass,
        entry.data[CONF_URL],
        entry.data[CONF_SECRET],
        entry.data.get(CONF_VERIFY_SSL, True),
    )
    await Store(hass, STORAGE_VERSION, storage_key(entry.entry_id)).async_remove()
