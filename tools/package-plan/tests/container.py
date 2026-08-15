#!/usr/bin/env python3

import platform
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
ARCH = "arm64" if platform.machine() in ("arm64", "aarch64") else "amd64"
MOUNT = f"{ROOT}:/repo:ro"


def run(image: str, script: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "podman", "run", "--rm", "--platform", f"linux/{ARCH}",
            "-v", MOUNT, "-w", "/repo", image, "sh", "-c", script,
        ],
        text=True,
        capture_output=True,
        check=False,
    )


def require(result: subprocess.CompletedProcess[str], description: str) -> None:
    if result.returncode:
        print(f"{description} failed:\n{result.stdout}{result.stderr}", file=sys.stderr)
        raise SystemExit(1)


def main() -> None:
    missing = {
        "docker.io/library/debian:trixie-slim": "install ca-certificates and curl",
        "docker.io/library/ubuntu:latest": "install ca-certificates and curl",
        "docker.io/chimeralinux/chimera:latest": "install curl, libarchive-progs",
    }
    if ARCH == "arm64":
        missing["docker.io/chimeralinux/chimera:latest"] += ", and gcompat"
    for image, diagnostic in missing.items():
        result = run(image, "HOME=/tmp/home dev/package-plan validate")
        if result.returncode == 0 or diagnostic not in result.stderr:
            print(f"wrong bootstrap diagnostic for {image}: {result.stderr}", file=sys.stderr)
            raise SystemExit(1)

    alpine_floor = "gcompat" if ARCH == "arm64" else ""
    chimera_floor = "curl libarchive-progs" + (" gcompat" if ARCH == "arm64" else "")
    scenarios = {
        "docker.io/library/debian:trixie-slim":
            "apt-get update >/dev/null && apt-get install -y ca-certificates curl >/dev/null",
        "docker.io/library/ubuntu:latest":
            "apt-get update >/dev/null && apt-get install -y ca-certificates curl >/dev/null",
        "docker.io/library/fedora:latest": ":",
        "docker.io/library/archlinux:latest": ":",
        "docker.io/library/alpine:latest": f"apk add {alpine_floor} >/dev/null" if alpine_floor else ":",
        "docker.io/chimeralinux/chimera:latest": f"apk add {chimera_floor} >/dev/null",
    }
    for image, prepare in scenarios.items():
        result = run(
            image,
            f"{prepare} && HOME=/tmp/home XDG_CACHE_HOME=/tmp/cache dev/package-plan validate",
        )
        require(result, f"bootstrap on {image}")

    for image, prepare in {
        "docker.io/library/alpine:latest":
            f"apk add {alpine_floor} >/dev/null" if alpine_floor else ":",
        "docker.io/chimeralinux/chimera:latest": f"apk add {chimera_floor} >/dev/null",
    }.items():
        result = run(
            image,
            f"{prepare} && HOME=/tmp/home XDG_CACHE_HOME=/tmp/cache "
            "PACKAGE_PLAN_UID=0 dev/package-plan apply --dry-run --yes >/tmp/plan && "
            "/tmp/cache/dotfiles/package-plan/mise/2026.8.0/mise --version && "
            "grep 'packages apk:' /tmp/plan",
        )
        require(result, f"complete musl dry run on {image}")


if __name__ == "__main__":
    main()
