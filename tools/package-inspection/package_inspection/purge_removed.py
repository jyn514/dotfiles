"""Purge residual Debian package configuration after explicit consent."""

from __future__ import annotations

import re
import shutil
import subprocess
import sys

from package_inspection.what_belongs import exit_status


PACKAGE_NAME = re.compile(rb"^[a-z0-9][a-z0-9+.-]*(?::[a-z0-9][a-z0-9-]*)?$")
QUERY_FORMAT = "${db:Status-Abbrev}\t${binary:Package}\n"


def parse_packages(output: bytes) -> list[str] | None:
    lines = output.split(b"\n")
    if lines and not lines[-1]:
        lines.pop()
    packages: set[bytes] = set()
    for line in lines:
        if not line or line.count(b"\t") != 1:
            return None
        status, package = line.split(b"\t")
        if len(status) != 3 or PACKAGE_NAME.fullmatch(package) is None:
            return None
        if status[:2] == b"rc":
            packages.add(package)
    return [package.decode("ascii") for package in sorted(packages)]


def confirmed(packages: list[str], assume_yes: bool) -> bool:
    print("Residual-config packages to purge:", file=sys.stderr)
    for package in packages:
        print(f"  {package}", file=sys.stderr)
    if assume_yes:
        return True
    print(f"Purge {len(packages)} packages? [y/N] ", end="", file=sys.stderr, flush=True)
    return sys.stdin.readline().rstrip("\n") == "y"


def main(arguments: list[str]) -> int:
    if arguments not in ([], ["--yes"]):
        print("usage: purge-removed [--yes]", file=sys.stderr)
        return 2
    query = shutil.which("dpkg-query")
    if query is None:
        print("dpkg-query not found", file=sys.stderr)
        return 127
    try:
        listing = subprocess.run(
            [query, "-W", f"-f={QUERY_FORMAT}"],
            check=False,
            stdout=subprocess.PIPE,
        )
    except OSError as error:
        print(f"could not run dpkg-query: {error}", file=sys.stderr)
        return 127
    if listing.returncode:
        return exit_status(listing.returncode)

    packages = parse_packages(listing.stdout)
    if packages is None:
        print("dpkg-query returned malformed package data", file=sys.stderr)
        return 1
    if not packages:
        return 0
    if not confirmed(packages, arguments == ["--yes"]):
        return 0

    sudo = shutil.which("sudo")
    dpkg = shutil.which("dpkg")
    if sudo is None or dpkg is None:
        missing = "sudo" if sudo is None else "dpkg"
        print(f"{missing} not found", file=sys.stderr)
        return 127
    try:
        result = subprocess.run(
            [sudo, dpkg, "--purge", "--", *packages],
            check=False,
        )
    except OSError as error:
        print(f"could not purge packages: {error}", file=sys.stderr)
        return 127
    return exit_status(result.returncode)
