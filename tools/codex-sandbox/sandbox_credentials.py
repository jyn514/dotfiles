"""Keychain persistence and a guest-owned cache lasting one Lima VM boot."""

import json
from pathlib import Path
import selectors
import struct
import subprocess
import sys

from keychain import Keychain, validate_token


GUEST_HELPER = "/usr/local/share/codex-sandbox/boot-credential.py"


def import_podman_token(keychain=None):
    # Capture only in memory. Never include stdout/stderr in an exception: a
    # failed producer is not allowed to turn its secret output into diagnostics.
    result = subprocess.run(["podman", "secret", "inspect", "--showsecret", "--format",
                             "{{.SecretData}}", "codex-github-token"],
                            capture_output=True, timeout=30)
    if result.returncode:
        raise ValueError("could not read the existing Podman GitHub secret")
    token = result.stdout.removesuffix(b"\n")
    validate_token(token)
    (keychain or Keychain()).import_token(token)


def boot_credential(runtime, *, retrieve=None, invalidate=False):
    runtime.verify()
    if "boot-credential.py" not in runtime.record["files"]:
        raise ValueError("Lima host predates boot credentials; provision a new host before migration")
    boot = runtime.guest(["cat", "/proc/sys/kernel/random/boot_id"],
                         capture_output=True, text=True).stdout.strip()
    uid = runtime.guest(["id", "-u"], capture_output=True, text=True).stdout.strip()
    if not uid.isdecimal():
        raise ValueError("guest returned an invalid credential owner")
    generation = runtime.record["generation"]
    expected = f"/run/user/{uid}/codex-sandbox-credentials/{generation}/{boot}/github-token"
    operation = "invalidate" if invalidate else "ensure"
    argv = runtime.host.guest_argv(runtime.record, "python3", GUEST_HELPER,
                                  operation, generation, boot)
    process = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        # The guest holds the cache lock while approval is pending. Other
        # launchers wait here and consume the completed cache without retrieval.
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            if not selector.select(timeout=600):
                raise ValueError("timed out waiting for the guest credential cache")
        response = json.loads(process.stdout.readline(4096))
        if response.get("path") != expected:
            raise ValueError("guest credential cache has a different boot identity")
        status = response.get("status")
        if status == "missing" and not invalidate:
            token = (retrieve or Keychain().retrieve)()
            validate_token(token)
            output, _ = process.communicate(struct.pack("!I", len(token)) + token, timeout=30)
            if json.loads(output) != {"status": "ready", "path": expected}:
                raise ValueError("guest credential transfer was not published")
        elif status == ("invalidated" if invalidate else "ready"):
            output, _ = process.communicate(timeout=30)
            if output:
                raise ValueError("unexpected guest credential response")
        else:
            raise ValueError("invalid guest credential response")
        if process.returncode:
            raise ValueError("guest credential operation failed")
        return None if invalidate else Path(expected)
    finally:
        # EOF aborts an incomplete transfer and releases the guest lock. Await
        # the producer before another launch can attempt cache publication.
        if process.poll() is None:
            if process.stdin and not process.stdin.closed:
                process.stdin.close()
                process.stdin = None
            try:
                process.communicate(timeout=30)
            except subprocess.TimeoutExpired:
                process.kill()
                process.communicate()
                print("credential transport did not exit; guest transfer will fail on EOF", file=sys.stderr)


def main():
    import argparse
    from sandbox_runtime import image_runtime

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--provider', choices=('lima', 'lima-docker'), default='lima')
    parser.add_argument("--state", type=Path)
    parser.add_argument("operation", choices=("import-podman", "prepare", "invalidate"))
    args = parser.parse_args()
    if args.operation == "import-podman":
        import_podman_token()
        print("Imported GitHub token into Keychain; Podman rollback secret retained.")
    else:
        boot_credential(image_runtime(args.provider, args.state), invalidate=args.operation == "invalidate")
        print("Guest boot credential " + ("invalidated." if args.operation == "invalidate" else "ready."))


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, subprocess.SubprocessError):
        sys.exit("GitHub credential operation failed; no plaintext fallback is permitted")
