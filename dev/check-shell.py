#!/usr/bin/env python3
"""Run ShellCheck on non-ignored POSIX scripts in the test runner's source roots."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


ROOT = Path(__file__).resolve().parent.parent
SOURCE_ROOTS = {"setup", "track", "bin", "dev", "lib", "libexec", "tests", "tools"}


def main() -> int:
    for command in ("rg", "shellcheck"):
        if shutil.which(command) is None:
            raise OSError(f"{command} is required for shell checks; install ripgrep and ShellCheck")
    # Let ripgrep interpret root/nested .gitignore files, including negations.
    # Explicit file arguments would bypass ignores for setup and track.
    listing = subprocess.run([
        "rg", "--no-config", "--no-require-git", "--files", "--hidden", "--null",
        "--no-ignore-dot", "--no-ignore-global", "--no-ignore-parent", "--no-ignore-exclude",
        "--glob", "!.git/**", "--glob", "!.jj/**",
    ], cwd=ROOT, stdout=subprocess.PIPE)
    if listing.returncode not in (0, 1):
        return listing.returncode
    scripts = []
    for entry in listing.stdout.split(b"\0"):
        if not entry:
            continue
        path = Path(os.fsdecode(entry))
        if path.parts[0] not in SOURCE_ROOTS:
            continue
        with (ROOT / path).open("rb") as source:
            if source.readline(256).rstrip(b"\r\n") == b"#!/bin/sh":
                scripts.append(str(path))
    if not scripts:
        return 0
    report = subprocess.run([
        "shellcheck", "--format=json", "--exclude=SC2015,SC1091", "--", *sorted(scripts),
    ], cwd=ROOT, text=True, stdout=subprocess.PIPE)
    if report.returncode not in (0, 1):
        return report.returncode
    findings = json.loads(report.stdout)
    if report.returncode and not findings:
        raise ValueError("ShellCheck failed without diagnostics")
    for finding in findings:
        print(f'{finding["file"]}:{finding["line"]}:{finding["column"]}: '
              f'error: SC{finding["code"]}: {finding["message"]}')
    return int(bool(findings))


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError) as error:
        print(f"shell checks: {error}", file=sys.stderr)
        raise SystemExit(1)
