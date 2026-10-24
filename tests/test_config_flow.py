"""Appariement par code, puis les options : un menu, chaque partie enregistrée seule."""

from __future__ import annotations

import asyncio

import pytest
from homeassistant.components.homeassistant.exposed_entities import async_expose_entity
from homeassistant.config_entries import SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType, InvalidData
from homeassistant.setup import async_setup_component
from homeassistant.util.uuid import random_uuid_hex

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
    CONF_PHRASE_SALT,
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
    assert fake.paired_with == [{"code": "K7QM4XT2", "component": "0.4.1"}]

    # La liaison s'ouvre aussitôt, et l'intégration le montre.
    await fake.connected.wait()
    assert fake.received[0] == {"type": "hello", "protocol": 1, "component": "0.4.1"}
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


async def _menu(hass: HomeAssistant, entry):
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.MENU
    return result


async def _step(hass: HomeAssistant, entry, step: str):
    """Le menu, puis une de ses parties."""
    result = await _menu(hass, entry)
    return await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": step}
    )


async def _submit(hass: HomeAssistant, entry, step: str, values: dict):
    result = await _step(hass, entry, step)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == step
    return await hass.config_entries.options.async_configure(result["flow_id"], values)


def _defaults(result) -> dict:
    return {getattr(key, "schema", key): key.default() for key in result["data_schema"].schema}


