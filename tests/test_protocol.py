"""Le protocole, sans Home Assistant."""

from __future__ import annotations

import json
import random

from custom_components.folonia import protocol


def test_code_saisi_comme_on_le_lit() -> None:
    assert protocol.normalize_code("k7qm-4xt2") == "K7QM4XT2"
    assert protocol.normalize_code(" K7QM 4XT2 ") == "K7QM4XT2"
    # O lu zéro, I et L lus un : on les confond à la lecture.
    assert protocol.normalize_code("O0IL-ABCD") == "0011ABCD"
    assert protocol.normalize_code("K7QM4XT") is None
    assert protocol.normalize_code("K7QM4XTU") is None


def test_adresses_du_service() -> None:
    assert protocol.base_url("https://folonia.fr/") == "https://folonia.fr"
    assert protocol.base_url("ftp://folonia.fr") is None
    assert protocol.base_url("folonia.fr") is None
    assert protocol.pair_url("https://folonia.fr") == "https://folonia.fr/v1/home/pair"
    assert protocol.link_url("https://folonia.fr") == "wss://folonia.fr/v1/home/link"
    assert protocol.link_url("http://192.168.0.10:8080") == "ws://192.168.0.10:8080/v1/home/link"


def test_reconnexion_avec_delai_croissant_et_borne() -> None:
    rng = random.Random(4)
    delays = [protocol.backoff(attempt, rng) for attempt in range(1, 15)]
    assert 0.5 <= delays[0] <= 1
    assert all(0 < delay <= 300 for delay in delays)
    assert delays[-1] >= 150


def test_fermetures_du_service() -> None:
    assert protocol.outcome_of_close(4000) == "replaced"
    assert protocol.outcome_of_close(4001) == "unlinked"
    assert protocol.outcome_of_close(4002) == "protocol"
    assert protocol.outcome_of_close(4003) == "capacity"
    assert protocol.outcome_of_close(1006) == "lost"
    assert protocol.outcome_of_close(None) == "lost"


def test_requetes_bien_formees_seulement() -> None:
    assert protocol.parse_request('{"type":"request","id":"1","op":"list"}') == protocol.Request(
        "1", "list"
    )
    read = protocol.parse_request(
        '{"type":"request","id":"2","op":"read","entity_ids":["light.cuisine"]}'
    )
    assert read == protocol.Request("2", "read", ("light.cuisine",))
    # Le code vocal à la lecture : facultatif.
    coded = protocol.parse_request(
        '{"type":"request","id":"2","op":"read","entity_ids":["lock.entree"],"code":"2468"}'
    )
    assert coded == protocol.Request("2", "read", ("lock.entree",), code="2468")
    bad_read_code = (
        '{"type":"request","id":"2","op":"read","entity_ids":["lock.entree"],"code":"24"}'
    )
    assert protocol.parse_request(bad_read_code) == protocol.Request("2", "invalid")
    too_many = json.dumps({"type": "request", "id": "3", "op": "read", "entity_ids": ["a.b"] * 21})
    assert protocol.parse_request(too_many) == protocol.Request("3", "invalid")
    command = protocol.parse_request(
        '{"type":"request","id":"4","op":"command","entity_id":"light.cuisine",'
        '"service":"light.turn_on","data":{"brightness_pct":40},"code":"1234"}'
    )
    assert command == protocol.Request(
        "4", "command", (), "light.cuisine", "light.turn_on", {"brightness_pct": 40}, "1234"
    )
    bad_service = '{"type":"request","id":"5","op":"command","entity_id":"a.b","service":"rm -rf"}'
    assert protocol.parse_request(bad_service) == protocol.Request("5", "invalid")
    # Le secret peut être un mot de passe parlé (0.4.0) ; il est vérifié par le verrou.
    phrase = protocol.parse_request(
        '{"type":"request","id":"6","op":"command","entity_id":"lock.entree",'
        '"service":"lock.unlock","code":"Dragon rouge."}'
    )
    assert phrase is not None and phrase.op == "command" and phrase.code == "Dragon rouge."
    # Rien qui ne puisse être un code ou un mot de passe : trop court, sans lettres, trop long,
    # caractère de contrôle, autre chose qu'un texte.
    for code in ("ab", "!!!!", "x" * 129, "drag\u0000on", 2468):
        bad_code = json.dumps(
            {
                "type": "request",
                "id": "6",
                "op": "command",
                "entity_id": "a.b",
                "service": "lock.unlock",
                "code": code,
            }
        )
        assert protocol.parse_request(bad_code) == protocol.Request("6", "invalid"), code
    phrase_read = protocol.parse_request(
        json.dumps(
            {"type": "request", "id": "7", "op": "read", "entity_ids": ["a.b"], "code": "Rémi 2"}
        )
    )
    assert phrase_read == protocol.Request("7", "read", ("a.b",), code="Rémi 2")
    assert protocol.parse_request("pas du JSON") is None
    assert protocol.parse_request('{"type":"welcome","protocol":1}') is None
    assert protocol.is_welcome('{"type":"welcome","protocol":1}')
    assert not protocol.is_welcome('{"type":"welcome","protocol":2}')


def test_ce_qui_sort_de_la_maison_est_borne() -> None:
    entity = protocol.entity_payload("cover.garage", "Porte\ndu   garage", "Garage", "garage")
    assert entity == {
        "entity_id": "cover.garage",
        "name": "Porte du garage",
        "area": "Garage",
        "domain": "cover",
        "device_class": "garage",
        "mode": "read",
    }
    state = protocol.state_payload(
        "light.cuisine",
        "on",
        None,
        {
            "brightness": 204,
            "friendly_name": "Lumière cuisine",
            "entity_picture": "/api/camera_proxy/…",
            "hvac_action": "x" * 100,
            "current_position": True,
        },
        "2026-10-04T07:20:00+00:00",
    )
    assert state["attributes"] == {"brightness": 204, "hvac_action": "x" * 64}
    assert protocol.entity_payload("light.x", "n" * 300, None, None)["name"] == "n" * 100
