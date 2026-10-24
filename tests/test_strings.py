"""Les chaînes des options : mêmes clés et mêmes repères en anglais et en français."""

from __future__ import annotations

import json
import re
from pathlib import Path

from custom_components.folonia.config_flow import MENU

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


def test_le_menu_et_ses_etapes() -> None:
    for name in FILES:
        options = _load(name)["options"]
        steps = options["step"]
        assert list(steps["init"]["menu_options"]) == list(MENU)
        assert set(steps) == {"init", *MENU}
        assert set(steps["read"]["data"]) == {"read"}
        assert set(steps["control"]["data"]) == {"control"}
        assert set(steps["exempt"]["data"]) == {"exempt"}
        assert set(steps["protections"]["data"]) == {
            "lock_open",
            "lock_read",
            "lock_code",
            "clear_lock_code",
            "lock_phrase",
            "clear_lock_phrase",
        }
        assert set(options["abort"]) == {
            "nothing_exposed",
            "nothing_controllable",
            "nothing_to_exempt",
        }
        assert set(options["error"]) == {
            "invalid_lock_code",
            "invalid_lock_phrase",
            "lock_code_required",
            "secret_needed",
        }
