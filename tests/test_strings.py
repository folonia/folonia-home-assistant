"""Les chaînes : mêmes clés et mêmes repères en anglais et en français."""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).parent.parent / "custom_components" / "folonia"
FILES = ("strings.json", "translations/en.json", "translations/fr.json")


def _load(name: str) -> dict:
    return json.loads((ROOT / name).read_text(encoding="utf-8"))


def _leaves(tree: dict, prefix: str = "") -> dict[str, str]:
    found: dict[str, str] = {}
    for key, value in tree.items():
        if isinstance(value, dict):
            found.update(_leaves(value, f"{prefix}{key}."))
        else:
            found[f"{prefix}{key}"] = value
    return found


def test_memes_cles_et_memes_reperes() -> None:
    reference = _leaves(_load("strings.json"))
    for name in FILES[1:]:
        leaves = _leaves(_load(name))
        assert leaves.keys() == reference.keys(), name
        for key, text in leaves.items():
            assert set(re.findall(r"\{(\w+)\}", text)) == set(
                re.findall(r"\{(\w+)\}", reference[key])
            ), f"{name} : {key}"


def test_les_options_renvoient_a_la_page() -> None:
    for name in FILES:
        options = _load(name)["options"]
        # hassfest exige `options.step` ; le formulaire n'en montre aucune, il renvoie à la page.
        assert set(options) == {"step", "abort"}
        assert set(options["abort"]) == {"use_panel"}
        assert "({url})" in options["abort"]["use_panel"]
