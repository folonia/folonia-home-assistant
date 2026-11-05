"""La liaison : ce qui sort de la maison, le journal, le coupe-tout, le déliement."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import pytest
from homeassistant.components.homeassistant.exposed_entities import async_expose_entity
from homeassistant.config_entries import SOURCE_REAUTH, ConfigEntryState
from homeassistant.core import Event, HomeAssistant
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import entity_registry as er
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

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
    STATE_SETTLE_DEADLINE,
)
from custom_components.folonia.voicelock import hash_code

from .fake_folonia import LINK_ID, FakeFolonia
from .helpers import entity_id

LOCK_HASH, LOCK_SALT = hash_code("2468")
PHRASE_HASH, PHRASE_SALT = hash_code("dragon rouge")

# Le faux service Folonia écoute sur la boucle locale : le banc de Home Assistant
# ferme les sockets par défaut, on les rouvre pour ce seul fichier.
pytestmark = pytest.mark.enable_socket


@pytest.fixture
async def linked(
    hass: HomeAssistant, folonia: tuple[FakeFolonia, str]
) -> AsyncIterator[tuple[FakeFolonia, MockConfigEntry, list[Event]]]:
    """Une maison reliée, qui montre la lumière de la cuisine et la porte du garage."""
    fake, url = folonia
    assert await async_setup_component(hass, "homeassistant", {})
    kitchen = ar.async_get(hass).async_create("Cuisine", aliases={"Coin repas"})
    registry = er.async_get(hass)
    light = registry.async_get_or_create("light", "test", "cuisine", suggested_object_id="cuisine")
    # Les alias d'Assist ; celui qui redit le nom ne sert à rien et ne sort pas.
    registry.async_update_entity(
        light.entity_id, area_id=kitchen.id, aliases={"Plafonnier", "lumière  CUISINE"}
    )

    hass.states.async_set(
        "light.cuisine", "on", {"friendly_name": "Lumière cuisine", "brightness": 204}
    )
    hass.states.async_set(
        "cover.garage",
        "closed",
        {"friendly_name": "Porte du garage", "device_class": "garage", "current_position": 0},
    )
    hass.states.async_set("lock.entree", "locked", {"friendly_name": "Serrure"})
    for exposed in ("light.cuisine", "cover.garage", "lock.entree"):
        async_expose_entity(hass, "conversation", exposed, True)

    logbook: list[Event] = []
    hass.bus.async_listen("logbook_entry", logbook.append)

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_URL: url,
            CONF_VERIFY_SSL: True,
            CONF_LINK_ID: LINK_ID,
            CONF_SECRET: fake.link_secret(),
        },
        # La serrure est exposée à Assist mais pas cochée : Oscar ne la voit pas. Les options
        # sont celles d'une installation 0.3.0 : ni « lock_open » ni exemptions, qui valent
        # alors leur défaut (protections cochées, aucune exemption).
        options={
            CONF_READ: ["light.cuisine", "cover.garage"],
            CONF_CONTROL: [],
            CONF_LOCK_HASH: LOCK_HASH,
            CONF_LOCK_SALT: LOCK_SALT,
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await fake.connected.wait()
    yield fake, entry, logbook
    if entry.state is ConfigEntryState.LOADED:
        assert await hass.config_entries.async_unload(entry.entry_id)


async def test_ne_montre_que_ce_qui_est_coche_et_expose(
    hass: HomeAssistant, linked: tuple[FakeFolonia, MockConfigEntry, list[Event]]
) -> None:
    fake, _, logbook = linked
    listed = await fake.request("list")
    assert listed["ok"] is True
    assert listed["entities"] == [
        {
            "entity_id": "light.cuisine",
            "name": "Lumière cuisine",
            "area": "Cuisine",
            "domain": "light",
            "device_class": None,
            "mode": "read",
            "aliases": ["Plafonnier"],
            "area_aliases": ["Coin repas"],
        },
        {
            "entity_id": "cover.garage",
            "name": "Porte du garage",
            "area": None,
            "domain": "cover",
            "device_class": "garage",
            "mode": "read",
            "aliases": [],
            "area_aliases": [],
        },
    ]

    # Installation d'avant `lock_read` : la case vaut cochée. La porte du garage est
    # sensible : sans code, un marqueur à la place de son état ; la lumière, elle, est lue.
    read = await fake.request("read", entity_ids=["cover.garage", "lock.entree", "light.cuisine"])
    assert [s["entity_id"] for s in read["states"]] == ["light.cuisine"]
    assert read["states"][0]["attributes"] == {"brightness": 204}
    assert read["withheld"] == [{"entity_id": "cover.garage", "reason": "code_required"}]

    read = await fake.request("read", entity_ids=["cover.garage", "light.cuisine"], code="2468")
    assert [s["entity_id"] for s in read["states"]] == ["cover.garage", "light.cuisine"]
    assert read["states"][0]["state"] == "closed"
    assert read["states"][0]["attributes"] == {"current_position": 0}
    assert "withheld" not in read

    # Retirer l'exposition à Assist retire aussi l'entité à Oscar, à la requête suivante.
    async_expose_entity(hass, "conversation", "cover.garage", False)
    again = await fake.request("read", entity_ids=["cover.garage"])
    assert again == {"type": "response", "id": again["id"], "ok": True, "states": []}

    await hass.async_block_till_done()
    messages = [(e.data.get("entity_id"), e.data["message"]) for e in logbook]
    assert (None, "a consulté la liste des appareils partagés (2)") in messages
    assert ("cover.garage", "lecture sous code vocal : code demandé") in messages
    assert ("cover.garage", "a lu l'état : closed") in messages
    assert ("light.cuisine", "a lu l'état : on") in messages
    assert all(e.data["name"] == "Oscar" for e in logbook)
    assert not any(entity == "lock.entree" for entity, _ in messages)


async def test_alias_relus_a_chaque_liste(
    hass: HomeAssistant, linked: tuple[FakeFolonia, MockConfigEntry, list[Event]]
) -> None:
    fake, _, _ = linked
    registry = er.async_get(hass)
    # Changés dans Home Assistant (ou dans la page) : Oscar les a à la liste suivante.
    registry.async_update_entity("light.cuisine", aliases={"Lustre", "Suspension"})
    areas = ar.async_get(hass)
    kitchen = areas.async_get_area_by_name("Cuisine")
    assert kitchen is not None
    areas.async_update(kitchen.id, aliases=set())
    listed = await fake.request("list")
    light = listed["entities"][0]
    assert (light["aliases"], light["area_aliases"]) == (["Lustre", "Suspension"], [])


async def test_commande_sur_les_seuls_appareils_coches_en_commande(
    hass: HomeAssistant, linked: tuple[FakeFolonia, MockConfigEntry, list[Event]]
) -> None:
    fake, entry, logbook = linked
    calls: list[tuple[str, str, dict]] = []

    async def record(call) -> None:
        calls.append((call.domain, call.service, dict(call.data)))
        if call.domain == "light":
            hass.states.async_set("light.cuisine", "off", {"friendly_name": "Lumière cuisine"})
        if call.domain == "lock":
            after = "unlocked" if call.service == "unlock" else "locked"
            hass.states.async_set("lock.entree", after, {"friendly_name": "Serrure"})

    for domain, service in (
        ("light", "turn_off"),
        ("light", "turn_on"),
        ("lock", "unlock"),
        ("lock", "lock"),
    ):
        hass.services.async_register(domain, service, record)

    # Cochée en lecture seulement : refusée, et la tentative est au journal.
    refused = await fake.request(
        "command", entity_id="light.cuisine", service="light.turn_off", data={}
    )
    assert refused["ok"] is False and refused["error"] == "forbidden"
    assert calls == []

    hass.config_entries.async_update_entry(
        entry, options={**entry.options, CONF_CONTROL: ["light.cuisine", "lock.entree"]}
    )
    await hass.async_block_till_done()
    listed = await fake.request("list")
    assert {e["entity_id"]: e["mode"] for e in listed["entities"]} == {
        "light.cuisine": "control",
        "cover.garage": "read",
        "lock.entree": "control",
    }

    done = await fake.request(
        "command", entity_id="light.cuisine", service="light.turn_off", data={}
    )
    assert done["ok"] is True
    assert done["result"]["entity_id"] == "light.cuisine"
    assert done["result"]["state"] == "off"
    assert calls == [("light", "turn_off", {"entity_id": "light.cuisine"})]

    # Un service hors liste, une donnée hors bornes : rien ne passe.
    bad = await fake.request("command", entity_id="light.cuisine", service="light.explode", data={})
    assert bad["error"] == "forbidden"
    bad = await fake.request(
        "command", entity_id="light.cuisine", service="light.turn_on", data={"brightness_pct": 400}
    )
    assert bad["error"] == "bad_request"
    bad = await fake.request(
        "command", entity_id="light.cuisine", service="light.turn_on", data={"effect": "x"}
    )
    assert bad["error"] == "bad_request"
    assert len(calls) == 1

    # Verrouiller passe sans code ; l'état de la serrure, sensible, ne sort pas sans code.
    locked_now = await fake.request("command", entity_id="lock.entree", service="lock.lock")
    assert locked_now == {"type": "response", "id": locked_now["id"], "ok": True}
    assert calls[-1] == ("lock", "lock", {"entity_id": "lock.entree"})

    # La serrure : le code d'abord, puis le bon code ; les faux sont comptés, le cinquième bloque.
    assert (await fake.request("command", entity_id="lock.entree", service="lock.unlock"))[
        "error"
    ] == "code_required"
    for _ in range(4):
        wrong = await fake.request(
            "command", entity_id="lock.entree", service="lock.unlock", code="0000"
        )
        assert wrong["error"] == "code_invalid"
    ok = await fake.request("command", entity_id="lock.entree", service="lock.unlock", code="2468")
    assert ok["ok"] is True and ok["result"]["state"] == "unlocked"
    assert calls[-1] == ("lock", "unlock", {"entity_id": "lock.entree"})
    for _ in range(5):
        wrong = await fake.request(
            "command", entity_id="lock.entree", service="lock.unlock", code="0000"
        )
    assert wrong["error"] == "locked"
    locked = await fake.request(
        "command", entity_id="lock.entree", service="lock.unlock", code="2468"
    )
    assert locked["error"] == "locked"
    await hass.async_block_till_done()
    assert any("verrou vocal bloqué" in e.data["message"] for e in logbook)

    # Rallumer « Accès d'Oscar » débloque.
    access = entity_id(hass, entry, "switch", "access")
    await hass.services.async_call("switch", "turn_off", {"entity_id": access}, blocking=True)
    await fake.disconnected.wait()
    await hass.services.async_call("switch", "turn_on", {"entity_id": access}, blocking=True)
    await fake.connected.wait()
    again = await fake.request(
        "command", entity_id="lock.entree", service="lock.unlock", code="2468"
    )
    assert again["ok"] is True

    await hass.async_block_till_done()
    messages = [(e.data.get("entity_id"), e.data["message"]) for e in logbook]
    assert ("light.cuisine", "a tenté une commande sur un appareil non commandable") in messages
    assert ("light.cuisine", "a commandé : turn_off → off") in messages
    assert ("lock.entree", "code du verrou vocal refusé") in messages
    assert ("lock.entree", "a commandé : unlock → unlocked") in messages
    assert not any("2468" in m or "0000" in m for _, m in messages)


async def test_requete_mal_formee(
    hass: HomeAssistant, linked: tuple[FakeFolonia, MockConfigEntry, list[Event]]
) -> None:
    fake, _, _ = linked
    reply = await fake.request("read", entity_ids=[])
    assert reply == {"type": "response", "id": reply["id"], "ok": False, "error": "bad_request"}


async def test_portes_seule_l_ouverture_sous_code(
    hass: HomeAssistant, linked: tuple[FakeFolonia, MockConfigEntry, list[Event]]
) -> None:
    fake, entry, _ = linked
    calls: list[tuple[str, dict]] = []

    async def record(call) -> None:
        calls.append((call.service, dict(call.data)))

    for service in ("open_cover", "close_cover", "stop_cover", "set_cover_position"):
        hass.services.async_register("cover", service, record)
    hass.config_entries.async_update_entry(
        entry, options={**entry.options, CONF_CONTROL: ["cover.garage"]}
    )
    await hass.async_block_till_done()

    async def command(service: str, **extra) -> dict:
        return await fake.request("command", entity_id="cover.garage", service=service, **extra)

    # Fermer, arrêter, position zéro : sans code.
    assert (await command("cover.close_cover"))["ok"] is True
    assert (await command("cover.stop_cover"))["ok"] is True
    zero = await command("cover.set_cover_position", data={"position": 0})
    assert zero["ok"] is True
    # Ouvrir, même à moitié : le code.
    assert (await command("cover.open_cover"))["error"] == "code_required"
    half = await command("cover.set_cover_position", data={"position": 30})
    assert half["error"] == "code_required"
    opened = await command("cover.open_cover", code="2468")
    assert opened["ok"] is True and opened["result"]["entity_id"] == "cover.garage"
    assert [service for service, _ in calls] == [
        "close_cover",
        "stop_cover",
        "set_cover_position",
        "open_cover",
    ]


async def test_lecture_sous_code_compte_les_codes_faux(
    hass: HomeAssistant, linked: tuple[FakeFolonia, MockConfigEntry, list[Event]]
) -> None:
    fake, entry, logbook = linked
    # Une question sans entité sensible ne réclame rien, et un code faux n'y compte pas.
    plain = await fake.request("read", entity_ids=["light.cuisine"], code="0000")
    assert plain["states"][0]["state"] == "on" and "withheld" not in plain
    assert len(entry.runtime_data.lock.failures) == 0

    for _ in range(4):
        wrong = await fake.request("read", entity_ids=["cover.garage"], code="0000")
        assert wrong["states"] == []
        assert wrong["withheld"] == [{"entity_id": "cover.garage", "reason": "code_invalid"}]
    wrong = await fake.request("read", entity_ids=["cover.garage"], code="0000")
    assert wrong["withheld"] == [{"entity_id": "cover.garage", "reason": "locked"}]
    # Bloqué : même le bon code n'ouvre plus rien, en lecture comme en commande.
    good = await fake.request("read", entity_ids=["cover.garage"], code="2468")
    assert good["withheld"] == [{"entity_id": "cover.garage", "reason": "locked"}]
    hass.config_entries.async_update_entry(
        entry, options={**entry.options, CONF_CONTROL: ["lock.entree"]}
    )
    await hass.async_block_till_done()
    refused = await fake.request(
        "command", entity_id="lock.entree", service="lock.unlock", code="2468"
    )
    assert refused["error"] == "locked"
    await hass.async_block_till_done()
    messages = [(e.data.get("entity_id"), e.data["message"]) for e in logbook]
    assert ("cover.garage", "code du verrou vocal refusé") in messages
    assert any("verrou vocal bloqué" in m for _, m in messages)
    assert not any("2468" in m or "0000" in m for _, m in messages)


async def test_lecture_libre_case_decochee_ou_sans_code_regle(
    hass: HomeAssistant, linked: tuple[FakeFolonia, MockConfigEntry, list[Event]]
) -> None:
    fake, entry, _ = linked
    hass.config_entries.async_update_entry(entry, options={**entry.options, CONF_LOCK_READ: False})
    await hass.async_block_till_done()
    read = await fake.request("read", entity_ids=["cover.garage"])
    assert read["states"][0]["state"] == "closed" and "withheld" not in read

    # Case cochée mais aucun code réglé (installation ancienne) : rien ne sort, et Oscar le sait.
    options = {k: v for k, v in entry.options.items() if k not in (CONF_LOCK_HASH, CONF_LOCK_SALT)}
    hass.config_entries.async_update_entry(entry, options={**options, CONF_LOCK_READ: True})
    await hass.async_block_till_done()
    read = await fake.request("read", entity_ids=["cover.garage"], code="2468")
    assert read["states"] == []
    assert read["withheld"] == [{"entity_id": "cover.garage", "reason": "code_not_set"}]


async def test_interrupteur_coupe_tout(
    hass: HomeAssistant, linked: tuple[FakeFolonia, MockConfigEntry, list[Event]]
) -> None:
    fake, entry, _ = linked
    access = entity_id(hass, entry, "switch", "access")
    link = entity_id(hass, entry, "binary_sensor", "link")
    await hass.services.async_call("switch", "turn_off", {"entity_id": access}, blocking=True)
    await fake.disconnected.wait()
    assert {"type": "bye", "reason": "paused"} in fake.received
    assert hass.states.get(access).state == "off"
    await hass.async_block_till_done()
    assert hass.states.get(link).state == "off"

    await hass.services.async_call("switch", "turn_on", {"entity_id": access}, blocking=True)
    await fake.connected.wait()
    assert hass.states.get(access).state == "on"


async def test_deliee_par_folonia_demande_un_nouveau_code(
    hass: HomeAssistant, linked: tuple[FakeFolonia, MockConfigEntry, list[Event]]
) -> None:
    fake, entry, _ = linked
    await fake.close_link(4001)
    await fake.disconnected.wait()
    # La liaison tourne en tâche de fond, que `async_block_till_done` n'attend pas : elle
    # peut voir la fermeture un peu après le faux service.
    for _ in range(100):
        if entry.runtime_data.stopped_reason is not None:
            break
        await asyncio.sleep(0.01)
    await hass.async_block_till_done()
    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert [flow["context"]["source"] for flow in flows] == [SOURCE_REAUTH]
    assert entry.runtime_data.stopped_reason == "unlinked"


async def test_retirer_l_integration_delie_la_maison(
    hass: HomeAssistant, linked: tuple[FakeFolonia, MockConfigEntry, list[Event]]
) -> None:
    fake, entry, _ = linked
    secret = entry.data[CONF_SECRET]
    assert await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()
    assert fake.unlinked == [secret]


async def test_commande_attend_l_etat_de_l_appareil(
    hass: HomeAssistant, linked: tuple[FakeFolonia, MockConfigEntry, list[Event]]
) -> None:
    """Essai du 5 novembre 2026 : « indiqué éteint, mais l'état affiché dit encore allumé »."""
    fake, entry, _ = linked
    hass.config_entries.async_update_entry(
        entry, options={**entry.options, CONF_CONTROL: ["light.cuisine", "lock.entree"]}
    )
    await hass.async_block_till_done()

    async def plus_tard(call) -> None:
        # Le service répond tout de suite ; l'appareil, un instant après.
        hass.loop.call_later(
            0.15,
            hass.states.async_set,
            "light.cuisine",
            "off",
            {"friendly_name": "Lumière cuisine"},
        )

    async def sans_effet(call) -> None:
        pass

    hass.services.async_register("light", "turn_off", plus_tard)
    done = await fake.request(
        "command", entity_id="light.cuisine", service="light.turn_off", data={}
    )
    assert done["ok"] is True
    assert done["result"]["state"] == "off"

    # Déjà dans cet état, ou muet : la réponse vient quand même, à la limite de l'attente.
    hass.services.async_register("light", "turn_on", sans_effet)
    before = hass.loop.time()
    done = await fake.request(
        "command", entity_id="light.cuisine", service="light.turn_on", data={}
    )
    assert done["ok"] is True
    assert done["result"]["state"] == "off"
    assert hass.loop.time() - before < STATE_SETTLE_DEADLINE + 0.5

    # En route, puis arrivé : c'est l'arrivée qui est dite, si elle vient dans l'attente.
    async def en_route(call) -> None:
        hass.states.async_set("lock.entree", "locking", {"friendly_name": "Serrure"})
        hass.loop.call_later(
            0.15, hass.states.async_set, "lock.entree", "locked", {"friendly_name": "Serrure"}
        )

    hass.services.async_register("lock", "lock", en_route)
    done = await fake.request("command", entity_id="lock.entree", service="lock.lock", data={})
    assert done["ok"] is True
    assert hass.states.get("lock.entree").state == "locked"


