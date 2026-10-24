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
    CONF_CLEAR_CODE,
    CONF_CLEAR_PHRASE,
    CONF_CODE,
    CONF_CONTROL,
    CONF_EXEMPT,
    CONF_LOCK_CODE,
    CONF_LOCK_HASH,
    CONF_LOCK_OPEN,
    CONF_LOCK_PHRASE,
    CONF_LOCK_READ,
    CONF_LOCK_SALT,
    CONF_PHRASE_HASH,
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
    # Par défaut, rien n'est montré ni commandé ; les protections sont cochées.
    assert result["options"] == {
        CONF_READ: [],
        CONF_CONTROL: [],
        CONF_LOCK_OPEN: True,
        CONF_LOCK_READ: True,
        CONF_EXEMPT: [],
    }
    assert fake.paired_with == [{"code": "K7QM4XT2", "component": "0.4.0"}]

    # La liaison s'ouvre aussitôt, et l'intégration le montre.
    await fake.connected.wait()
    assert fake.received[0] == {"type": "hello", "protocol": 1, "component": "0.4.0"}
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
        CONF_LOCK_OPEN: True,
        CONF_LOCK_READ: True,
        CONF_EXEMPT: [],
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

    # Une serrure cochée en commande exige un code tant que « lock_open » est coché, même
    # « lock_read » décoché ; le code est gardé en empreinte.
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


async def _options_flow(hass: HomeAssistant, folonia: tuple[FakeFolonia, str], options=None):
    """Une maison reliée, avec une serrure, la porte du garage, une lumière, un capteur."""
    fake, url = folonia
    assert await async_setup_component(hass, "homeassistant", {})
    hass.states.async_set("light.cuisine", "on", {"friendly_name": "Lumière cuisine"})
    hass.states.async_set("lock.entree", "locked", {"friendly_name": "Serrure"})
    hass.states.async_set(
        "cover.garage", "closed", {"friendly_name": "Porte du garage", "device_class": "garage"}
    )
    hass.states.async_set(
        "sensor.salon", "21", {"friendly_name": "Salon", "unit_of_measurement": "°C"}
    )
    for exposed in ("light.cuisine", "lock.entree", "cover.garage", "sensor.salon"):
        async_expose_entity(hass, "conversation", exposed, True)
    result = await _start(hass)
    await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_CODE: "K7QM4XT2", CONF_URL: url, CONF_VERIFY_SSL: True}
    )
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    if options is not None:
        hass.config_entries.async_update_entry(entry, options=options)
    await fake.connected.wait()
    return entry


#: Un formulaire rempli de zéro : rien de partagé, protections cochées, aucune exemption. Un
#: champ absent prendrait sinon la valeur déjà enregistrée.
BLANK = {
    CONF_READ: [],
    CONF_CONTROL: [],
    CONF_LOCK_OPEN: True,
    CONF_LOCK_READ: True,
    CONF_EXEMPT: [],
}


async def _submit(hass: HomeAssistant, entry, values: dict):
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    return await hass.config_entries.options.async_configure(result["flow_id"], {**BLANK, **values})


