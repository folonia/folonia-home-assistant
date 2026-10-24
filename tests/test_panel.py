"""La page Folonia : le panneau, ses commandes WebSocket, et les réglages d'avant 0.5.0."""

from __future__ import annotations

import json
from typing import Any

import pytest
from homeassistant.components.homeassistant.exposed_entities import async_expose_entity
from homeassistant.core import HomeAssistant
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import entity_registry as er
from homeassistant.setup import async_setup_component
from homeassistant.util.uuid import random_uuid_hex
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.folonia import exposure
from custom_components.folonia.const import (
    CONF_CONTROL,
    CONF_EXEMPT,
    CONF_LINK_ID,
    CONF_LOCK_HASH,
    CONF_LOCK_OPEN,
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
from custom_components.folonia.voicelock import hash_code

from .fake_folonia import LINK_ID, FakeFolonia

# Le faux service Folonia et le client WebSocket écoutent sur la boucle locale.
pytestmark = pytest.mark.enable_socket

FRONTEND_PANELS = "frontend_panels"
MODULE_URL = "/folonia_static/0.5.0/folonia-panel.js"


async def _home(
    hass: HomeAssistant, folonia: tuple[FakeFolonia, str], options: dict[str, Any] | None = None
) -> MockConfigEntry:
    """Une maison reliée : lumière, serrure, porte du garage, capteur, et un interrupteur caché."""
    fake, url = folonia
    assert await async_setup_component(hass, "homeassistant", {})
    kitchen = ar.async_get(hass).async_create("Cuisine")
    registry = er.async_get(hass)
    light = registry.async_get_or_create("light", "test", "cuisine", suggested_object_id="cuisine")
    registry.async_update_entity(light.entity_id, area_id=kitchen.id)
    hass.states.async_set("light.cuisine", "on", {"friendly_name": "Lumière cuisine"})
    hass.states.async_set("lock.entree", "locked", {"friendly_name": "Serrure"})
    hass.states.async_set(
        "cover.garage", "closed", {"friendly_name": "Porte du garage", "device_class": "garage"}
    )
    hass.states.async_set(
        "sensor.salon", "21.5", {"friendly_name": "Salon", "unit_of_measurement": "°C"}
    )
    hass.states.async_set("switch.cachee", "on", {"friendly_name": "Cachée"})
    for exposed in ("light.cuisine", "lock.entree", "cover.garage", "sensor.salon"):
        async_expose_entity(hass, "conversation", exposed, True)
    async_expose_entity(hass, "conversation", "switch.cachee", False)
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_URL: url,
            CONF_VERIFY_SSL: True,
            CONF_LINK_ID: LINK_ID,
            CONF_SECRET: fake.link_secret(),
        },
        options=options
        if options is not None
        else {
            CONF_READ: [],
            CONF_CONTROL: [],
            CONF_LOCK_OPEN: True,
            CONF_LOCK_READ: True,
            CONF_EXEMPT: [],
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await fake.connected.wait()
    return entry


async def _ws(client, **message: Any) -> dict[str, Any]:
    await client.send_json_auto_id(message)
    return await client.receive_json()


def _choices(result: dict[str, Any]) -> dict[str, tuple[bool, bool, bool]]:
    return {d["entity_id"]: (d["read"], d["control"], d["exempt"]) for d in result["devices"]}


def _no_fingerprint(result: dict[str, Any], entry: MockConfigEntry) -> None:
    """Ni empreinte ni sel ne sortent par la page, quels que soient les secrets réglés."""
    text = json.dumps(result)
    for key in (CONF_LOCK_HASH, CONF_LOCK_SALT, CONF_PHRASE_HASH, CONF_PHRASE_SALT):
        assert key not in text
        if entry.options.get(key):
            assert entry.options[key] not in text


async def test_page_enregistree_puis_retiree(
    hass: HomeAssistant, folonia: tuple[FakeFolonia, str], hass_client
) -> None:
    entry = await _home(hass, folonia)
    panel = hass.data[FRONTEND_PANELS]["folonia"]
    assert panel.component_name == "custom"
    assert panel.sidebar_title == "Folonia"
    assert panel.sidebar_icon == "mdi:home-account"
    assert panel.require_admin is True
    assert panel.config_panel_domain == DOMAIN
    assert panel.config["_panel_custom"] == {
        "name": "folonia-panel",
        "embed_iframe": False,
        "trust_external": False,
        "module_url": MODULE_URL,
    }
    # Le module est servi par l'intégration, la version dans l'adresse.
    client = await hass_client()
    response = await client.get(MODULE_URL)
    assert response.status == 200
    body = await response.text()
    assert 'const TAG = "folonia-panel";' in body
    assert "customElements.define(TAG, FoloniaPanel)" in body

    # Déchargée : la page disparaît ; rechargée, elle revient.
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert "folonia" not in hass.data[FRONTEND_PANELS]
    assert await hass.config_entries.async_setup(entry.entry_id)
    assert "folonia" in hass.data[FRONTEND_PANELS]
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_lecture_des_reglages(
    hass: HomeAssistant, folonia: tuple[FakeFolonia, str], hass_ws_client
) -> None:
    lock_hash, lock_salt = hash_code("2468")
    entry = await _home(
        hass,
        folonia,
        {
            CONF_READ: ["light.cuisine", "cover.garage"],
            CONF_CONTROL: ["cover.garage"],
            CONF_LOCK_OPEN: True,
            CONF_LOCK_READ: True,
            CONF_EXEMPT: ["cover.garage"],
            CONF_LOCK_HASH: lock_hash,
            CONF_LOCK_SALT: lock_salt,
        },
    )
    client = await hass_ws_client(hass)
    reply = await _ws(client, type="folonia/settings")
    assert reply["success"] is True
    result = reply["result"]
    # Seules les entités exposées aux assistants vocaux, sans celles de l'intégration.
    assert [d["entity_id"] for d in result["devices"]] == [
        "cover.garage",
        "light.cuisine",
        "lock.entree",
        "sensor.salon",
    ]
    garage, light, lock, salon = result["devices"]
    assert garage == {
        "entity_id": "cover.garage",
        "name": "Porte du garage",
        "area": None,
        "domain": "cover",
        "device_class": "garage",
        "kind": "volet ou porte",
        "state": "fermé",
        "sensitive": True,
        "opens_home": True,
        "controllable": True,
        "protectable": True,
        "read": True,
        "control": True,
        "exempt": True,
    }
    assert light["area"] == "Cuisine" and light["state"] == "allumé"
    assert (light["sensitive"], light["protectable"], light["controllable"]) == (
        False,
        False,
        True,
    )
    assert lock["kind"] == "serrure" and lock["state"] == "verrouillé" and lock["sensitive"]
    assert salon["state"] == "21,5 °C" and salon["controllable"] is False
    assert result["protections"] == {"lock_open": True, "lock_read": True}
    assert result["secrets"] == {"code": True, "phrase": False}
    assert result["lock"] == {"locked": False, "failures": 0, "max_failures": 5}
    assert result["secret_needed"] is False
    assert result["max_shared"] == 200
    link = result["link"]
    assert (link["enabled"], link["connected"], link["stopped"]) == (True, True, None)
    assert hass.states.get(link["switch"]).state == "on"
    assert hass.states.get(link["sensor"]).state == "on"
    _no_fingerprint(result, entry)
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_enregistrement_applique_sans_redemarrage(
    hass: HomeAssistant, folonia: tuple[FakeFolonia, str], hass_ws_client
) -> None:
    fake, _ = folonia
    entry = await _home(hass, folonia)
    client = await hass_ws_client(hass)
    reply = await _ws(
        client,
        type="folonia/save",
        read=["light.cuisine", "sensor.salon"],
        control=["light.cuisine"],
        exempt=[],
        lock_open=True,
        lock_read=True,
    )
    assert reply["success"] is True
    assert entry.options == {
        CONF_READ: ["light.cuisine", "sensor.salon"],
        CONF_CONTROL: ["light.cuisine"],
        CONF_EXEMPT: [],
        CONF_LOCK_OPEN: True,
        CONF_LOCK_READ: True,
    }
    assert reply["result"]["secret_needed"] is False
    await hass.async_block_till_done()
    # La liaison, déjà ouverte, applique les nouveaux réglages à la requête suivante.
    listed = await fake.request("list")
    assert [(e["entity_id"], e["mode"]) for e in listed["entities"]] == [
        ("light.cuisine", "control"),
        ("sensor.salon", "read"),
    ]
    # Une liste absente est gardée ; une protection seule peut changer.
    reply = await _ws(client, type="folonia/save", lock_read=False)
    assert entry.options[CONF_READ] == ["light.cuisine", "sensor.salon"]
    assert entry.options[CONF_LOCK_READ] is False
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_entite_non_permise_ecartee(
    hass: HomeAssistant, folonia: tuple[FakeFolonia, str], hass_ws_client
) -> None:
    entry = await _home(hass, folonia)
    client = await hass_ws_client(hass)
    reply = await _ws(
        client,
        type="folonia/save",
        # Non exposée, inconnue, identifiant de registre, doublon : écartés.
        read=[
            "light.cuisine",
            "switch.cachee",
            "light.inconnue",
            random_uuid_hex(),
            "light.cuisine",
        ],
        # Un capteur ne se commande pas.
        control=["sensor.salon", "cover.garage"],
        # Une lumière ne peut pas être sous code ; la serrure n'est pas partagée.
        exempt=["light.cuisine", "lock.entree", "cover.garage"],
        lock_open=True,
        lock_read=True,
    )
    assert reply["success"] is True
    assert entry.options[CONF_READ] == ["light.cuisine"]
    assert entry.options[CONF_CONTROL] == ["cover.garage"]
    assert entry.options[CONF_EXEMPT] == ["cover.garage"]
    assert _choices(reply["result"])["cover.garage"] == (False, True, True)

    # Plus partagé du tout : l'exemption tombe, il ne reviendrait pas sans code.
    reply = await _ws(client, type="folonia/save", control=[])
    assert entry.options[CONF_EXEMPT] == []
    # Une entité qui perd son exposition disparaît à l'enregistrement suivant.
    async_expose_entity(hass, "conversation", "light.cuisine", False)
    reply = await _ws(client, type="folonia/save", lock_open=True)
    assert entry.options[CONF_READ] == []
    assert "light.cuisine" not in _choices(reply["result"])

    # Ce que la page envoie de travers est refusé par le schéma.
    reply = await _ws(client, type="folonia/save", read="light.cuisine")
    assert reply["success"] is False
    assert reply["error"]["code"] == "invalid_format"
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_secret_necessaire_enregistre_quand_meme(
    hass: HomeAssistant, folonia: tuple[FakeFolonia, str], hass_ws_client
) -> None:
    fake, _ = folonia
    entry = await _home(hass, folonia)
    client = await hass_ws_client(hass)
    # Serrure partagée, protections cochées, aucun secret : enregistré, et la page le dit.
    reply = await _ws(
        client, type="folonia/save", read=["lock.entree"], control=["lock.entree"], exempt=[]
    )
    assert reply["success"] is True
    assert entry.options[CONF_CONTROL] == ["lock.entree"]
    assert reply["result"]["secret_needed"] is True
    await hass.async_block_till_done()
    # D'ici là, Oscar refuse ce qui demande un code.
    refused = await fake.request("command", entity_id="lock.entree", service="lock.unlock", data={})
    assert refused["ok"] is False and refused["error"] == "forbidden"
    # Exemptée, plus rien n'exige de secret.
    reply = await _ws(client, type="folonia/save", exempt=["lock.entree"])
    assert reply["result"]["secret_needed"] is False
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_secrets_regles_et_effaces(
    hass: HomeAssistant, folonia: tuple[FakeFolonia, str], hass_ws_client
) -> None:
    entry = await _home(hass, folonia)
    client = await hass_ws_client(hass)
    await _ws(client, type="folonia/save", read=["lock.entree"], control=["lock.entree"])

    # Une saisie invalide n'enregistre rien, l'autre secret non plus.
    reply = await _ws(client, type="folonia/secret", code="12", phrase="dragon rouge")
    assert reply["success"] is False
    assert reply["error"]["code"] == "invalid_lock_code"
    assert CONF_LOCK_HASH not in entry.options and CONF_PHRASE_HASH not in entry.options
    reply = await _ws(client, type="folonia/secret", phrase="Ah !")
    assert reply["error"]["code"] == "invalid_lock_phrase"

    # Code et mot de passe réglés : les empreintes sont gardées, jamais rendues.
    reply = await _ws(client, type="folonia/secret", code="24 68", phrase="Dragon rouge.")
    assert reply["success"] is True
    result = reply["result"]
    assert result["secrets"] == {"code": True, "phrase": True}
    assert result["secret_needed"] is False
    assert result["weak_phrase"] is False
    assert len(entry.options[CONF_LOCK_HASH]) == 64
    assert len(entry.options[CONF_PHRASE_HASH]) == 64
    assert "2468" not in str(entry.options) and "dragon" not in str(entry.options).casefold()
    _no_fingerprint(result, entry)
    code_hash = entry.options[CONF_LOCK_HASH]

    # Un texte vide garde ce qui est réglé ; un mot de passe court est accepté, déconseillé.
    reply = await _ws(client, type="folonia/secret", code="", phrase="lune")
    assert reply["result"]["weak_phrase"] is True
    assert entry.options[CONF_LOCK_HASH] == code_hash

    # Effacer le mot de passe garde le code ; effacer le dernier, serrure partagée, est refusé.
    reply = await _ws(client, type="folonia/secret", phrase=None)
    assert reply["result"]["secrets"] == {"code": True, "phrase": False}
    assert CONF_PHRASE_HASH not in entry.options and CONF_PHRASE_SALT not in entry.options
    reply = await _ws(client, type="folonia/secret", code=None)
    assert reply["success"] is False
    assert reply["error"]["code"] == "lock_code_required"
    assert entry.options[CONF_LOCK_HASH] == code_hash
    # Rien de protégé : tout peut être effacé.
    await _ws(client, type="folonia/save", read=[], control=[])
    reply = await _ws(client, type="folonia/secret", code=None)
    assert reply["success"] is True
    assert CONF_LOCK_HASH not in entry.options and CONF_LOCK_SALT not in entry.options
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_nouveau_secret_debloque_le_verrou(
    hass: HomeAssistant, folonia: tuple[FakeFolonia, str], hass_ws_client
) -> None:
    lock_hash, lock_salt = hash_code("2468")
    entry = await _home(
        hass,
        folonia,
        {
            CONF_READ: [],
            CONF_CONTROL: ["lock.entree"],
            CONF_LOCK_HASH: lock_hash,
            CONF_LOCK_SALT: lock_salt,
        },
    )
    link = entry.runtime_data
    for _ in range(5):
        link.lock.check("0000")
    client = await hass_ws_client(hass)
    reply = await _ws(client, type="folonia/settings")
    assert reply["result"]["lock"] == {"locked": True, "failures": 5, "max_failures": 5}
    # Enregistrer les mêmes choix ne débloque rien.
    reply = await _ws(client, type="folonia/save", read=["lock.entree"])
    assert reply["result"]["lock"]["locked"] is True
    # Un nouveau code, oui, aussitôt.
    reply = await _ws(client, type="folonia/secret", code="13579")
    assert reply["result"]["lock"] == {"locked": False, "failures": 0, "max_failures": 5}
    await hass.async_block_till_done()
    assert link.lock.check("13579") == "ok"
    assert any(
        line["message"] == "code ou mot de passe du verrou vocal modifié"
        for line in link.journal.entries
    )
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_journal(
    hass: HomeAssistant, folonia: tuple[FakeFolonia, str], hass_ws_client
) -> None:
    entry = await _home(hass, folonia)
    journal = entry.runtime_data.journal
    journal.record("a lu l'état : on", "light.cuisine")
    journal.record("code du verrou vocal refusé", "lock.entree", refused=True)
    client = await hass_ws_client(hass)
    reply = await _ws(client, type="folonia/journal")
    entries = reply["result"]["entries"]
    assert [(e["message"], e["name"], e["refused"]) for e in entries[:2]] == [
        ("code du verrou vocal refusé", "Serrure", True),
        ("a lu l'état : on", "Lumière cuisine", False),
    ]
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_reserve_aux_administrateurs(
    hass: HomeAssistant,
    folonia: tuple[FakeFolonia, str],
    hass_ws_client,
    hass_read_only_access_token: str,
) -> None:
    entry = await _home(hass, folonia)
    options = dict(entry.options)
    client = await hass_ws_client(hass, hass_read_only_access_token)
    for message in (
        {"type": "folonia/settings"},
        {"type": "folonia/save", "read": ["light.cuisine"]},
        {"type": "folonia/secret", "code": None},
        {"type": "folonia/journal"},
    ):
        reply = await _ws(client, **message)
        assert reply["success"] is False
        assert reply["error"]["code"] == "unauthorized"
    assert entry.options == options
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_integration_dechargee(
    hass: HomeAssistant, folonia: tuple[FakeFolonia, str], hass_ws_client
) -> None:
    entry = await _home(hass, folonia)
    assert await hass.config_entries.async_unload(entry.entry_id)
    client = await hass_ws_client(hass)
    reply = await _ws(client, type="folonia/settings")
    assert reply["success"] is False
    assert reply["error"]["code"] == "not_loaded"


# --- Les réglages d'avant 0.5.0, relus et enregistrés par la page ---------------------------


async def _echo(client) -> dict[str, Any]:
    """Ce que la page envoie à « Enregistrer » sans rien changer : lire suit commander."""
    result = (await _ws(client, type="folonia/settings"))["result"]
    devices = result["devices"]
    reply = await _ws(
        client,
        type="folonia/save",
        read=[d["entity_id"] for d in devices if d["read"] or d["control"]],
        control=[d["entity_id"] for d in devices if d["control"]],
        exempt=[d["entity_id"] for d in devices if d["exempt"]],
        **result["protections"],
    )
    assert reply["success"] is True
    return result


def _seen(hass: HomeAssistant, options) -> tuple[list[str], list[str]]:
    """Ce qu'Oscar voit et commande (l'ordre suit la page, triée : il ne compte pas)."""
    return sorted(exposure.allowed(hass, options)), sorted(exposure.allowed_control(hass, options))


async def test_reglages_d_une_installation_0_3(
    hass: HomeAssistant, folonia: tuple[FakeFolonia, str], hass_ws_client
) -> None:
    lock_hash, lock_salt = hash_code("2468")
    # Les options telles que 0.3.0 les a laissées : ni « lock_open », ni exemptions.
    old = {
        CONF_READ: ["light.cuisine"],
        CONF_CONTROL: ["lock.entree"],
        CONF_LOCK_READ: False,
        CONF_LOCK_HASH: lock_hash,
        CONF_LOCK_SALT: lock_salt,
    }
    entry = await _home(hass, folonia, old)
    client = await hass_ws_client(hass)
    before = _seen(hass, entry.options)
    result = await _echo(client)
    assert result["protections"] == {"lock_open": True, "lock_read": False}
    assert result["secrets"] == {"code": True, "phrase": False}
    assert _choices(result)["lock.entree"] == (False, True, False)
    # Enregistré tel quel : le code est gardé, les nouvelles clés prennent leur défaut, et
    # Oscar voit et commande exactement la même chose.
    assert entry.options[CONF_LOCK_HASH] == lock_hash
    assert entry.options[CONF_LOCK_SALT] == lock_salt
    assert entry.options[CONF_LOCK_OPEN] is True
    assert entry.options[CONF_LOCK_READ] is False
    assert entry.options[CONF_EXEMPT] == []
    assert _seen(hass, entry.options) == before
    assert await hass.config_entries.async_unload(entry.entry_id)


@pytest.mark.parametrize("version", ["0.4.0", "0.4.1"])
async def test_reglages_d_une_installation_0_4(
    hass: HomeAssistant, folonia: tuple[FakeFolonia, str], hass_ws_client, version: str
) -> None:
    phrase_hash, phrase_salt = hash_code("dragon rouge")
    # Les options telles que 0.4.0 les écrit d'un coup, et 0.4.1 partie par partie (même forme).
    old = {
        CONF_READ: ["light.cuisine", "cover.garage"],
        CONF_CONTROL: ["lock.entree", "cover.garage"],
        CONF_LOCK_OPEN: True,
        CONF_LOCK_READ: True,
        CONF_EXEMPT: ["cover.garage"],
        CONF_PHRASE_HASH: phrase_hash,
        CONF_PHRASE_SALT: phrase_salt,
    }
    if version == "0.4.1":
        old = {**old, CONF_LOCK_OPEN: False, CONF_EXEMPT: ["cover.garage", "lock.entree"]}
    entry = await _home(hass, folonia, old)
    client = await hass_ws_client(hass)
    before = _seen(hass, entry.options)
    result = await _echo(client)
    assert result["protections"]["lock_open"] is old[CONF_LOCK_OPEN]
    assert result["secrets"] == {"code": False, "phrase": True}
    assert result["secret_needed"] is False
    assert _choices(result)["cover.garage"] == (True, True, True)
    assert entry.options[CONF_PHRASE_HASH] == phrase_hash
    assert entry.options[CONF_LOCK_OPEN] is old[CONF_LOCK_OPEN]
    assert entry.options[CONF_LOCK_READ] is True
    assert entry.options[CONF_EXEMPT] == old[CONF_EXEMPT]
    assert _seen(hass, entry.options) == before
    # Les protections et les exemptions s'appliquent comme avant.
    for entity_id in ("cover.garage", "lock.entree"):
        state = hass.states.get(entity_id)
        assert exposure.read_guarded(state, entry.options) is exposure.read_guarded(state, old)
    assert await hass.config_entries.async_unload(entry.entry_id)
