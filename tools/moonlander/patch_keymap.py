#!/usr/bin/env python3
"""Replace Oryx placeholders with repository-owned QMK functionality."""

from __future__ import annotations

import argparse
import re
from pathlib import Path


UNICODE_START = "SS_LCTL(SS_LSFT(SS_TAP(X_U)))"
SEND_STRING = re.compile(r"SEND_STRING\((?P<body>[^;]*?)\);")
HEX_TAP = re.compile(r"SS_TAP\(X_([0-9A-F])\)")
ANY_TAP = re.compile(r"SS_TAP\(X_([A-Z0-9_]+)\)")
SENTINELS = {"KC_F13": "UC_NEXT"}
BACKTICKS = (
    "SEND_STRING(SS_TAP(X_GRAVE) SS_DELAY(5) SS_TAP(X_GRAVE) "
    "SS_DELAY(5) SS_TAP(X_GRAVE) SS_DELAY(5) SS_TAP(X_ENTER) "
    "SS_DELAY(5) SS_TAP(X_ENTER) SS_DELAY(5) SS_TAP(X_GRAVE) "
    "SS_DELAY(5) SS_TAP(X_GRAVE) SS_DELAY(5) SS_TAP(X_GRAVE) "
    "SS_DELAY(5) SS_TAP(X_UP));"
)


class PatchError(RuntimeError):
    pass


def unicode_calls(body: str) -> list[str] | None:
    if UNICODE_START not in body:
        return None
    prefix, *sequences = body.split(UNICODE_START)
    if prefix.strip():
        raise PatchError("Unicode SEND_STRING has content before its first input sequence")
    calls = []
    for sequence in sequences:
        terminators = [
            index
            for marker in ("SS_TAP(X_ENTER)", "SS_TAP(X_SPACE)")
            if (index := sequence.find(marker)) >= 0
        ]
        if not terminators:
            raise PatchError("Unicode input sequence has no Enter or Space terminator")
        terminator = min(terminators)
        digits = HEX_TAP.findall(sequence[:terminator])
        if not digits:
            raise PatchError("Unicode input sequence contains no hexadecimal code point")
        trailing = sequence[terminator:]
        trailing = trailing.replace("SS_TAP(X_ENTER)", "", 1)
        trailing = trailing.replace("SS_TAP(X_SPACE)", "", 1)
        trailing = re.sub(r"SS_DELAY\(\d+\)", "", trailing)
        if trailing.strip():
            raise PatchError("Unicode input sequence contains unsupported trailing actions")
        calls.append(f"register_unicode(0x{''.join(digits)});")
    return calls


def patch_keymap(source: str, require_sentinels: bool = True) -> str:
    unicode_count = 0

    def replace_unicode(match: re.Match[str]) -> str:
        nonlocal unicode_count
        body = match.group("body")
        taps = ANY_TAP.findall(body)
        if taps == ["GRAVE", "GRAVE", "GRAVE"]:
            return BACKTICKS
        if taps == ["P", "L", "P", "R"]:
            unicode_count += 2
            return "register_unicode(0x1F449); register_unicode(0x1F448);"
        calls = unicode_calls(body)
        if calls is None:
            return match.group(0)
        unicode_count += len(calls)
        return " ".join(calls)

    result = source.replace("SS_DELAY(100)", "SS_DELAY(5)")
    result = SEND_STRING.sub(replace_unicode, result)
    if unicode_count == 0:
        raise PatchError("no Oryx Unicode macros were found")
    for placeholder, replacement in SENTINELS.items():
        count = result.count(placeholder)
        if require_sentinels and count != 1:
            raise PatchError(f"expected one {placeholder} sentinel, found {count}")
        result = result.replace(placeholder, replacement)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("keymap", type=Path)
    args = parser.parse_args()
    try:
        source = args.keymap.read_text()
        patched = patch_keymap(source)
        args.keymap.write_text(patched)
    except (OSError, PatchError) as error:
        parser.error(str(error))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