async def _cover_services(hass: HomeAssistant) -> list[str]:
    calls: list[str] = []

    async def record(call) -> None:
        calls.append(f"{call.domain}.{call.service}")
        if call.domain == "lock":
            after = "unlocked" if call.service == "unlock" else "locked"
            hass.states.async_set("lock.entree", after, {"friendly_name": "Serrure"})

    for service in ("open_cover", "close_cover"):
        hass.services.async_register("cover", service, record)
    for service in ("lock", "unlock"):
        hass.services.async_register("lock", service, record)
    return calls


async def test_ouvrir_sans_code_case_decochee(
    hass: HomeAssistant, linked: tuple[FakeFolonia, MockConfigEntry, list[Event]]
) -> None:
    fake, entry, _ = linked
    calls = await _cover_services(hass)
    hass.config_entries.async_update_entry(
        entry,
        options={**entry.options, CONF_CONTROL: ["lock.entree"], CONF_LOCK_OPEN: False},
    )
    await hass.async_block_till_done()
    # Décoché par l'utilisateur : déverrouiller passe sans code. L'état de la serrure,
    # sensible, reste sous code tant que « lock_read » est coché.
    done = await fake.request("command", entity_id="lock.entree", service="lock.unlock")
    assert done == {"type": "response", "id": done["id"], "ok": True}
    assert calls == ["lock.unlock"]
    read = await fake.request("read", entity_ids=["lock.entree"])
    assert read["withheld"] == [{"entity_id": "lock.entree", "reason": "code_required"}]
    # Un code dit quand même ne gêne pas, et un code faux n'y compte pas.
    again = await fake.request(
        "command", entity_id="lock.entree", service="lock.unlock", code="0000"
    )
    assert again["ok"] is True
    assert len(entry.runtime_data.lock.failures) == 0


