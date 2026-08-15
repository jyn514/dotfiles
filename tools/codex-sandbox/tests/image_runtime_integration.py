from __future__ import annotations

import json
from pathlib import Path
import subprocess
import uuid


ROOT = Path(__file__).resolve().parents[3]
DOCKERFILE = ROOT / "tools" / "codex-sandbox" / "image" / "Dockerfile"
PACKAGE_LOCK = ROOT / "tools" / "pi-npm" / "package-lock.json"
PI_VERSION = json.loads(PACKAGE_LOCK.read_text(encoding="utf-8"))["packages"][
    "node_modules/@earendil-works/pi-coding-agent"
]["version"]


def run(*args: str) -> str:
    return subprocess.run(
        args,
        cwd=ROOT,
        check=True,
        stdout=subprocess.PIPE,
        text=True,
    ).stdout


def build(tag: str, base_image: str | None = None) -> None:
    command = [
        "docker", "build", "-f", str(DOCKERFILE), "--target", "pi-runtime",
    ]
    if base_image is not None:
        command.extend(["--build-arg", f"BASE_IMAGE={base_image}"])
    command.extend(["-t", tag, "."])
    subprocess.run(command, cwd=ROOT, check=True)


def main() -> None:
    suffix = uuid.uuid4().hex
    alpine = f"codex-sandbox-pi-alpine-test:{suffix}"
    debian = f"codex-sandbox-pi-debian-test:{suffix}"
    try:
        build(alpine)
        alpine_output = run(
            "docker", "run", "--rm", "--entrypoint", "sh", alpine, "-c",
            "test ! -e /opt/agent-pi/standalone; "
            "node --version; /opt/agent-pi/bin/pi --version",
        ).splitlines()
        if not alpine_output[0].startswith("v24.") or alpine_output[1] != PI_VERSION:
            raise RuntimeError(f"unexpected Alpine runtimes: {alpine_output!r}")

        build(debian, "node:20-bookworm-slim")
        debian_output = run(
            "docker", "run", "--rm", "--entrypoint", "sh", debian, "-c",
            "test ! -e /opt/agent-pi/lib; "
            "node --version; /opt/agent-pi/bin/pi --version",
        ).splitlines()
        if not debian_output[0].startswith("v20.") or debian_output[1] != PI_VERSION:
            raise RuntimeError(f"unexpected Debian runtimes: {debian_output!r}")
    finally:
        subprocess.run(
            ["docker", "image", "rm", "-f", alpine, debian],
            cwd=ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )


if __name__ == "__main__":
    main()
