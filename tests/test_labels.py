"""Libellés de la liste des appareils : nature et valeur du moment, en français."""

from homeassistant.core import State

from custom_components.folonia.exposure import kind_label, value_label


def test_kind_follows_device_class_then_domain() -> None:
    assert (
        kind_label(State("binary_sensor.garage", "off", {"device_class": "garage_door"}))
        == "porte de garage"
    )
    assert (
        kind_label(State("sensor.salon", "21.5", {"device_class": "temperature"})) == "température"
    )
    assert kind_label(State("light.cuisine", "on")) == "lumière"
    assert kind_label(State("foo.bar", "x")) == "foo"


def test_value_speaks_french() -> None:
    assert (
        value_label(State("binary_sensor.garage", "off", {"device_class": "garage_door"}))
        == "fermé"
    )
    assert (
        value_label(State("binary_sensor.couloir", "on", {"device_class": "motion"})) == "détecté"
    )
    assert value_label(State("light.cuisine", "on")) == "allumé"
    assert value_label(State("lock.entree", "locked")) == "verrouillé"
    assert value_label(State("sensor.salon", "21.5", {"unit_of_measurement": "°C"})) == "21,5 °C"
    assert value_label(State("sensor.pile", "42", {"unit_of_measurement": "%"})) == "42 %"
    assert value_label(State("sensor.texte", "pluie")) == "pluie"
