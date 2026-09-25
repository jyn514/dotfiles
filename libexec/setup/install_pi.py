#!/usr/bin/env python3
"""Build and install the Pi fork used by codex-sandbox."""

from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys


PI_REPOSITORY = "https://github.com/jyn514/pi.git"
# Follow upstream main; the installed commit is recorded after each successful
# build so unchanged setup runs remain cheap.
PI_REVISION = "main"
PI_STATE = Path.home() / ".local/share/pi"
PI_SOURCE = PI_STATE / "source"
PI_INSTALL = PI_STATE / "node"
PI_PACKAGE = PI_SOURCE / "packages/coding-agent"
PI_CLI = PI_INSTALL / "node_modules/.bin/pi"


def run(command: list[str], *, cwd: Path | None = None) -> None:
    subprocess.run(command, cwd=cwd, check=True)


def installed_revision() -> str | None:
    marker = PI_INSTALL / ".source-revision"
    try:
        return marker.read_text(encoding="utf-8").strip()
    except OSError:
        return None


def install_is_current(expected_revision: str) -> bool:
    return installed_revision() == expected_revision and PI_CLI.is_file() and all(
        (PI_INSTALL / "node_modules/@earendil-works/pi-coding-agent" / relative).exists()
        for relative in ("README.md", "docs", "examples")
    )


def source_revision() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=PI_SOURCE,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def prepare_source() -> None:
    if not (PI_SOURCE / ".git").is_dir():
        PI_STATE.mkdir(mode=0o700, parents=True, exist_ok=True)
        run(["git", "clone", "--filter=blob:none", PI_REPOSITORY, str(PI_SOURCE)])
    else:
        remote = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=PI_SOURCE,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        if remote != PI_REPOSITORY:
            raise RuntimeError(f"unexpected Pi source remote: {remote}")

    run(["git", "fetch", "--depth", "1", "origin", PI_REVISION], cwd=PI_SOURCE)
    # This checkout is installer-owned. Discard generated-file edits from a
    # previous failed or exploratory build before using the fetched revision.
    run(["git", "checkout", "--force", "--detach", "FETCH_HEAD"], cwd=PI_SOURCE)


def install() -> None:
    if PI_REVISION != "main" and install_is_current(PI_REVISION):
        return

    prepare_source()
    revision = source_revision()
    if install_is_current(revision):
        return
    run(["npm", "ci", "--ignore-scripts"], cwd=PI_SOURCE)
    run(["npm", "run", "hydrate:pinned-model-data"], cwd=PI_SOURCE)
    run(["npm", "run", "build:offline"], cwd=PI_SOURCE)

    PI_INSTALL.mkdir(mode=0o700, parents=True, exist_ok=True)
    run([
        "npm", "install", "--ignore-scripts", "--prefix", str(PI_INSTALL),
        str(PI_PACKAGE),
    ])
    (PI_INSTALL / ".source-revision").write_text(revision + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    try:
        install()
    except (OSError, RuntimeError, subprocess.CalledProcessError) as error:
        print(f"install-pi: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
