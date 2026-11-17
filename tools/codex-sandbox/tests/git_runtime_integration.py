"""Build and exercise the shared Git runtime without rebuilding Pi.

This is also called by image_runtime_integration.py for its final images.
"""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import tempfile
import uuid

ROOT = Path(__file__).resolve().parents[3]
DOCKERFILE = ROOT / "tools/codex-sandbox/image/Dockerfile"
PROBE = Path(__file__).with_name("fixtures") / "git-runtime.py"
BASES = {
    "alpine": "node:24-alpine3.22",
    "trixie": "node:24-trixie-slim",
    "bookworm": "node:20-bookworm-slim",
    "rpm": "registry.fedoraproject.org/fedora-minimal:44",
}


def probe_git(image, *, check_toolchain=False):
    subprocess.run([
        "docker", "run", "--rm", "--interactive", "--user", "1000:1000",
        "--read-only", "--tmpfs", "/tmp:mode=1777", "--entrypoint", "python3",
        image, "-", *(["--no-toolchain"] if check_toolchain else []),
    ], input=PROBE.read_text(), text=True, check=True, timeout=120)


def main():
    platform = subprocess.check_output([
        "docker", "version", "--format", "{{.Server.Os}}/{{.Server.Arch}}",
    ], text=True).strip()
    suffix = uuid.uuid4().hex
    tags = {name: f"codex-sandbox-git-{name}-test:{suffix}" for name in BASES}
    caches = {name: f"codex-sandbox-git-{name}-test:cache" for name in BASES}
    definition = {
        "group": {"default": {"targets": list(BASES)}},
        "target": {name: {
            "context": str(ROOT), "dockerfile": str(DOCKERFILE), "target": "agent-deps",
            "args": {"BASE_IMAGE": base, "JJ_IMAGE": "alpine:3.22"},
            "tags": [tags[name], caches[name]], "platforms": [platform],
        } for name, base in BASES.items()},
    }
    try:
        with tempfile.TemporaryDirectory(prefix="git-runtime-bake-") as directory:
            path = Path(directory) / "docker-bake.json"
            path.write_text(json.dumps(definition))
            subprocess.run(["docker", "buildx", "bake", "--file", str(path), "--print"], check=True)
            subprocess.run(["docker", "buildx", "bake", "--file", str(path), "--load"], check=True)
        for name, image in tags.items():
            subprocess.run(["docker", "image", "inspect", "--format",
                            "{{.Id}} {{.Os}}/{{.Architecture}}", image], check=True)
            print(f"Git runtime: {name} ({BASES[name]})", flush=True)
            probe_git(image, check_toolchain=True)
    finally:
        subprocess.run(["docker", "image", "rm", *tags.values()],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)


if __name__ == "__main__":
    main()