async def test_menu_et_choix_parmi_les_entites_exposees(
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

    # Le menu, et son résumé : rien de partagé, aucun secret.
    result = await _menu(hass, entry)
    assert result["step_id"] == "init"
    assert list(result["menu_options"]) == ["read", "control", "exempt", "protections"]
    assert result["description_placeholders"] == {
        "read": "0",
        "control": "0",
        "exempt": "0",
        "lock_state": "—",
        "phrase_state": "—",
    }

    # Le sélecteur natif, limité aux entités exposées ; les sensibles sont rappelées, avec leur
    # nature et leur valeur du moment, dans la description.
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "read"}
    )
    assert result["step_id"] == "read"
    selector = result["data_schema"].schema[CONF_READ]
    config = selector.serialize()["selector"]["entity"]
    assert config["include_entities"] == ["light.cuisine", "lock.entree"]
    assert config["multiple"] is True
    assert result["description_placeholders"] == {"sensitive": "- Serrure · serrure : verrouillé ⚠"}
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

    result = await _step(hass, entry, "control")
    control = result["data_schema"].schema[CONF_CONTROL]
    assert control.config["include_entities"] == ["light.cuisine", "lock.entree"]
    assert result["description_placeholders"] == {"opens": "- Serrure · serrure : verrouillé ⚠"}

    # Une serrure partagée en lecture, case cochée (par défaut), sans secret : la liste est
    # enregistrée, et l'on passe à « Code et protections », qui dit pourquoi.
    result = await _submit(hass, entry, "read", {CONF_READ: ["light.cuisine", "lock.entree"]})
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "protections"
    assert result["errors"] == {"base": "secret_needed"}
    assert entry.options[CONF_READ] == ["light.cuisine", "lock.entree"]
    # Case décochée : plus rien n'exige de secret.
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_LOCK_READ: False}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_LOCK_READ] is False
    assert entry.options[CONF_READ] == ["light.cuisine", "lock.entree"]

    # Une serrure cochée en commande exige un secret tant que « lock_open » est coché, même
    # « lock_read » décoché ; le code est gardé en empreinte.
    result = await _submit(hass, entry, "control", {CONF_CONTROL: ["lock.entree"]})
    assert result["step_id"] == "protections"
    assert result["errors"] == {"base": "secret_needed"}
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_LOCK_CODE: "12"}
    )
    assert result["errors"] == {CONF_LOCK_CODE: "invalid_lock_code"}
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_LOCK_CODE: "24 68"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_CONTROL] == ["lock.entree"]
    assert CONF_LOCK_CODE not in entry.options
    assert len(entry.options[CONF_LOCK_HASH]) == 64
    hashed = entry.options[CONF_LOCK_HASH]

    # Champ vide : le code est gardé ; le menu le dit réglé.
    result = await _submit(hass, entry, "protections", {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_LOCK_HASH] == hashed
    result = await _menu(hass, entry)
    assert result["description_placeholders"] == {
        "read": "2",
        "control": "1",
        "exempt": "0",
        "lock_state": "✓",
        "phrase_state": "—",
    }
    await fake.connected.wait()
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_entite_non_permise_ecartee(
    hass: HomeAssistant, folonia: tuple[FakeFolonia, str]
) -> None:
    entry = await _options_flow(hass, folonia)
    hass.states.async_set("switch.cachee", "on", {"friendly_name": "Cachée"})
    async_expose_entity(hass, "conversation", "switch.cachee", False)

    # Hors de la liste permise : le sélecteur refuse.
    result = await _step(hass, entry, "read")
    with pytest.raises(InvalidData):
        await hass.config_entries.options.async_configure(
            result["flow_id"], {CONF_READ: ["switch.cachee"]}
        )
    result = await _step(hass, entry, "control")
    with pytest.raises(InvalidData):
        await hass.config_entries.options.async_configure(
            result["flow_id"], {CONF_CONTROL: ["sensor.salon"]}
        )

    # Ce que le sélecteur laisse passer (un identifiant de registre) et une entité qui perd son
    # exposition entre l'affichage et l'envoi : écartés à l'enregistrement.
    result = await _step(hass, entry, "read")
    async_expose_entity(hass, "conversation", "sensor.salon", False)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {CONF_READ: ["light.cuisine", "sensor.salon", random_uuid_hex(), "light.cuisine"]},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_READ] == ["light.cuisine"]

    # Une entité enregistrée qui perd son exposition disparaît de la liste proposée, du
    # résumé, et de la liste à l'enregistrement suivant.
    result = await _submit(hass, entry, "control", {CONF_CONTROL: ["light.cuisine"]})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    async_expose_entity(hass, "conversation", "light.cuisine", False)
    result = await _menu(hass, entry)
    assert result["description_placeholders"]["read"] == "0"
    assert result["description_placeholders"]["control"] == "0"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "control"}
    )
    assert (
        "light.cuisine" not in result["data_schema"].schema[CONF_CONTROL].config["include_entities"]
    )
    assert _defaults(result)[CONF_CONTROL] == []
    result = await hass.config_entries.options.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_CONTROL] == []
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_rien_a_commander_ni_a_exempter(
    hass: HomeAssistant, folonia: tuple[FakeFolonia, str]
) -> None:
    entry = await _options_flow(hass, folonia)
    # Rien de partagé : aucun appareil à laisser sans code.
    result = await _step(hass, entry, "exempt")
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "nothing_to_exempt"
    # Seul le capteur exposé : rien à commander.
    for hidden in ("light.cuisine", "lock.entree", "cover.garage"):
        async_expose_entity(hass, "conversation", hidden, False)
    result = await _step(hass, entry, "control")
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "nothing_controllable"
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_chaque_etape_garde_les_autres_cles(
    hass: HomeAssistant, folonia: tuple[FakeFolonia, str]
) -> None:
    from custom_components.folonia.voicelock import hash_code

    lock_hash, lock_salt = hash_code("2468")
    phrase_hash, phrase_salt = hash_code("dragon rouge")
    options = {
        CONF_READ: ["light.cuisine", "cover.garage"],
        CONF_CONTROL: ["cover.garage"],
        CONF_LOCK_OPEN: False,
        CONF_LOCK_READ: True,
        CONF_EXEMPT: ["cover.garage"],
        CONF_LOCK_HASH: lock_hash,
        CONF_LOCK_SALT: lock_salt,
        CONF_PHRASE_HASH: phrase_hash,
        CONF_PHRASE_SALT: phrase_salt,
    }
    entry = await _options_flow(hass, folonia, options)

    result = await _step(hass, entry, "control")
    assert _defaults(result) == {CONF_CONTROL: ["cover.garage"]}
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_CONTROL: ["cover.garage", "light.cuisine"]}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options == {**options, CONF_CONTROL: ["cover.garage", "light.cuisine"]}

    result = await _step(hass, entry, "protections")
    assert _defaults(result)[CONF_LOCK_OPEN] is False
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_LOCK_OPEN: True, CONF_LOCK_READ: False}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options == {
        **options,
        CONF_CONTROL: ["cover.garage", "light.cuisine"],
        CONF_LOCK_OPEN: True,
        CONF_LOCK_READ: False,
    }

    # Le garage reste partagé (en commande) : son exemption est gardée.
    result = await _submit(hass, entry, "read", {CONF_READ: ["light.cuisine"]})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_EXEMPT] == ["cover.garage"]
    # Plus partagé du tout : l'exemption tombe, il ne reviendrait pas sans code.
    result = await _submit(hass, entry, "control", {CONF_CONTROL: ["light.cuisine"]})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_EXEMPT] == []
    assert entry.options[CONF_LOCK_HASH] == lock_hash
    assert entry.options[CONF_PHRASE_HASH] == phrase_hash
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_protections_decochables_sans_secret_exige(
    hass: HomeAssistant, folonia: tuple[FakeFolonia, str]
) -> None:
    entry = await _options_flow(hass, folonia)
    # Rien de protégé n'est partagé : ni code ni mot de passe exigé, cases cochées.
    result = await _submit(hass, entry, "read", {CONF_READ: ["light.cuisine", "sensor.salon"]})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_LOCK_OPEN] is True and entry.options[CONF_LOCK_READ] is True

    # Protections décochées : une serrure et le garage en commande, sans aucun secret. On
    # avertit (description), on ne refuse pas.
    result = await _submit(
        hass, entry, "protections", {CONF_LOCK_OPEN: False, CONF_LOCK_READ: False}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    result = await _submit(hass, entry, "control", {CONF_CONTROL: ["lock.entree", "cover.garage"]})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_LOCK_OPEN] is False
    assert CONF_LOCK_HASH not in entry.options and CONF_PHRASE_HASH not in entry.options

    # Case recochée, serrure en commande : un secret est exigé, rien n'est enregistré.
    result = await _submit(
        hass, entry, "protections", {CONF_LOCK_OPEN: True, CONF_LOCK_READ: False}
    )
    assert result["errors"] == {CONF_LOCK_CODE: "lock_code_required"}
    assert entry.options[CONF_LOCK_OPEN] is False
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_appareils_sans_code(hass: HomeAssistant, folonia: tuple[FakeFolonia, str]) -> None:
    entry = await _options_flow(hass, folonia)
    # Le garage partagé, cases cochées, sans secret : enregistré, puis le secret demandé.
    result = await _submit(hass, entry, "read", {CONF_READ: ["cover.garage"]})
    assert result["errors"] == {"base": "secret_needed"}
    result = await _submit(hass, entry, "control", {CONF_CONTROL: ["cover.garage"]})
    assert result["errors"] == {"base": "secret_needed"}
    # Ne sont proposés à l'exemption que les appareils partagés qui peuvent être sous code.
    result = await _step(hass, entry, "exempt")
    exempt = result["data_schema"].schema[CONF_EXEMPT]
    assert exempt.config["include_entities"] == ["cover.garage"]
    # Le garage exempté : plus aucun secret exigé.
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_EXEMPT: ["cover.garage"]}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_EXEMPT] == ["cover.garage"]
    assert entry.options[CONF_READ] == entry.options[CONF_CONTROL] == ["cover.garage"]

    # La serrure, partagée et non exemptée, exige un secret ; exemptée, non.
    result = await _submit(hass, entry, "control", {CONF_CONTROL: ["lock.entree", "cover.garage"]})
    assert result["errors"] == {"base": "secret_needed"}
    result = await hass.config_entries.options.async_configure(result["flow_id"], {})
    assert result["errors"] == {CONF_LOCK_CODE: "lock_code_required"}
    result = await _step(hass, entry, "exempt")
    assert result["data_schema"].schema[CONF_EXEMPT].config["include_entities"] == [
        "cover.garage",
        "lock.entree",
    ]
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_EXEMPT: ["lock.entree", "cover.garage"]}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_EXEMPT] == ["lock.entree", "cover.garage"]
    result = await _submit(hass, entry, "protections", {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_mot_de_passe_parle_et_effacement(
    hass: HomeAssistant, folonia: tuple[FakeFolonia, str]
) -> None:
    entry = await _options_flow(hass, folonia)
    result = await _submit(hass, entry, "control", {CONF_CONTROL: ["lock.entree"]})
    assert result["errors"] == {"base": "secret_needed"}
    # Trop court pour être un mot de passe : refusé ; quatre lettres suffisent.
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_LOCK_PHRASE: "Ah !"}
    )
    assert result["errors"] == {CONF_LOCK_PHRASE: "invalid_lock_phrase"}
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_LOCK_PHRASE: "Dragon rouge."}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert len(entry.options[CONF_PHRASE_HASH]) == 64
    assert CONF_LOCK_HASH not in entry.options
    assert CONF_LOCK_PHRASE not in entry.options
    assert "Dragon" not in str(entry.options) and "dragon" not in str(entry.options)
    phrase = entry.options[CONF_PHRASE_HASH]

    # Un code chiffré en plus ; le mot de passe est gardé.
    result = await _submit(hass, entry, "protections", {CONF_LOCK_CODE: "2468"})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_PHRASE_HASH] == phrase
    assert len(entry.options[CONF_LOCK_HASH]) == 64

    # Effacer le mot de passe garde le code ; effacer les deux, serrure partagée, est refusé.
    result = await _submit(hass, entry, "protections", {CONF_CLEAR_PHRASE: True})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert CONF_PHRASE_HASH not in entry.options and CONF_LOCK_HASH in entry.options
    result = await _submit(hass, entry, "protections", {CONF_CLEAR_CODE: True})
    assert result["errors"] == {CONF_LOCK_CODE: "lock_code_required"}
    assert CONF_LOCK_HASH in entry.options
    # Rien de protégé : tout peut être effacé.
    result = await _submit(hass, entry, "control", {CONF_CONTROL: []})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    result = await _submit(hass, entry, "protections", {CONF_CLEAR_CODE: True})
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
    result = await _menu(hass, entry)
    assert result["description_placeholders"] == {
        "read": "1",
        "control": "1",
        "exempt": "0",
        "lock_state": "✓",
        "phrase_state": "—",
    }
    result = await _step(hass, entry, "protections")
    defaults = _defaults(result)
    assert defaults[CONF_LOCK_OPEN] is True
    assert defaults[CONF_LOCK_READ] is False
    result = await _step(hass, entry, "control")
    assert _defaults(result)[CONF_CONTROL] == ["lock.entree"]
    # Enregistré tel quel : le code chiffré est gardé, les nouvelles clés prennent leur défaut.
    result = await _submit(hass, entry, "protections", {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_LOCK_HASH] == lock_hash
    assert entry.options[CONF_LOCK_OPEN] is True
    assert entry.options[CONF_READ] == ["light.cuisine"]
    result = await _submit(hass, entry, "read", {CONF_READ: ["light.cuisine", "sensor.salon"]})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options == {
        CONF_READ: ["light.cuisine", "sensor.salon"],
        CONF_CONTROL: ["lock.entree"],
        CONF_LOCK_OPEN: True,
        CONF_LOCK_READ: False,
        CONF_EXEMPT: [],
        CONF_LOCK_HASH: lock_hash,
        CONF_LOCK_SALT: lock_salt,
    }
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_reglages_d_une_installation_0_4(
    hass: HomeAssistant, folonia: tuple[FakeFolonia, str]
) -> None:
    from custom_components.folonia.voicelock import hash_code

    phrase_hash, phrase_salt = hash_code("dragon rouge")
    # Les options telles que 0.4.0 les a laissées : toutes les clés, écrites d'un coup.
    options = {
        CONF_READ: ["light.cuisine", "cover.garage"],
        CONF_CONTROL: ["lock.entree", "cover.garage"],
        CONF_LOCK_OPEN: True,
        CONF_LOCK_READ: True,
        CONF_EXEMPT: ["cover.garage"],
        CONF_PHRASE_HASH: phrase_hash,
        CONF_PHRASE_SALT: phrase_salt,
    }
    entry = await _options_flow(hass, folonia, options)
    result = await _menu(hass, entry)
    assert result["description_placeholders"] == {
        "read": "2",
        "control": "2",
        "exempt": "1",
        "lock_state": "—",
        "phrase_state": "✓",
    }
    result = await _step(hass, entry, "exempt")
    assert _defaults(result) == {CONF_EXEMPT: ["cover.garage"]}
    result = await hass.config_entries.options.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    result = await _submit(hass, entry, "protections", {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options == options
    assert await hass.config_entries.async_unload(entry.entry_id)
