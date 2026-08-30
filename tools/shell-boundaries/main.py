#!/usr/bin/env python3
"""Reject new shell constructs that hide producer failures or parse path lines.

The fingerprint baseline records pre-enforcement debt, not approved exceptions.
Changing an existing risky command invalidates its fingerprint. New exceptions
must use a reasoned ``langsec: allow`` comment beside the relevant command.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path
from typing import NamedTuple


ROOT = Path(__file__).resolve().parents[2]
SEARCH_ROOTS = ("bin", "config", "dev", "lib", "libexec", "tests", "tools")
SHELL_NAMES = {"profile", "zprofile", "zshrc", "config.fish", "tmux.conf"}
ALLOW = re.compile(r"#\s*langsec:\s*allow\s+([a-z-]+)\s+--\s+(.+)$")
BASELINE_PATH = Path(__file__).with_name("baseline.json")


class Rule(NamedTuple):
    name: str
    message: str
    pattern: re.Pattern[str]


RULES = (
    Rule(
        "nested-substitution",
        "nested command substitution obscures which producer failed",
        re.compile(r"\$\([^\n)]*\$\("),
    ),
    Rule(
        "filename-lines",
        "newline-delimited Git/find output is unsafe for filenames",
        re.compile(r"(?:git\s+(?:diff\b[^\n|]*--name-only[^\n|]*|ls-files\b[^\n|]*)|find\s+[^\n|]+)\s*\|"),
    ),
    Rule(
        "unchecked-pipeline",
        "a pipeline inside command substitution can mask its producer failure",
        re.compile(r"=\$\([^\n]*\|[^\n]*\)(?!\s*\|\|)"),
    ),
    Rule(
        "persistent-write",
        "persistent caches and completions must be staged and replaced atomically",
        re.compile(r"(?:^|[;&]\s*)(?:[^#\n]*\s)?(?:>|tee\s+)(?!>)[^\n]*(?:cache|completions?)", re.I),
    ),
)


def is_shell_file(path: Path) -> bool:
    if path.name in SHELL_NAMES or path.suffix in {".sh", ".bash", ".zsh", ".fish"}:
        return True
    try:
        first_line = path.open("rb").readline(256)
    except OSError:
        return False
    return first_line.startswith(b"#!") and any(shell in first_line for shell in (b"sh", b"bash", b"zsh", b"fish"))


def shell_files() -> list[Path]:
    paths = [ROOT / "setup", ROOT / "track"]
    for directory in SEARCH_ROOTS:
        paths.extend(path for path in (ROOT / directory).rglob("*") if path.is_file())
    return sorted({path for path in paths if is_shell_file(path)})


def fingerprint(path: Path, rule: str, line: str) -> str:
    relative = path.relative_to(ROOT).as_posix()
    digest = hashlib.sha256(line.encode(errors="surrogateescape")).hexdigest()[:16]
    return f"{relative}:{rule}:{digest}"


def findings(path: Path) -> list[tuple[str, int, Rule]]:
    try:
        lines = path.read_text(errors="surrogateescape").splitlines()
    except OSError as error:
        raise RuntimeError(f"{path}: cannot read: {error}") from error

    result: list[tuple[str, int, Rule]] = []
    pending_allow: tuple[str, str] | None = None
    for number, line in enumerate(lines, 1):
        annotation = ALLOW.search(line)
        if annotation and line.lstrip().startswith("#"):
            pending_allow = (annotation.group(1), annotation.group(2).strip())
            continue

        inline = annotation.group(1) if annotation else None
        for rule in RULES:
            if not rule.pattern.search(line):
                continue
            if inline == rule.name or pending_allow and pending_allow[0] == rule.name:
                continue
            result.append((fingerprint(path, rule.name, line), number, rule))
        if line.strip() and not line.lstrip().startswith("#"):
            pending_allow = None
    return result


def load_baseline() -> set[str]:
    try:
        values = json.loads(BASELINE_PATH.read_text())
    except FileNotFoundError:
        return set()
    if not isinstance(values, list) or not all(isinstance(value, str) for value in values):
        raise ValueError(f"{BASELINE_PATH} must contain a JSON array of strings")
    return set(values)


def violations(path: Path, baseline: set[str] | None = None) -> list[str]:
    baseline = baseline or set()
    relative = path.relative_to(ROOT)
    return [
        f"{relative}:{number}: {rule.name}: {rule.message}; "
        f"add '# langsec: allow {rule.name} -- reason' beside an approved exception"
        for key, number, rule in findings(path)
        if key not in baseline
    ]


def main() -> int:
    paths = shell_files()
    if sys.argv[1:]:
        print("usage: main.py", file=sys.stderr)
        return 2

    baseline = load_baseline()
    current = {key for path in paths for key, _, _ in findings(path)}
    stale = sorted(baseline - current)
    if stale:
        print("shell-boundary baseline contains resolved entries; regenerate it:", file=sys.stderr)
        print("\n".join(stale), file=sys.stderr)
        return 1

    problems = [problem for path in paths for problem in violations(path, baseline)]
    if problems:
        print("\n".join(problems), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