async def test_appareil_exempte_lu_et_ouvert_sans_code(
    hass: HomeAssistant, linked: tuple[FakeFolonia, MockConfigEntry, list[Event]]
) -> None:
    fake, entry, logbook = linked
    calls = await _cover_services(hass)
    hass.config_entries.async_update_entry(
        entry,
        options={
            **entry.options,
            CONF_CONTROL: ["cover.garage", "lock.entree"],
            CONF_EXEMPT: ["cover.garage"],
        },
    )
    await hass.async_block_till_done()
    # « J'ai bien fermé le garage ? » sans code, cases cochées.
    read = await fake.request("read", entity_ids=["cover.garage", "lock.entree"])
    assert [s["entity_id"] for s in read["states"]] == ["cover.garage"]
    assert read["states"][0]["state"] == "closed"
    assert read["withheld"] == [{"entity_id": "lock.entree", "reason": "code_required"}]
    opened = await fake.request("command", entity_id="cover.garage", service="cover.open_cover")
    assert opened["ok"] is True and opened["result"]["entity_id"] == "cover.garage"
    # La serrure, non exemptée, reste sous code.
    refused = await fake.request("command", entity_id="lock.entree", service="lock.unlock")
    assert refused["error"] == "code_required"
    assert calls == ["cover.open_cover"]
    await hass.async_block_till_done()
    messages = [(e.data.get("entity_id"), e.data["message"]) for e in logbook]
    assert ("cover.garage", "a lu l'état : closed") in messages


