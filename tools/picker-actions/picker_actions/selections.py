"""Parse direct or NUL-delimited picker selections without decoding paths."""

from __future__ import annotations

import os
import sys


def read_records(data: bytes) -> list[bytes] | None:
    if not data:
        return []
    if not data.endswith(b"\0"):
        return None
    records = data[:-1].split(b"\0")
    if records == [b""]:
        return []
    if any(not record for record in records):
        return None
    return records


def parse(arguments: list[str]) -> list[bytes] | None:
    if arguments == ["--read0"]:
        return read_records(sys.stdin.buffer.read())
    if arguments and arguments[0] == "--":
        arguments = arguments[1:]
    if not arguments:
        return None
    return [os.fsencode(argument) for argument in arguments]
