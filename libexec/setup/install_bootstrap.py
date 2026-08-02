#!/usr/bin/env python3

import argparse
import hashlib
import json
import shutil
import subprocess
import tempfile
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MANIFEST = ROOT / "install/bootstrap.lock.json"


def load_entry(manifest: Path, kind: str, name: str) -> dict[str, str]:
    entries = json.loads(manifest.read_text())[kind]
    if name not in entries:
        raise ValueError(f"unknown locked {kind} source: {name}")
    return entries[name]


def download(entry: dict[str, str], destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=destination.parent, delete=False) as output:
        temporary = Path(output.name)
        digest = hashlib.sha256()
        try:
            with urllib.request.urlopen(entry["url"]) as response:
                while chunk := response.read(1024 * 1024):
                    digest.update(chunk)
                    output.write(chunk)
            if digest.hexdigest() != entry["sha256"]:
                raise ValueError(
                    f"checksum mismatch for {entry['url']}: {digest.hexdigest()}"
                )
            temporary.replace(destination)
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise


def clone(entry: dict[str, str], destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        return
    with tempfile.TemporaryDirectory(dir=destination.parent) as temporary:
        staged = Path(temporary) / destination.name
        subprocess.run(["git", "init", "--quiet", staged], check=True)
        subprocess.run(
            ["git", "-C", staged, "fetch", "--quiet", "--depth=1", entry["url"], entry["revision"]],
            check=True,
        )
        subprocess.run(
            ["git", "-C", staged, "checkout", "--quiet", "--detach", "FETCH_HEAD"],
            check=True,
        )
        staged.replace(destination)


def main() -> int:
    parser = argparse.ArgumentParser(description="Install checksum-locked bootstrap inputs")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("download", "clone"):
        subparser = subparsers.add_parser(command)
        subparser.add_argument("name")
        subparser.add_argument("destination", type=Path)
    get_parser = subparsers.add_parser("get")
    get_parser.add_argument("kind", choices=("downloads", "git"))
    get_parser.add_argument("name")
    get_parser.add_argument("field")
    arguments = parser.parse_args()
    try:
        if arguments.command == "get":
            value = load_entry(
                arguments.manifest, arguments.kind, arguments.name
            ).get(arguments.field)
            if not isinstance(value, str):
                raise ValueError(
                    f"locked {arguments.kind} source {arguments.name} has no string field {arguments.field}"
                )
            print(value)
            return 0
        kind = "downloads" if arguments.command == "download" else "git"
        entry = load_entry(arguments.manifest, kind, arguments.name)
        if arguments.command == "download":
            download(entry, arguments.destination)
        else:
            clone(entry, arguments.destination)
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"{error}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
