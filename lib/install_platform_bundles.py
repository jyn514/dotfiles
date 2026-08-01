#!/usr/bin/env python3

import argparse
import hashlib
import json
import os
import platform
import shutil
import tempfile
import urllib.request
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def platform_key() -> str:
    system = platform.system().lower()
    machine = platform.machine().lower()
    architectures = {
        "amd64": "x86_64",
        "arm64": "aarch64",
        "x64": "x86_64",
    }
    machine = architectures.get(machine, machine)
    if system == "linux" and Path("/etc/alpine-release").exists():
        system = "linux-musl"
    return f"{system}-{machine}"


def bundle_url(bundle: dict, current_platform: str) -> str | None:
    platforms = bundle["platforms"]
    return platforms.get(current_platform) or platforms.get("all")


def bundle_checksum(bundle: dict, current_platform: str) -> str | None:
    checksums = bundle["sha256"]
    return checksums.get(current_platform) or checksums.get("all")


def download(url: str, destination: Path, expected_checksum: str) -> None:
    with urllib.request.urlopen(url) as response, destination.open("wb") as output:
        digest = hashlib.sha256()
        while chunk := response.read(1024 * 1024):
            digest.update(chunk)
            output.write(chunk)
    if digest.hexdigest() != expected_checksum:
        raise ValueError(f"checksum mismatch for {url}: {digest.hexdigest()}")


def install_bundle(
    name: str,
    bundle: dict,
    *,
    home: Path,
    current_platform: str,
) -> bool:
    url = bundle_url(bundle, current_platform)
    if url is None:
        print(f"Skipping {name}: unsupported on {current_platform}")
        return False
    destination = home / bundle["destination"]
    if destination.is_dir():
        return False

    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=f"{name}.", dir=destination.parent
    ) as temporary:
        temporary_directory = Path(temporary)
        archive = temporary_directory / "bundle.zip"
        staged = temporary_directory / "contents"
        staged.mkdir()
        checksum = bundle_checksum(bundle, current_platform)
        if checksum is None:
            raise ValueError(f"missing checksum for {name} on {current_platform}")
        download(url, archive, checksum)
        with zipfile.ZipFile(archive) as bundle_zip:
            bundle_zip.extractall(staged)
        executable = bundle.get("executable")
        if executable:
            path = staged / executable
            path.chmod(path.stat().st_mode | 0o111)
        staged.replace(destination)
    return True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("bundles", nargs="+")
    parser.add_argument(
        "--manifest", type=Path, default=ROOT / "install/bundles.json"
    )
    arguments = parser.parse_args()
    manifest = json.loads(arguments.manifest.read_text())
    for name in arguments.bundles:
        if name not in manifest:
            parser.error(f"unknown platform bundle: {name}")
        install_bundle(
            name,
            manifest[name],
            home=Path.home(),
            current_platform=platform_key(),
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
