"""Readable on-disk representation for a canonical Oryx Moonlander layout."""

from __future__ import annotations

import copy
import json
import re
from typing import Any


SCHEMA_VERSION = 2
SCHEMA_PATH = "./layout.schema.json"
ROW_INDICES = {
    "number": (list(range(0, 7)), list(range(36, 43))),
    "top": (list(range(7, 14)), list(range(43, 50))),
    "home": (list(range(14, 21)), list(range(50, 57))),
    "bottom": (list(range(21, 27)), list(range(57, 63))),
    # This is the argument order of QMK's LAYOUT_moonlander macro. The first
    # right key on this row is the upper thumb key, not Oryx key 63.
    "lower": (list(range(27, 33)), [68, 63, 64, 65, 66, 67]),
    "thumb": (list(range(33, 36)), list(range(69, 72))),
}
KEY_METADATA = {
    "customLabel": "label",
    "glowColor": "glow",
    "lockGlowColor": "lockGlow",
    "tappingTerm": "tappingTerm",
    "icon": "icon",
    "emoji": "emoji",
}
METADATA_KEYS = {readable: oryx for oryx, readable in KEY_METADATA.items()}
MODIFIER_WRAPPERS = {
    "leftAlt": "LALT",
    "leftCtrl": "LCTL",
    "leftGui": "LGUI",
    "leftShift": "LSFT",
    "rightAlt": "RALT",
    "rightCtrl": "RCTL",
    "rightGui": "RGUI",
    "rightShift": "RSFT",
}
WRAPPER_MODIFIERS = {wrapper: modifier for modifier, wrapper in MODIFIER_WRAPPERS.items()}
HOLD_MODIFIERS = {
    "KC_LEFT_ALT": "MOD_LALT",
    "KC_LEFT_CTRL": "MOD_LCTL",
    "KC_LEFT_GUI": "MOD_LGUI",
    "KC_LEFT_SHIFT": "MOD_LSFT",
    "KC_RIGHT_ALT": "MOD_RALT",
    "KC_RIGHT_CTRL": "MOD_RCTL",
    "KC_RIGHT_GUI": "MOD_RGUI",
    "KC_RIGHT_SHIFT": "MOD_RSFT",
}
MODIFIER_HOLDS = {modifier: key for key, modifier in HOLD_MODIFIERS.items()}
LAYER_ACTIONS = {"MO", "TO", "TG"}
TOKEN = re.compile(r"^[A-Z][A-Z0-9_]*$")
CALL = re.compile(r"^([A-Z][A-Z0-9_]*)\((.*)\)$")


class FormatError(ValueError):
    pass


def _reject_unknown(value: Any, allowed: set[str], context: str) -> None:
    if not isinstance(value, dict):
        raise FormatError(f"{context} must be an object")
    unknown = set(value) - allowed
    if unknown:
        raise FormatError(f"unknown {context} fields: {', '.join(sorted(unknown))}")


