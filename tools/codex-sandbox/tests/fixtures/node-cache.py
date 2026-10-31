"""Run inside a fresh image and verify the worker uses its seeded Node cache."""

from pathlib import Path
import os
import subprocess
import tempfile


version = subprocess.run(["node", "--version"], check=True, capture_output=True, text=True).stdout
if int(version.removeprefix("v").split(".")[0]) < 22:
    print("Skipping Node bytecode probe: this Node version cannot load the worker SDK")
    raise SystemExit(0)

cache = Path("/tmp/pi-node-cache")
seed = {path: path.stat().st_mtime_ns for path in cache.rglob("*") if path.is_file()}
assert seed, "image has no Node bytecode seed"
command = ["node", "/opt/agent-tools/bin/tool-worker.mjs", "--warm-cache"]
result = subprocess.run(command, capture_output=True, text=True,
                        env={**os.environ, "NODE_DEBUG_NATIVE": "COMPILE_CACHE"}, check=True)
assert result.stderr.count("was accepted") >= len(seed), result.stderr
assert all(path.stat().st_mtime_ns == modified for path, modified in seed.items()), \
    "Node rewrote the image seed instead of reusing it"
print(f"Reused {len(seed)} Node bytecode cache files")

with tempfile.TemporaryDirectory() as directory:
    disabled = Path(directory) / "disabled-cache"
    control = subprocess.run(command, capture_output=True, text=True, check=True,
                             env={**os.environ, "NODE_COMPILE_CACHE": str(disabled),
                                  "NODE_DISABLE_COMPILE_CACHE": "1", "NODE_DEBUG_NATIVE": "COMPILE_CACHE"})
    assert "was accepted" not in control.stderr, control.stderr
    assert not disabled.exists(), "disabled cache still created files"
