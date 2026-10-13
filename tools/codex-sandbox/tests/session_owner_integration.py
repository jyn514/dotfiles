"""Verify native proxy identity and recorded-owner cleanup on disposable resources."""

import argparse
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from sandbox_runtime import image_runtime, runtime_identity, resource_exists, ResourceKind
from proxy_session import SessionLock

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
        with tempfile.TemporaryDirectory() as directory:
            session = Path(directory)
            metadata = session / "session.json"
            metadata.write_text(json.dumps({"version": 2, "state": state}))
            first = SessionLock(session)
            first.release_coordination()
            second = SessionLock(session)
            try:
                first.finish(lambda: proxies.reset_session(session))
                assert metadata.exists(), "first exit removed shared recovery authority"
                assert runtime.inspect_container(name)["State"]["Running"]
                second.finish(lambda: proxies.reset_session(session))
                assert not metadata.exists(), "final exit retained recovery authority"
                for kind in (ResourceKind.CONTAINER, ResourceKind.VOLUME):
                    assert not resource_exists(runtime, kind, name), f"final exit retained {kind.value}"
            finally:
                first.close()
                second.close()
        print(f"{runtime.provider}: native identity, shared attachment, and final-holder cleanup passed.")
    finally:
        runtime.run(["rm", "--force", name], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        runtime.run(["volume", "rm", name], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", choices=("lima", "lima-docker"), required=True)
    parser.add_argument("--state", type=Path)
    parser.add_argument("--base", required=True)
    args = parser.parse_args()
    exercise(image_runtime(args.provider, args.state), args.base)
