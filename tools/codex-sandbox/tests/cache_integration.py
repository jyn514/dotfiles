"""Check image-seeded Jiti reuse, invalidation, isolation, and build failure handling."""

from __future__ import annotations

import argparse
from pathlib import Path
import re
import subprocess
import tempfile
import uuid


ROOT = Path(__file__).resolve().parents[3]
FIXTURES = Path(__file__).resolve().with_name("fixtures")
EXTENSIONS = "/home/codex/.pi/agent/pi-extensions"


def run(image: str, *arguments: str, mounts: tuple[str, ...] = (),
        entrypoint: str = "/opt/agent-pi/bin/pi") -> subprocess.CompletedProcess[str]:
    container = f"pi-cache-test-{uuid.uuid4().hex}"
    try:
        result = subprocess.run(
            ["docker", "run", "--rm", "--name", container, "--network", "none",
             "--env", "PI_OFFLINE=1", "--env", "JITI_DEBUG=1",
             "--mount", f"type=bind,src={ROOT / 'config/pi-extensions'},dst={EXTENSIONS},readonly",
             *[argument for mount in mounts for argument in ("--mount", mount)],
             "--entrypoint", entrypoint, image, *arguments],
            text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=60,
        )
    finally:
        # A timeout can kill the CLI without stopping its container.
        subprocess.run(["docker", "rm", "--force", container],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15)
    result.stdout = re.sub(r"\x1b\[[0-9;]*m", "", result.stdout)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", required=True, help="built final sandbox image")
    parser.add_argument("--builder", required=True, help="pi-extension-cache stage image")
    args = parser.parse_args()
    help_args = ("--no-extensions", "--extension", f"{EXTENSIONS}/index.ts", "--help")

    # The first container must use the image seed, without a previous session.
    original = run(args.runtime, *help_args)
    assert original.returncode == 0, original.stdout
    assert "[cache] [hit]" in original.stdout, original.stdout
    assert "[cache] [miss]" not in original.stdout, original.stdout

    edited = run(args.runtime, *help_args, mounts=(
        f"type=bind,src={FIXTURES / 'cache-edited.ts'},dst={EXTENSIONS}/index.ts,readonly",
    ))
    assert edited.returncode == 0, edited.stdout
    assert "--cache-invalidation-check" in edited.stdout, edited.stdout
    assert "[cache] [miss]" in edited.stdout, edited.stdout

    # A later container still starts with the original seed.
    again = run(args.runtime, *help_args)
    assert again.returncode == 0, again.stdout
    assert "--cache-invalidation-check" not in again.stdout, again.stdout
    assert "[cache] [miss]" not in again.stdout, again.stdout

    failure = run(args.builder, "/opt/cache-pi-extensions.mjs", "warm",
                  entrypoint="node", mounts=(
        f"type=bind,src={FIXTURES / 'cache-failure.ts'},dst={EXTENSIONS}/index.ts,readonly",
    ))
    assert failure.returncode != 0, failure.stdout
    assert "cache fixture failure" in failure.stdout, failure.stdout

    with tempfile.TemporaryDirectory() as empty_packages:
        missing = run(args.builder, "/opt/cache-pi-extensions.mjs", "warm",
                      entrypoint="node", mounts=(
            f"type=bind,src={empty_packages},dst=/home/codex/.pi/agent/npm,readonly",
        ))
    assert missing.returncode != 0, missing.stdout
    assert "Missing cache input: npm:" in missing.stdout, missing.stdout
    print("Image cache: reuse, invalidation, isolation, and source/package failures passed")


if __name__ == "__main__":
    main()