async def test_protections_decochables_sans_secret_exige(
    hass: HomeAssistant, folonia: tuple[FakeFolonia, str]
) -> None:
    entry = await _options_flow(hass, folonia)
    # « lock_open » décoché : une serrure et le garage en commande, sans aucun secret. On
    # avertit (description), on ne refuse pas.
    result = await _submit(
        hass,
        entry,
        {
            CONF_READ: [],
            CONF_CONTROL: ["lock.entree", "cover.garage"],
            CONF_LOCK_OPEN: False,
            CONF_LOCK_READ: False,
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_LOCK_OPEN] is False
    assert CONF_LOCK_HASH not in entry.options and CONF_PHRASE_HASH not in entry.options

    # Rien de protégé n'est partagé : ni code ni mot de passe exigé, cases cochées.
    result = await _submit(hass, entry, {CONF_READ: ["light.cuisine", "sensor.salon"]})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_LOCK_OPEN] is True and entry.options[CONF_LOCK_READ] is True

    # Case cochée et serrure en commande : un secret est exigé.
    result = await _submit(hass, entry, {CONF_CONTROL: ["lock.entree"], CONF_LOCK_READ: False})
    assert result["errors"] == {CONF_LOCK_CODE: "lock_code_required"}
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_appareils_sans_code(hass: HomeAssistant, folonia: tuple[FakeFolonia, str]) -> None:
    entry = await _options_flow(hass, folonia)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    # Ne sont proposés à l'exemption que les appareils qui peuvent être sous code.
    exempt = result["data_schema"].schema[CONF_EXEMPT]
    assert {o["value"] for o in exempt.config["options"]} == {"lock.entree", "cover.garage"}

    # Le garage exempté, en lecture et en commande, cases cochées : aucun secret exigé.
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_READ: ["cover.garage"],
            CONF_CONTROL: ["cover.garage"],
            CONF_EXEMPT: ["cover.garage"],
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_EXEMPT] == ["cover.garage"]

    # Une exemption ne vaut que pour un appareil partagé ; la serrure, non exemptée, exige un
    # secret.
    result = await _submit(
        hass,
        entry,
        {CONF_CONTROL: ["lock.entree"], CONF_EXEMPT: ["cover.garage"]},
    )
    assert result["errors"] == {CONF_LOCK_CODE: "lock_code_required"}
    result = await _submit(
        hass,
        entry,
        {CONF_CONTROL: ["lock.entree"], CONF_EXEMPT: ["lock.entree", "cover.garage"]},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_EXEMPT] == ["lock.entree"]
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_mot_de_passe_parle_et_effacement(
    hass: HomeAssistant, folonia: tuple[FakeFolonia, str]
) -> None:
    entry = await _options_flow(hass, folonia)
    # Trop court pour être un mot de passe : refusé ; quatre lettres suffisent.
    result = await _submit(hass, entry, {CONF_CONTROL: ["lock.entree"], CONF_LOCK_PHRASE: "Ah !"})
    assert result["errors"] == {CONF_LOCK_PHRASE: "invalid_lock_phrase"}
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {**BLANK, CONF_CONTROL: ["lock.entree"], CONF_LOCK_PHRASE: "Dragon rouge."},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert len(entry.options[CONF_PHRASE_HASH]) == 64
    assert CONF_LOCK_HASH not in entry.options
    assert CONF_LOCK_PHRASE not in entry.options
    assert "Dragon" not in str(entry.options) and "dragon" not in str(entry.options)
    phrase = entry.options[CONF_PHRASE_HASH]

    # Un code chiffré en plus ; le mot de passe est gardé.
    result = await _submit(hass, entry, {CONF_CONTROL: ["lock.entree"], CONF_LOCK_CODE: "2468"})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_PHRASE_HASH] == phrase
    assert len(entry.options[CONF_LOCK_HASH]) == 64

    # Effacer le mot de passe garde le code ; effacer les deux, serrure partagée, est refusé.
    result = await _submit(hass, entry, {CONF_CONTROL: ["lock.entree"], CONF_CLEAR_PHRASE: True})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert CONF_PHRASE_HASH not in entry.options and CONF_LOCK_HASH in entry.options
    result = await _submit(hass, entry, {CONF_CONTROL: ["lock.entree"], CONF_CLEAR_CODE: True})
    assert result["errors"] == {CONF_LOCK_CODE: "lock_code_required"}
    # Rien de protégé : tout peut être effacé.
    result = await _submit(hass, entry, {CONF_READ: ["light.cuisine"], CONF_CLEAR_CODE: True})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert CONF_LOCK_HASH not in entry.options and CONF_LOCK_SALT not in entry.options
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_reglages_d_une_installation_0_3(
    hass: HomeAssistant, folonia: tuple[FakeFolonia, str]
) -> None:
    from custom_components.folonia.voicelock import hash_code

    lock_hash, lock_salt = hash_code("2468")
    # Les options telles que 0.3.0 les a laissées : ni « lock_open », ni exemptions.
    entry = await _options_flow(
        hass,
        folonia,
        {
            CONF_READ: ["light.cuisine"],
            CONF_CONTROL: ["lock.entree"],
            CONF_LOCK_READ: False,
            CONF_LOCK_HASH: lock_hash,
            CONF_LOCK_SALT: lock_salt,
        },
    )
    result = await hass.config_entries.options.async_init(entry.entry_id)
    defaults = {getattr(key, "schema", key): key.default() for key in result["data_schema"].schema}
    assert defaults[CONF_LOCK_OPEN] is True
    assert defaults[CONF_LOCK_READ] is False
    assert defaults[CONF_EXEMPT] == []
    assert defaults[CONF_CONTROL] == ["lock.entree"]
    # Enregistré tel quel : le code chiffré est gardé, les nouvelles clés prennent leur défaut.
    result = await hass.config_entries.options.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_LOCK_HASH] == lock_hash
    assert entry.options[CONF_LOCK_OPEN] is True
    assert entry.options[CONF_EXEMPT] == []
    assert await hass.config_entries.async_unload(entry.entry_id)
