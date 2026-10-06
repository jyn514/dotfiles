from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import uuid


ROOT = Path(__file__).resolve().parents[3]
DOCKERFILE = ROOT / "tools" / "codex-sandbox" / "image" / "Dockerfile"
WRAPPED_COMMAND_PROBE = Path(__file__).with_name("wrapped_command_probe.clj")


def run(*args: str) -> str:
    return subprocess.run(
        args,
        cwd=ROOT,
        check=True,
        stdout=subprocess.PIPE,
        text=True,
    ).stdout


def build(tag: str, pi_revision: str, base_image: str | None = None) -> None:
    command = [
        "docker", "build", "-f", str(DOCKERFILE),
        "--build-arg", f"PI_REVISION={pi_revision}",
    ]
    if base_image is not None:
        command.extend(["--build-arg", f"BASE_IMAGE={base_image}"])
    command.extend(["-t", tag, "."])
    subprocess.run(command, cwd=ROOT, check=True)


def main() -> None:
    parser = argparse.ArgumentParser(description='Build and check Alpine Node and Debian Bun runtimes.')
    parser.add_argument('--expected-revision', required=True, help='expected Pi commit in the built images')
    args = parser.parse_args()
    suffix = uuid.uuid4().hex
    alpine = f"codex-sandbox-pi-alpine-test:{suffix}"
    debian = f"codex-sandbox-pi-debian-test:{suffix}"
    try:
        for tag, base_image in (
            (alpine, None),
            (debian, "node:20-bookworm-slim"),
        ):
            build(tag, args.expected_revision, base_image)
            label = run(
                'docker', 'image', 'inspect', '--format',
                '{{ index .Config.Labels "dev.codex.pi-revision" }}', tag,
            ).strip()
            if label != args.expected_revision:
                raise RuntimeError(f'unexpected Pi revision label: {label!r}')
            output = run(
                "docker", "run", "--rm", "--entrypoint", "sh", tag, "-c",
                "node --version; cat /opt/agent-pi/REVISION; "
                "/opt/agent-pi/bin/pi --version; bun --version; "
                "bun test /opt/agent-pi/check-bun.test.ts >/dev/null "
                "&& printf 'bun-test-ok\\n'",
            ).splitlines()
            expected_node = "v24." if tag == alpine else "v20."
            if (
                not output[0].startswith(expected_node)
                or output[1] != args.expected_revision
                or output[3:] != ["1.3.14", "bun-test-ok"]
            ):
                raise RuntimeError(f"unexpected Pi runtime: {output!r}")
            wrapped = run(
                "docker", "run", "--rm",
                "--entrypoint", "/opt/agent-tools/libexec/bb",
                "--mount", f"type=bind,src={WRAPPED_COMMAND_PROBE},dst=/probe.clj,readonly",
                tag, "/probe.clj",
            )
            if wrapped != "wrapped-command-probe-ok\n":
                raise RuntimeError(f"unexpected wrapped-command probe: {wrapped!r}")
    finally:
        subprocess.run(
            ["docker", "image", "rm", "-f", alpine, debian],
            cwd=ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )


if __name__ == "__main__":
    main()
