"""Run inside a fresh final image and verify its Node cache is already usable."""

from pathlib import Path
import os
import subprocess


if not Path("/etc/alpine-release").exists():
    print("Node bytecode seed applies only to Alpine; this image uses Bun")
    raise SystemExit(0)

cache = Path("/tmp/pi-node-cache")
seed = {path: path.stat().st_mtime_ns for path in cache.rglob("*") if path.is_file()}
assert seed, "image has no Node bytecode seed"
result = subprocess.run(["pi", "--offline", "--help"], capture_output=True, text=True,
                        env={**os.environ, "NODE_DEBUG_NATIVE": "COMPILE_CACHE"}, check=True)
assert result.stderr.count("was accepted") >= len(seed), result.stderr
assert all(path.stat().st_mtime_ns == modified for path, modified in seed.items()), \
    "Node rewrote the image seed instead of reusing it"
print(f"Reused {len(seed)} Node bytecode cache files")