def _stable(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _stable(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        return [_stable(item) for item in value]
    return copy.deepcopy(value)


def _empty_modifiers() -> dict[str, bool]:
    return {name: False for name in MODIFIER_WRAPPERS}


def _canonical_modifiers(modifiers: dict[str, bool] | None) -> dict[str, bool] | None:
    if not modifiers or not any(modifiers.values()):
        return None
    return {name: bool(modifiers.get(name)) for name in MODIFIER_WRAPPERS}


def _canonical_action(action: dict[str, Any]) -> dict[str, Any]:
    return {
        "code": action.get("code"),
        "color": action.get("color"),
        "description": action.get("description"),
        "layer": action.get("layer"),
        "macro": _canonical_macro(action.get("macro")),
        "modifier": action.get("modifier"),
        "modifiers": _canonical_modifiers(action.get("modifiers")),
    }


def _canonical_macro(macro: dict[str, Any] | None) -> dict[str, Any] | None:
    if macro is None:
        return None
    return {
        "applyAlt": bool(macro.get("applyAlt")),
        "endEnter": bool(macro.get("endEnter")),
        "keys": [
            {
                "code": step.get("code"),
                **({"delay": step["delay"]} if step.get("delay") is not None else {}),
                "modifiers": _canonical_modifiers(step.get("modifiers")),
            }
            for step in macro.get("keys", [])
        ],
        "name": macro.get("name"),
    }


def canonical_key(key: dict[str, Any]) -> dict[str, Any]:
    result = {
        field: copy.deepcopy(key[field])
        for field in KEY_METADATA
        if field in key and key[field] is not None
    }
    for field in ("tap", "hold", "doubleTap", "tapHold"):
        if key.get(field) is not None:
            result[field] = _canonical_action(key[field])
    return result


def _action_token(action: dict[str, Any]) -> str:
    action = _canonical_action(action)
    if action["macro"] is not None:
        raise FormatError("macro action needs a named macro definition")
    if action["modifier"] is not None:
        raise FormatError("legacy modifier actions are not supported")
    code = action["code"]
    if not isinstance(code, str) or not TOKEN.fullmatch(code):
        raise FormatError(f"invalid QMK keycode {code!r}")
    layer = action["layer"]
    if layer is not None:
        if code not in LAYER_ACTIONS or not isinstance(layer, int):
            raise FormatError(f"unsupported layer action {code}({layer!r})")
        token = f"{code}({layer})"
    else:
        token = code
    modifiers = action["modifiers"]
    if modifiers is not None:
        unknown = set(modifiers) - set(MODIFIER_WRAPPERS)
        if unknown:
            raise FormatError(f"unknown modifiers: {', '.join(sorted(unknown))}")
        for modifier, wrapper in MODIFIER_WRAPPERS.items():
            if modifiers.get(modifier):
                token = f"{wrapper}({token})"
    return token


def _simple_key_token(key: dict[str, Any]) -> str | None:
    tap = key.get("tap")
    hold = key.get("hold")
    if key.get("doubleTap") is not None or key.get("tapHold") is not None:
        return None
    if tap is not None and tap.get("macro") is not None:
        return None
    if hold is not None and hold.get("macro") is not None:
        return None
    if tap is None and hold is None:
        return "KC_NO"
    if tap is not None and hold is None:
        return _action_token(tap)
    if tap is None and hold is not None:
        hold_token = _action_token(hold)
        if hold.get("code") == "MO" and not any((hold.get("modifiers") or {}).values()):
            return hold_token
        modifier = HOLD_MODIFIERS.get(hold.get("code"))
        if modifier is not None and not any((hold.get("modifiers") or {}).values()):
            return f"MT({modifier}, KC_NO)"
        return None
    if hold.get("code") == "MO" and hold.get("layer") is not None and not any(
        (hold.get("modifiers") or {}).values()
    ):
        return f"LT({hold['layer']}, {_action_token(tap)})"
    modifier = HOLD_MODIFIERS.get(hold.get("code"))
    if modifier is not None and not any((hold.get("modifiers") or {}).values()):
        return f"MT({modifier}, {_action_token(tap)})"
    return None


def _macro_definition(action: dict[str, Any]) -> dict[str, Any]:
    macro = _canonical_macro(action.get("macro"))
    if macro is None:
        raise FormatError("macro definition has no macro")
    steps = list(macro["keys"])
    original_size = len(steps)
    while steps and steps[-1].get("code") == "KC_TRANSPARENT" and not any(
        (steps[-1].get("modifiers") or {}).values()
    ) and steps[-1].get("delay") is None:
        steps.pop()
    readable_steps: list[str | dict[str, Any]] = []
    for step in steps:
        token = _action_token(
            {
                "code": step.get("code"),
                "modifiers": step.get("modifiers"),
            }
        )
        if step.get("delay") is None:
            readable_steps.append(token)
        else:
            readable_steps.append({"key": token, "delay": step["delay"]})
    result: dict[str, Any] = {"keys": readable_steps}
    if original_size != 5:
        result["size"] = original_size
    if macro["applyAlt"]:
        result["applyAlt"] = True
    if macro["endEnter"]:
        result["endEnter"] = True
    return result


def _slot(
    key: dict[str, Any],
    layer_name: str,
    index: int,
    macros: dict[str, Any],
    tap_dances: dict[str, Any],
) -> str | dict[str, Any]:
    key = canonical_key(key)
    action_metadata = {
        field: {
            name: key[field][name]
            for name in ("color", "description")
            if key[field].get(name) is not None
        }
        for field in ("tap", "hold", "doubleTap", "tapHold")
        if key.get(field) is not None
        and any(key[field].get(name) is not None for name in ("color", "description"))
    }
    token = _simple_key_token(key)
    if token is None:
        name = f"{_identifier(layer_name)}_{index:02d}"
        if name in macros or name in tap_dances:
            raise FormatError(f"duplicate custom behavior name {name}")
        if all(
            key.get(field, {}).get("macro") is None
            for field in ("tap", "hold", "doubleTap", "tapHold")
        ):
            actions = {
                readable: _action_token(key[oryx])
                for oryx, readable in (
                    ("tap", "tap"),
                    ("hold", "hold"),
                    ("doubleTap", "doubleTap"),
                    ("tapHold", "tapHold"),
                )
                if key.get(oryx) is not None
            }
            tap_dances[name] = actions
            token = f"TD({name})"
        elif key.get("tap", {}).get("macro") is not None and key.get("hold") is None:
            macros[name] = _macro_definition(key["tap"])
            token = f"M_{name}"
        else:
            raise FormatError(f"unsupported behavior at {layer_name} key {index}")
    metadata = {
        readable: copy.deepcopy(key[oryx])
        for oryx, readable in KEY_METADATA.items()
        if key.get(oryx) is not None
    }
    if action_metadata:
        metadata["actionMetadata"] = action_metadata
    if not metadata:
        return token
    return {"key": token, **metadata}


def _identifier(name: str) -> str:
    result = re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_").upper()
    return result or "LAYER"


def encode(snapshot: dict[str, Any]) -> dict[str, Any]:
    layout = snapshot["layout"]
    revision = layout["revision"]
    macros: dict[str, Any] = {}
    tap_dances: dict[str, Any] = {}
    layers = []
    for layer in revision["layers"]:
        layer_name = layer.get("title") or f"layer-{layer['position']}"
        keys = [canonical_key(key) for key in layer["keys"]]
        rows = {}
        for row_name, (left, right) in ROW_INDICES.items():
            rows[row_name] = {
                "left": [
                    _slot(keys[index], layer_name, index, macros, tap_dances)
                    for index in left
                ],
                "right": [
                    _slot(keys[index], layer_name, index, macros, tap_dances)
                    for index in right
                ],
            }
        layers.append(
            {
                "position": layer["position"],
                "title": layer.get("title"),
                "color": layer.get("color"),
                "automouse": bool(layer.get("automouse")),
                "keys": rows,
            }
        )
    result = {
        "$schema": SCHEMA_PATH,
        "schemaVersion": SCHEMA_VERSION,
        "layout": {
            "hashId": layout["hashId"],
            "geometry": layout["geometry"],
            "title": layout.get("title"),
            "privacy": layout.get("privacy"),
            "tags": _stable(layout.get("tags") or []),
            "revision": {
                "model": _stable(revision.get("model")),
                "config": _stable(revision.get("config")),
                "swatch": _stable(revision.get("swatch")),
                "navigators": _stable(revision.get("navigators")),
                "layers": layers,
                "macros": macros,
                "tapDances": tap_dances,
                "combos": _stable(revision.get("combos") or []),
            },
        },
    }
    return result


def _split_arguments(arguments: str) -> list[str]:
    result = []
    depth = 0
    start = 0
    for index, character in enumerate(arguments):
        if character == "(":
            depth += 1
        elif character == ")":
            depth -= 1
            if depth < 0:
                raise FormatError("unbalanced QMK expression")
        elif character == "," and depth == 0:
            result.append(arguments[start:index].strip())
            start = index + 1
    if depth != 0:
        raise FormatError("unbalanced QMK expression")
    result.append(arguments[start:].strip())
    return result


def _action(code: str, *, layer: int | None = None, modifiers: dict[str, bool] | None = None) -> dict[str, Any]:
    return {
        "code": code,
        "color": None,
        "description": None,
        "layer": layer,
        "macro": None,
        "modifier": None,
        "modifiers": modifiers,
    }


def _parse_action(token: str) -> dict[str, Any]:
    token = token.strip()
    if TOKEN.fullmatch(token):
        return _action(token)
    match = CALL.fullmatch(token)
    if match is None:
        raise FormatError(f"invalid QMK expression {token!r}")
    function, raw_arguments = match.groups()
    arguments = _split_arguments(raw_arguments)
    if function in LAYER_ACTIONS and len(arguments) == 1:
        try:
            layer = int(arguments[0])
        except ValueError as error:
            raise FormatError(f"invalid layer in {token!r}") from error
        return _action(function, layer=layer)
    modifier = WRAPPER_MODIFIERS.get(function)
    if modifier is not None and len(arguments) == 1:
        action = _parse_action(arguments[0])
        modifiers = dict(action.get("modifiers") or _empty_modifiers())
        modifiers[modifier] = True
        action["modifiers"] = modifiers
        return action
    raise FormatError(f"unsupported QMK expression {token!r}")


def _macro_action(definition: dict[str, Any]) -> dict[str, Any]:
    _reject_unknown(
        definition,
        {"keys", "size", "applyAlt", "endEnter"},
        "macro definition",
    )
    steps = []
    for readable_step in definition.get("keys", []):
        if isinstance(readable_step, str):
            token = readable_step
            delay = None
        elif isinstance(readable_step, dict):
            _reject_unknown(readable_step, {"key", "delay"}, "macro step")
            token = readable_step.get("key")
            delay = readable_step.get("delay")
        else:
            raise FormatError("macro steps must be QMK strings or objects")
        action = _parse_action(token)
        if action["layer"] is not None or action["macro"] is not None:
            raise FormatError("macro steps must be ordinary key actions")
        step = {"code": action["code"], "modifiers": action["modifiers"]}
        if delay is not None:
            step["delay"] = delay
        steps.append(step)
    size = definition.get("size", 5)
    if not isinstance(size, int) or size < len(steps) or size > 5:
        raise FormatError("invalid Oryx macro size")
    if len(steps) > 5:
        raise FormatError("Oryx macros contain at most five steps")
    while len(steps) < size:
        steps.append({"code": "KC_TRANSPARENT", "modifiers": None})
    return _action(
        "KC_TRANSPARENT",
        modifiers=None,
    ) | {
        "macro": {
            "applyAlt": bool(definition.get("applyAlt")),
            "endEnter": bool(definition.get("endEnter")),
            "keys": steps,
            "name": None,
        }
    }


def _decode_token(
    token: str,
    macros: dict[str, Any],
    tap_dances: dict[str, Any],
) -> dict[str, Any]:
    if token == "KC_NO":
        return {}
    if token.startswith("M_"):
        name = token[2:]
        if name not in macros:
            raise FormatError(f"unknown macro {token}")
        return {"tap": _macro_action(macros[name])}
    match = CALL.fullmatch(token)
    if match is not None:
        function, raw_arguments = match.groups()
        arguments = _split_arguments(raw_arguments)
        if function == "TD" and len(arguments) == 1:
            name = arguments[0]
            if name not in tap_dances:
                raise FormatError(f"unknown tap dance {name}")
            fields = {
                field: _parse_action(value)
                for field, value in tap_dances[name].items()
            }
            unknown = set(fields) - {"tap", "hold", "doubleTap", "tapHold"}
            if unknown:
                raise FormatError(f"unknown tap-dance actions: {', '.join(sorted(unknown))}")
            return fields
        if function == "LT" and len(arguments) == 2:
            try:
                layer = int(arguments[0])
            except ValueError as error:
                raise FormatError(f"invalid layer in {token!r}") from error
            return {"tap": _parse_action(arguments[1]), "hold": _action("MO", layer=layer)}
        if function == "MT" and len(arguments) == 2:
            hold_code = MODIFIER_HOLDS.get(arguments[0])
            if hold_code is None:
                raise FormatError(f"unsupported mod-tap modifier {arguments[0]!r}")
            result = {"hold": _action(hold_code)}
            if arguments[1] != "KC_NO":
                result["tap"] = _parse_action(arguments[1])
            return result
        if function == "MO":
            return {"hold": _parse_action(token)}
    return {"tap": _parse_action(token)}


def _decode_slot(
    readable: str | dict[str, Any],
    macros: dict[str, Any],
    tap_dances: dict[str, Any],
) -> dict[str, Any]:
    if isinstance(readable, str):
        return _decode_token(readable, macros, tap_dances)
    if not isinstance(readable, dict) or not isinstance(readable.get("key"), str):
        raise FormatError("key slots must be QMK strings or objects with a key")
    key = _decode_token(readable["key"], macros, tap_dances)
    unknown = set(readable) - {"key", "actionMetadata", *METADATA_KEYS}
    if unknown:
        raise FormatError(f"unknown key metadata: {', '.join(sorted(unknown))}")
    for readable_name, oryx_name in METADATA_KEYS.items():
        if readable.get(readable_name) is not None:
            key[oryx_name] = copy.deepcopy(readable[readable_name])
    action_metadata = readable.get("actionMetadata") or {}
    for field, metadata in action_metadata.items():
        if field not in key or field not in {"tap", "hold", "doubleTap", "tapHold"}:
            raise FormatError(f"metadata refers to missing action {field!r}")
        unknown_metadata = set(metadata) - {"color", "description"}
        if unknown_metadata:
            raise FormatError(
                f"unknown action metadata: {', '.join(sorted(unknown_metadata))}"
            )
        key[field].update(copy.deepcopy(metadata))
    return key


def decode(readable: dict[str, Any]) -> dict[str, Any]:
    _reject_unknown(readable, {"$schema", "schemaVersion", "layout"}, "document")
    if readable.get("$schema") != SCHEMA_PATH:
        raise FormatError(f"unsupported or missing $schema {readable.get('$schema')!r}")
    if readable.get("schemaVersion") != SCHEMA_VERSION:
        raise FormatError(f"unsupported or missing schemaVersion {readable.get('schemaVersion')!r}")
    layout = readable.get("layout")
    _reject_unknown(
        layout,
        {"hashId", "geometry", "title", "privacy", "tags", "revision"},
        "layout",
    )
    revision = layout.get("revision")
    _reject_unknown(
        revision,
        {
            "model",
            "config",
            "swatch",
            "navigators",
            "layers",
            "macros",
            "tapDances",
            "combos",
        },
        "layout revision",
    )
    macros = revision.get("macros") or {}
    tap_dances = revision.get("tapDances") or {}
    if not isinstance(macros, dict):
        raise FormatError("layout revision macros must be an object")
    if not isinstance(tap_dances, dict):
        raise FormatError("layout revision tapDances must be an object")
    for name, definition in macros.items():
        if not isinstance(name, str):
            raise FormatError("macro names must be strings")
        _macro_action(definition)
    for name, definition in tap_dances.items():
        if not isinstance(name, str):
            raise FormatError("tap-dance names must be strings")
        _reject_unknown(
            definition,
            {"tap", "hold", "doubleTap", "tapHold"},
            "tap-dance definition",
        )
        for token in definition.values():
            _parse_action(token)
    readable_layers = revision.get("layers") or []
    if not isinstance(readable_layers, list):
        raise FormatError("layout revision layers must be an array")
    layers = []
    for readable_layer in readable_layers:
        _reject_unknown(
            readable_layer,
            {"position", "title", "color", "automouse", "keys"},
            "layer",
        )
        keys: list[dict[str, Any] | None] = [None] * 72
        readable_rows = readable_layer.get("keys")
        if not isinstance(readable_rows, dict):
            raise FormatError("layer keys must be keyboard rows")
        if set(readable_rows) != set(ROW_INDICES):
            raise FormatError("layer keys must contain the six Moonlander rows")
        for row_name, (left_indices, right_indices) in ROW_INDICES.items():
            row = readable_rows[row_name]
            _reject_unknown(row, {"left", "right"}, f"{row_name} row")
            for side, indices in (("left", left_indices), ("right", right_indices)):
                slots = row.get(side) if isinstance(row, dict) else None
                if not isinstance(slots, list) or len(slots) != len(indices):
                    raise FormatError(
                        f"{readable_layer.get('title')} {row_name} {side} needs {len(indices)} keys"
                    )
                for index, slot in zip(indices, slots):
                    keys[index] = _decode_slot(slot, macros, tap_dances)
        if any(key is None for key in keys):
            raise FormatError("Moonlander row mapping did not cover every key")
        layers.append(
            {
                "position": readable_layer.get("position"),
                "title": readable_layer.get("title"),
                "color": readable_layer.get("color"),
                "automouse": bool(readable_layer.get("automouse")),
                "keys": keys,
            }
        )
    return {
        "schemaVersion": 1,
        "layout": {
            "hashId": layout.get("hashId"),
            "geometry": layout.get("geometry"),
            "title": layout.get("title"),
            "privacy": layout.get("privacy"),
            "tags": copy.deepcopy(layout.get("tags") or []),
            "revision": {
                "model": copy.deepcopy(revision.get("model")),
                "config": copy.deepcopy(revision.get("config")),
                "swatch": copy.deepcopy(revision.get("swatch")),
                "navigators": copy.deepcopy(revision.get("navigators")),
                "layers": layers,
                "combos": copy.deepcopy(revision.get("combos") or []),
            },
        },
    }


def dumps(snapshot: dict[str, Any]) -> str:
    readable = encode(snapshot)
    rows: dict[str, str] = {}
    for layer_index, layer in enumerate(readable["layout"]["revision"]["layers"]):
        for row_name, row in layer["keys"].items():
            for side in ("left", "right"):
                marker = f"__MOONLANDER_ROW_{layer_index}_{row_name}_{side}__"
                rows[marker] = json.dumps(
                    row[side], ensure_ascii=False, separators=(", ", ": ")
                )
                row[side] = marker
    text = json.dumps(readable, indent=2, ensure_ascii=False) + "\n"
    for marker, row in rows.items():
        text = text.replace(json.dumps(marker), row)
    return text


def loads(text: str) -> dict[str, Any]:
    try:
        readable = json.loads(text)
    except json.JSONDecodeError as error:
        raise FormatError(str(error)) from error
    return decode(readable)
