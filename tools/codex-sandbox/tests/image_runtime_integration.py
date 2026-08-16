from __future__ import annotations

from pathlib import Path
import subprocess
import uuid


ROOT = Path(__file__).resolve().parents[3]
DOCKERFILE = ROOT / "tools" / "codex-sandbox" / "image" / "Dockerfile"
PI_REVISION = "a4a3cfc16b9dec18868c69979c75d88fa922702c"


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
        for tag, base_image in (
            (alpine, None),
            (debian, "node:20-bookworm-slim"),
        ):
            build(tag, base_image)
            output = run(
                "docker", "run", "--rm", "--entrypoint", "sh", tag, "-c",
                "node --version; cat /opt/agent-pi/REVISION; "
                "/opt/agent-pi/bin/pi --version",
            ).splitlines()
            expected_node = "v24." if tag == alpine else "v20."
            if not output[0].startswith(expected_node) or output[1] != PI_REVISION:
                raise RuntimeError(f"unexpected Pi runtime: {output!r}")
    finally:
        subprocess.run(
            ["docker", "image", "rm", "-f", alpine, debian],
            cwd=ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )


if __name__ == "__main__":
    main()
