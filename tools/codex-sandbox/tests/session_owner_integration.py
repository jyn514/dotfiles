"""Verify native proxy identity and recorded-owner cleanup on disposable resources."""

import argparse
import importlib.util
from pathlib import Path
import subprocess
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from sandbox_runtime import image_runtime, runtime_identity

spec = importlib.util.spec_from_file_location("proxies", ROOT / "sandbox-proxies.py")
proxies = importlib.util.module_from_spec(spec)
spec.loader.exec_module(proxies)


def exercise(runtime, base):
    name = "owned-session-" + uuid.uuid4().hex
    image = runtime.inspect_image(base)
    state = {"runtime": runtime_identity(runtime), "proxies": [
        {"name": "example", "container": name, "volume": name, "image": image.reference}]}
    try:
        runtime.run(["volume", "create", name], stdout=subprocess.DEVNULL)
        subprocess.run(runtime.workload_argv(image, ["--detach", "--name", name, "--network", "none",
            "--label", "dev.codex.sandbox-proxy=true", "--label", "dev.codex.repository=owned-repository",
            "--label", "dev.codex.command=example", "--mount", f"type=volume,src={name},dst=/owned"],
            ["sleep", "300"]), check=True, stdout=subprocess.DEVNULL)
        proxies.validate_live_proxy(runtime, state["proxies"][0], "owned-repository", "example")
        try:
            proxies.validate_live_proxy(runtime, state["proxies"][0], "another-repository", "example")
        except proxies.ConfigError:
            pass
        else:
            raise AssertionError("native proxy accepted another repository")
        proxies.OUTER_RUNTIME = None  # Cleanup must not consult the caller's default.
        proxies.stop_state(state)
        print(f"{runtime.provider}: native proxy identity and recorded-owner container/volume cleanup passed.")
    finally:
        runtime.run(["rm", "--force", name], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        runtime.run(["volume", "rm", name], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", choices=("podman", "lima"), required=True)
    parser.add_argument("--state", type=Path)
    parser.add_argument("--base", required=True)
    args = parser.parse_args()
    exercise(image_runtime(args.provider, args.state), args.base)
