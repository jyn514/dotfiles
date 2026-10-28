import importlib.util
import json
import random
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
MODULE_PATH = ROOT / "tools/moonlander/layout_format.py"
SPEC = importlib.util.spec_from_file_location("layout_format", MODULE_PATH)
assert SPEC and SPEC.loader
layout_format = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = layout_format
SPEC.loader.exec_module(layout_format)


def action(code, *, layer=None, modifiers=None, macro=None, description=None):
    return {
        "code": code,
        "color": None,
        "description": description,
        "layer": layer,
        "macro": macro,
        "modifier": None,
        "modifiers": modifiers,
    }


def modifiers(*enabled):
    return {
        name: name in enabled
        for name in layout_format.MODIFIER_WRAPPERS
    }


def macro():
    return {
        "applyAlt": False,
        "endEnter": True,
        "keys": [
            {"code": "KC_2", "modifiers": None},
            {"code": "KC_DOT", "delay": 10, "modifiers": modifiers("leftShift")},
            {"code": "KC_TRANSPARENT", "modifiers": None},
        ],
        "name": None,
    }


def snapshot(keys):
    return {
        "schemaVersion": 1,
        "layout": {
            "hashId": "layout-id",
            "geometry": "moonlander",
            "title": "layout",
            "privacy": False,
            "tags": [],
            "revision": {
                "model": "mk1",
                "config": {"tappingTerm": 135},
                "swatch": None,
                "navigators": None,
                "layers": [
                    {
                        "position": 0,
                        "title": "base",
                        "color": "#123456",
                        "automouse": False,
                        "keys": keys,
                    }
                ],
                "combos": [],
            },
        },
    }


def generated_key(kind):
    if kind == "tap":
        return {"tap": action("KC_Q")}
    if kind == "modified-tap":
        return {"tap": action("KC_GRAVE", modifiers=modifiers("leftGui"))}
    if kind == "layer-hold":
        return {"hold": action("MO", layer=2)}
    if kind == "layer-tap":
        return {"tap": action("KC_DELETE"), "hold": action("MO", layer=5)}
    if kind == "mod-tap":
        return {"tap": action("KC_ESCAPE"), "hold": action("KC_LEFT_CTRL")}
    if kind == "macro":
        return {"customLabel": "2>&1", "tap": action("KC_TRANSPARENT", macro=macro())}
    if kind == "tap-dance":
        return {
            "customLabel": "compose/steno",
            "tap": action("KC_SCRL"),
            "doubleTap": action("TO", layer=7),
        }
    if kind == "metadata":
        return {
            "glowColor": "#00ff00",
            "tap": action("KC_Q", description="documented key"),
        }
    if kind == "modified-hold":
        return {
            "tap": action("KC_ESCAPE"),
            "hold": action("KC_LEFT_CTRL", modifiers=modifiers("leftAlt")),
        }
    if kind == "empty":
        return {}
    raise AssertionError(kind)


class LayoutFormatTests(unittest.TestCase):
    def test_repository_snapshot_uses_readable_format(self):
        path = ROOT / "tools/moonlander/moonlander-layout.json"
        readable = json.loads(path.read_text())

        self.assertEqual(readable["schemaVersion"], 2)
        canonical = layout_format.loads(path.read_text())
        self.assertEqual(layout_format.loads(layout_format.dumps(canonical)), canonical)

    def test_generated_supported_keys_round_trip(self):
        rng = random.Random(0x4D4F4F4E)
        kinds = [
            "tap",
            "modified-tap",
            "layer-hold",
            "layer-tap",
            "mod-tap",
            "macro",
            "tap-dance",
            "metadata",
            "modified-hold",
            "empty",
        ]
        exercised = set()

        for case in range(40):
            selected = [rng.choice(kinds) for _ in range(72)]
            selected[: len(kinds)] = kinds
            rng.shuffle(selected)
            exercised.update(selected)
            expected = snapshot([generated_key(kind) for kind in selected])
            with self.subTest(case=case):
                self.assertEqual(
                    layout_format.loads(layout_format.dumps(expected)),
                    expected,
                )

        self.assertEqual(exercised, set(kinds))

    def test_common_behaviors_have_qmk_shaped_keys(self):
        kinds = ["tap", "modified-tap", "layer-hold", "layer-tap", "mod-tap"]
        keys = [generated_key("empty") for _ in range(72)]
        keys[: len(kinds)] = [generated_key(kind) for kind in kinds]

        readable = layout_format.encode(snapshot(keys))
        number_left = readable["layout"]["revision"]["layers"][0]["keys"]["number"]["left"]

        self.assertEqual(
            number_left[:5],
            [
                "KC_Q",
                "LGUI(KC_GRAVE)",
                "MO(2)",
                "LT(5, KC_DELETE)",
                "MT(MOD_LCTL, KC_ESCAPE)",
            ],
        )

    def test_qmk_rows_preserve_the_lower_right_argument_order(self):
        keys = [{"tap": action(f"KC_F{index + 1}")} for index in range(72)]
        readable = layout_format.encode(snapshot(keys))
        lower_right = readable["layout"]["revision"]["layers"][0]["keys"]["lower"]["right"]

        self.assertEqual(
            lower_right,
            ["KC_F69", "KC_F64", "KC_F65", "KC_F66", "KC_F67", "KC_F68"],
        )
        self.assertEqual(layout_format.decode(readable), snapshot(keys))

    def test_rejects_arbitrary_c_syntax(self):
        value = layout_format.encode(snapshot([generated_key("tap") for _ in range(72)]))
        value["layout"]["revision"]["layers"][0]["keys"]["home"]["left"][0] = "KC_Q; reset_keyboard()"

        with self.assertRaisesRegex(layout_format.FormatError, "invalid QMK expression"):
            layout_format.decode(value)


if __name__ == "__main__":
    unittest.main()
