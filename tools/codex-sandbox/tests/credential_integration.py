"""Dummy credential contract against an owned, already provisioned Lima host."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import subprocess
import struct
import sys
import threading
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sandbox_credentials import boot_credential, GUEST_HELPER
from sandbox_runtime import Lima


def guest_fails(runtime, arguments):
    try:
        runtime.guest(arguments, capture_output=True)
    except subprocess.CalledProcessError:
        return True
    return False


def exercise(state, base):
    runtime = Lima(state)
    count = 0
    lock = threading.Lock()
    def retrieve():
        nonlocal count
        with lock:
            count += 1
        return b"owned-dummy-github-token"
    with ThreadPoolExecutor(max_workers=4) as executor:
        paths = list(executor.map(lambda _: boot_credential(runtime, retrieve=retrieve), range(4)))
    assert count == 1 and len(set(paths)) == 1, "concurrent launches repeated credential retrieval"
    path = paths[0]
    name = "owned-credential-" + uuid.uuid4().hex
    probe = runtime.host.state / "scratch/credential-probe.py"
    probe.write_bytes(Path(__file__).with_name("credential_guest.py").read_bytes())
    image = runtime.resolve_image(base)
    try:
        with runtime.workload(image, name, ["--network", "none", "--cap-drop=ALL",
                "--security-opt=no-new-privileges", "--read-only",
                "--mount", f"type=bind,src={path},dst=/run/secrets/github-token,readonly",
                "--mount", f"type=bind,src={probe},dst=/probe.py,readonly"],
                ["python3", "/probe.py"], stdout=subprocess.PIPE) as process:
            output = process.communicate(timeout=30)[0]
            assert process.returncode == 0, "credential injection failed"
            assert b"owned-dummy-github-token" not in output
            metadata = runtime.run(["inspect", "--mode=native", name], capture_output=True).stdout
            assert "owned-dummy-github-token" not in metadata, "token persisted in containerd metadata"
        assert boot_credential(runtime, retrieve=retrieve) == path
        assert count == 1, "session cleanup discarded the boot credential"
        boot_credential(runtime, invalidate=True)
        # A real transfer whose producer exits before its advertised length
        # must release the guest lock without publishing a partial credential.
        try:
            runtime.guest(["python3", GUEST_HELPER, "ensure", runtime.record["generation"], path.parent.name],
                          input=struct.pack("!I", 20) + b"partial", capture_output=True)
        except subprocess.CalledProcessError:
            pass
        else:
            raise AssertionError("interrupted transfer succeeded")
        assert guest_fails(runtime, ["test", "-e", str(path)])
        def denied():
            raise ValueError("owned denied approval")
        try:
            boot_credential(runtime, retrieve=denied)
        except ValueError:
            pass
        else:
            raise AssertionError("denied approval succeeded")
        assert guest_fails(runtime, ["test", "-e", str(path)])
        assert boot_credential(runtime, retrieve=retrieve) == path
        assert count == 2, "denied transfer left a usable cache"
        # Leave a populated cache for the caller's reboot test.
        print("Concurrent retrieval, read-only injection, metadata exclusion, session reuse, denial, and retry passed.", flush=True)
        return str(path)
    finally:
        probe.unlink(missing_ok=True)


def reject_previous_boot(state, path):
    runtime = Lima(state)
    assert guest_fails(runtime, ["test", "-e", path]), "cache survived VM reboot"
    old_boot = Path(path).parent.name
    assert guest_fails(runtime, ["python3", GUEST_HELPER, "ensure", runtime.record["generation"], old_boot]), "stale boot identity was accepted"


if __name__ == "__main__":
    exercise(Path(sys.argv[1]), sys.argv[2])