async def test_mot_de_passe_parle_et_essais_faux_comptes_ensemble(
    hass: HomeAssistant, linked: tuple[FakeFolonia, MockConfigEntry, list[Event]]
) -> None:
    fake, entry, logbook = linked
    calls = await _cover_services(hass)
    hass.config_entries.async_update_entry(
        entry,
        options={
            **entry.options,
            CONF_CONTROL: ["lock.entree"],
            CONF_PHRASE_HASH: PHRASE_HASH,
            CONF_PHRASE_SALT: PHRASE_SALT,
        },
    )
    await hass.async_block_till_done()
    # Le mot de passe tel que le modèle le transcrit, ou le code : l'un ou l'autre suffit.
    read = await fake.request("read", entity_ids=["cover.garage"], code="Dragon. Rouge !")
    assert read["states"][0]["state"] == "closed" and "withheld" not in read
    done = await fake.request(
        "command", entity_id="lock.entree", service="lock.unlock", code="dragon rouge"
    )
    assert done["ok"] is True and done["result"]["state"] == "unlocked"
    done = await fake.request(
        "command", entity_id="lock.entree", service="lock.unlock", code="2468"
    )
    assert done["ok"] is True

    # Codes et mots de passe faux, en lecture comme en commande, comptent ensemble.
    wrong = await fake.request("read", entity_ids=["cover.garage"], code="dragon bleu")
    assert wrong["withheld"] == [{"entity_id": "cover.garage", "reason": "code_invalid"}]
    for code in ("0000", "chat noir", "1111"):
        wrong = await fake.request(
            "command", entity_id="lock.entree", service="lock.unlock", code=code
        )
        assert wrong["error"] == "code_invalid"
    wrong = await fake.request(
        "command", entity_id="lock.entree", service="lock.unlock", code="dragon vert"
    )
    assert wrong["error"] == "locked"
    good = await fake.request(
        "command", entity_id="lock.entree", service="lock.unlock", code="dragon rouge"
    )
    assert good["error"] == "locked"
    assert calls == ["lock.unlock", "lock.unlock"]

    # Effacer le mot de passe change le verrou : il est débloqué, le code chiffré reste.
    options = {
        k: v for k, v in entry.options.items() if k not in (CONF_PHRASE_HASH, CONF_PHRASE_SALT)
    }
    hass.config_entries.async_update_entry(entry, options=options)
    await hass.async_block_till_done()
    assert not entry.runtime_data.lock.is_locked()
    gone = await fake.request("read", entity_ids=["cover.garage"], code="dragon rouge")
    assert gone["withheld"] == [{"entity_id": "cover.garage", "reason": "code_invalid"}]
    await hass.async_block_till_done()
    messages = [m for _, m in ((e.data.get("entity_id"), e.data["message"]) for e in logbook)]
    assert "code ou mot de passe du verrou vocal modifié" in messages
    assert not any("dragon" in m.lower() or "2468" in m for m in messages)
