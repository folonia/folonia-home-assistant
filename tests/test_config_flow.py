"""Appariement par code et choix de ce qu'Oscar peut lire."""

from __future__ import annotations

import asyncio

import pytest
from homeassistant.components.homeassistant.exposed_entities import async_expose_entity
from homeassistant.config_entries import SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.setup import async_setup_component

from custom_components.folonia.const import (
    CONF_CODE,
    CONF_CONTROL,
    CONF_LOCK_CODE,
    CONF_LOCK_HASH,
    CONF_LOCK_READ,
    CONF_READ,
    CONF_SECRET,
    CONF_URL,
    CONF_VERIFY_SSL,
    DOMAIN,
)

from .fake_folonia import SECRET, FakeFolonia
from .helpers import entity_id

# Le faux service Folonia écoute sur la boucle locale : sockets rouverts pour ce fichier.
pytestmark = pytest.mark.enable_socket


async def _start(hass: HomeAssistant):
    return await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER, "show_advanced_options": True}
    )


async def test_appariement_par_code(hass: HomeAssistant, folonia: tuple[FakeFolonia, str]) -> None:
    fake, url = folonia
    result = await _start(hass)
    assert result["type"] is FlowResultType.FORM

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_CODE: "k7qm-4xt2", CONF_URL: url, CONF_VERIFY_SSL: True}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_SECRET] == SECRET
    assert result["data"][CONF_URL] == url
    # Par défaut, rien n'est montré ni commandé.
    assert result["options"] == {CONF_READ: [], CONF_CONTROL: [], CONF_LOCK_READ: True}
    assert fake.paired_with == [{"code": "K7QM4XT2", "component": "0.3.0"}]

    # La liaison s'ouvre aussitôt, et l'intégration le montre.
    await fake.connected.wait()
    assert fake.received[0] == {"type": "hello", "protocol": 1, "component": "0.3.0"}
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
        result["flow_id"], {CONF_CODE: "AAAA-AAAA", CONF_URL: url, CONF_VERIFY_SSL: True}
    )
    assert result["errors"] == {CONF_CODE: "invalid_code"}

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_CODE: "trop court", CONF_URL: url, CONF_VERIFY_SSL: True}
    )
    assert result["errors"] == {CONF_CODE: "invalid_code"}

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_CODE: "K7QM4XT2", CONF_URL: "http://127.0.0.1:9", CONF_VERIFY_SSL: True},
    )
    assert result["errors"] == {"base": "cannot_connect"}


async def test_choix_parmi_les_entites_exposees_a_assist(
    hass: HomeAssistant, folonia: tuple[FakeFolonia, str]
) -> None:
    fake, url = folonia
    assert await async_setup_component(hass, "homeassistant", {})
    result = await _start(hass)
    await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_CODE: "K7QM4XT2", CONF_URL: url, CONF_VERIFY_SSL: True}
    )
    entry = hass.config_entries.async_entries(DOMAIN)[0]

    # Rien d'exposé aux assistants vocaux : rien à choisir.
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "nothing_exposed"

    hass.states.async_set("light.cuisine", "on", {"friendly_name": "Lumière cuisine"})
    hass.states.async_set("lock.entree", "locked", {"friendly_name": "Serrure"})
    hass.states.async_set("switch.cachee", "on", {"friendly_name": "Cachée"})
    async_expose_entity(hass, "conversation", "light.cuisine", True)
    async_expose_entity(hass, "conversation", "lock.entree", True)
    async_expose_entity(hass, "conversation", "switch.cachee", False)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    selector = result["data_schema"].schema[CONF_READ]
    labels = {o["value"]: o["label"] for o in selector.config["options"]}
    assert labels == {
        "light.cuisine": "Lumière cuisine · lumière : allumé",
        "lock.entree": "Serrure · serrure : verrouillé ⚠",
    }

    control = result["data_schema"].schema[CONF_CONTROL]
    assert {o["value"] for o in control.config["options"]} == {"light.cuisine", "lock.entree"}

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_READ: ["light.cuisine"]}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options == {
        CONF_READ: ["light.cuisine"],
        CONF_CONTROL: [],
        CONF_LOCK_READ: True,
    }

    # Une serrure partagée en lecture, case cochée (par défaut), exige un code ; décochée, non.
    result = await hass.config_entries.options.async_init(entry.entry_id)
    lock_read = result["data_schema"].schema
    assert any(getattr(k, "schema", None) == CONF_LOCK_READ for k in lock_read)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_READ: ["lock.entree"], CONF_CONTROL: []}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_LOCK_CODE: "lock_code_required"}
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_READ: ["lock.entree"], CONF_CONTROL: [], CONF_LOCK_READ: False}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_LOCK_READ] is False

    # Une serrure cochée en commande exige un code, case décochée ou non ; le code est gardé
    # en empreinte.
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_READ: [], CONF_CONTROL: ["lock.entree"], CONF_LOCK_READ: False}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_LOCK_CODE: "lock_code_required"}
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_READ: [], CONF_CONTROL: ["lock.entree"], CONF_LOCK_CODE: "12"}
    )
    assert result["errors"] == {CONF_LOCK_CODE: "invalid_lock_code"}
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {CONF_READ: [], CONF_CONTROL: ["lock.entree"], CONF_LOCK_CODE: "24 68"},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_CONTROL] == ["lock.entree"]
    assert CONF_LOCK_CODE not in entry.options
    assert len(entry.options[CONF_LOCK_HASH]) == 64
    hashed = entry.options[CONF_LOCK_HASH]

    # Champ vide : le code est gardé.
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_READ: ["light.cuisine"], CONF_CONTROL: ["lock.entree"]}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_LOCK_HASH] == hashed
    await fake.connected.wait()
    assert await hass.config_entries.async_unload(entry.entry_id)
