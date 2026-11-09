"""Appariement par code ; les options renvoient à la page Folonia."""

from __future__ import annotations

import asyncio

import pytest
from homeassistant.config_entries import SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.folonia.config_flow import SECTION_ADVANCED
from custom_components.folonia.const import (
    CONF_CODE,
    CONF_CONTROL,
    CONF_EXEMPT,
    CONF_LOCK_OPEN,
    CONF_LOCK_READ,
    CONF_READ,
    CONF_SECRET,
    CONF_URL,
    CONF_VERIFY_SSL,
    DEFAULT_URL,
    DOMAIN,
    VERSION,
)

from .fake_folonia import SECRET, FakeFolonia
from .helpers import entity_id

# Le faux service Folonia écoute sur la boucle locale : sockets rouverts pour ce fichier.
pytestmark = pytest.mark.enable_socket


def _saisie(code: str, url: str) -> dict:
    return {CONF_CODE: code, SECTION_ADVANCED: {CONF_URL: url, CONF_VERIFY_SSL: True}}


async def _start(hass: HomeAssistant):
    return await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})


async def test_appariement_par_code(hass: HomeAssistant, folonia: tuple[FakeFolonia, str]) -> None:
    fake, url = folonia
    result = await _start(hass)
    assert result["type"] is FlowResultType.FORM
    # L'adresse du service reste repliée : le formulaire ne montre que le code.
    fields = {str(key): value for key, value in result["data_schema"].schema.items()}
    assert set(fields) == {CONF_CODE, SECTION_ADVANCED}
    assert fields[SECTION_ADVANCED].options["collapsed"] is True

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], _saisie("k7qm-4xt2", url)
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_SECRET] == SECRET
    assert result["data"][CONF_URL] == url
    # Par défaut, rien n'est montré ni commandé ; les protections sont cochées.
    assert result["options"] == {
        CONF_READ: [],
        CONF_CONTROL: [],
        CONF_LOCK_OPEN: True,
        CONF_LOCK_READ: True,
        CONF_EXEMPT: [],
    }
    assert fake.paired_with == [{"code": "K7QM4XT2", "component": VERSION}]

    # La liaison s'ouvre aussitôt, et l'intégration le montre.
    await fake.connected.wait()
    assert fake.received[0] == {"type": "hello", "protocol": 1, "component": VERSION}
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    # La liaison tourne en tâche de fond : elle lit le `welcome` un peu après le faux service.
    for _ in range(100):
        if entry.runtime_data.connected:
            break
        await asyncio.sleep(0.01)
    await hass.async_block_till_done()
    assert hass.states.get(entity_id(hass, entry, "binary_sensor", "link")).state == "on"
    assert hass.states.get(entity_id(hass, entry, "switch", "access")).state == "on"

    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_code_refuse_et_service_injoignable(
    hass: HomeAssistant, folonia: tuple[FakeFolonia, str]
) -> None:
    _, url = folonia
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], _saisie("AAAA-AAAA", url)
    )
    assert result["errors"] == {CONF_CODE: "invalid_code"}

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], _saisie("trop court", url)
    )
    assert result["errors"] == {CONF_CODE: "invalid_code"}

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        _saisie("K7QM4XT2", "http://127.0.0.1:9"),
    )
    assert result["errors"] == {"base": "cannot_connect"}

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], _saisie("K7QM4XT2", "pas une adresse")
    )
    assert result["errors"] == {"base": "invalid_url"}


def test_le_service_par_defaut_est_celui_de_l_api() -> None:
    # folonia.fr est le site public : il répond 404 à /v1/*, l'API est sur compte.folonia.fr.
    assert DEFAULT_URL == "https://compte.folonia.fr"


async def test_sans_section_avancee_le_service_de_folonia(
    hass: HomeAssistant, folonia: tuple[FakeFolonia, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _, url = folonia
    monkeypatch.setattr("custom_components.folonia.config_flow.DEFAULT_URL", url)
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_CODE: "K7QM4XT2"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_URL] == url
    assert result["data"][CONF_VERIFY_SSL] is True
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_les_options_renvoient_a_la_page(
    hass: HomeAssistant, folonia: tuple[FakeFolonia, str]
) -> None:
    fake, url = folonia
    result = await _start(hass)
    await hass.config_entries.flow.async_configure(result["flow_id"], _saisie("K7QM4XT2", url))
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    await fake.connected.wait()
    options = dict(entry.options)
    # Le formulaire d'options n'est plus qu'un renvoi vers la page Folonia ; rien ne change.
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "use_panel"
    assert result["description_placeholders"] == {"url": "/folonia"}
    assert entry.options == options
    assert await hass.config_entries.async_unload(entry.entry_id)
