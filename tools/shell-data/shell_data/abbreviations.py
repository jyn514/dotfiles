"""Validate the compact `name=expansion` abbreviation format."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Entry:
    name: str
    expansion: str
    line: int


@dataclass(frozen=True)
class Diagnostic:
    line: int
    message: str

    def __str__(self) -> str:
        return f"line {self.line}: {self.message}"


def validate(contents: bytes) -> tuple[list[Entry], list[Diagnostic]]:
    entries: list[Entry] = []
    diagnostics: list[Diagnostic] = []
    names: dict[str, int] = {}
    for number, raw_line in enumerate(contents.split(b"\n"), 1):
        if raw_line.endswith(b"\r"):
            raw_line = raw_line[:-1]
        if b"\0" in raw_line:
            diagnostics.append(Diagnostic(number, "NUL is not allowed"))
            continue
        if b"\r" in raw_line:
            diagnostics.append(Diagnostic(number, "carriage return is only allowed in CRLF"))
            continue
        try:
            line = raw_line.decode("utf-8")
        except UnicodeDecodeError:
            diagnostics.append(Diagnostic(number, "line is not valid UTF-8"))
            continue
        if not line or line.startswith("#"):
            continue
        name, separator, expansion = line.partition("=")
        if not separator:
            diagnostics.append(Diagnostic(number, "expected name=expansion"))
            continue
        if not name:
            diagnostics.append(Diagnostic(number, "name must not be empty"))
        elif any(character.isspace() for character in name):
            diagnostics.append(Diagnostic(number, "name must not contain whitespace"))
        if not expansion:
            diagnostics.append(Diagnostic(number, "expansion must not be empty"))
        previous = names.get(name)
        if name and previous is not None:
            diagnostics.append(
                Diagnostic(number, f"duplicate name {name!r}; first defined on line {previous}")
            )
        elif name:
            names[name] = number
        if (
            name
            and expansion
            and not any(character.isspace() for character in name)
            and previous is None
        ):
            entries.append(Entry(name, expansion, number))
    return entries, diagnostics
