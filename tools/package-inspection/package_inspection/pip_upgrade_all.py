"""Upgrade all pip packages using structured discovery and explicit consent."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys

from package_inspection.what_belongs import exit_status


PACKAGE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def command_arguments(arguments: list[str]) -> tuple[bool, list[str]]:
    assume_yes = False
    forwarded: list[str] = []
    command_options = True
    for argument in arguments:
        if command_options and argument == "--yes":
            assume_yes = True
        elif command_options and argument == "--":
            command_options = False
        else:
            forwarded.append(argument)
    return assume_yes, forwarded


def parse_packages(output: str) -> list[str] | None:
    try:
        records = json.loads(output)
    except json.JSONDecodeError:
        return None
    if not isinstance(records, list):
        return None

    names: set[str] = set()
    for record in records:
        if not isinstance(record, dict):
            return None
        name = record.get("name")
        if not isinstance(name, str) or PACKAGE_NAME.fullmatch(name) is None:
            return None
        names.add(name)
    return sorted(names, key=lambda name: (name.casefold(), name))


def confirmed(packages: list[str], assume_yes: bool) -> bool:
    print("Packages to upgrade:", file=sys.stderr)
    for package in packages:
        print(f"  {package}", file=sys.stderr)
    if assume_yes:
        return True
    print(f"Upgrade {len(packages)} packages? [y/N] ", end="", file=sys.stderr, flush=True)
    reply = sys.stdin.readline()
    return reply.rstrip("\n") == "y"


def main(arguments: list[str]) -> int:
    assume_yes, forwarded = command_arguments(arguments)
    pip = shutil.which("pip")
    if pip is None:
        print("pip not found", file=sys.stderr)
        return 127
    try:
        listing = subprocess.run(
            [pip, "list", "--format=json"],
            check=False,
            stdout=subprocess.PIPE,
            text=True,
            errors="replace",
        )
    except OSError as error:
        print(f"could not run pip: {error}", file=sys.stderr)
        return 127
    if listing.returncode:
        return exit_status(listing.returncode)

    packages = parse_packages(listing.stdout)
    if packages is None:
        print("pip returned malformed package data", file=sys.stderr)
        return 1
    if not packages:
        return 0
    if not confirmed(packages, assume_yes):
        return 0

    try:
        result = subprocess.run(
            [pip, "install", "-U", *forwarded, *packages],
            check=False,
        )
    except OSError as error:
        print(f"could not run pip: {error}", file=sys.stderr)
        return 127
    return exit_status(result.returncode)
