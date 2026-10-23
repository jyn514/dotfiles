"""Retrieve a host credential and stage it in guest tmpfs for one launch."""

import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import selectors
import stat
import struct
import subprocess
import sys

from keychain import Keychain, KeychainError, validate_token


GUEST_HELPER = "/usr/local/share/codex-sandbox/boot-credential.py"
GUEST_ENTRYPOINT = Path(__file__).with_name('lima') / 'current-boot-credential.py'
GUEST_HELPER_SOURCE = Path(__file__).with_name('lima') / 'boot-credential.py'
ONEPASSWORD_GITHUB_TOKEN = "op://Private/agent sandbox token/token"
LINUX_GITHUB_TOKEN = Path.home() / ".config/codex-sandbox/github-token"


def credential_path(value, generation, request=None):
    # The same guest owns UID, boot identity, and the installed cache helper.
    # Accept only its fixed cache namespace in the requested VM generation.
    if not isinstance(value, str) or not re.fullmatch(
            rf'/run/user/[0-9]+/codex-sandbox-credentials/{re.escape(generation)}/'
            r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/'
            + ('github-token' if request is None else rf'github-token-{re.escape(request)}'), value):
        raise ValueError('guest credential staging has an invalid identity')
    return value


def retrieve_host_token():
    if sys.platform == "darwin":
        try:
            return Keychain().retrieve()
        except KeychainError as error:
            if "OSStatus -25300" in str(error):
                return None
            raise
    if sys.platform == "linux":
        if LINUX_GITHUB_TOKEN.exists():
            flags = os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0)
            descriptor = os.open(LINUX_GITHUB_TOKEN, flags)
            try:
                metadata = os.fstat(descriptor)
                if (not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.getuid() or
                        metadata.st_nlink != 1 or stat.S_IMODE(metadata.st_mode) != 0o600):
                    raise ValueError("sandbox GitHub token file has unsafe ownership or permissions")
                token = os.read(descriptor, 16385).removesuffix(b"\n")
                if os.read(descriptor, 1):
                    raise ValueError("sandbox GitHub token file is too large")
            finally:
                os.close(descriptor)
            validate_token(token)
            return token
        # Capture and discard all diagnostics: an unexpected CLI failure must
        # never turn secret output into a launcher error or terminal log.
        result = subprocess.run(["op", "read", ONEPASSWORD_GITHUB_TOKEN],
                                capture_output=True, timeout=30)
        if result.returncode:
            raise ValueError("could not retrieve the sandbox GitHub token from 1Password")
        token = result.stdout.removesuffix(b"\n")
        validate_token(token)
        return token
    return None


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
    files = runtime.record["files"]
    expected = hashlib.sha256(GUEST_HELPER_SOURCE.read_bytes()).hexdigest()
    if not isinstance(files, dict) or files.get("boot-credential.py") != expected:
        raise ValueError("installed Lima credential helper does not match this launcher; upgrade the host")
    generation = runtime.record["generation"]
    operation = "invalidate" if invalidate else "stage"
    request = None if invalidate else secrets.token_hex(16)
    argv = runtime.host.guest_argv(runtime.record, 'python3', '-c', GUEST_ENTRYPOINT.read_text(),
                                  GUEST_HELPER, operation, generation, *([] if request is None else [request]))
    process = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        # The guest holds the cache lock while approval is pending. Other
        # launchers wait here and consume the completed cache without retrieval.
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            if not selector.select(timeout=600):
                raise ValueError("timed out waiting for guest credential staging")
        response = json.loads(process.stdout.readline(4096))
        expected_path = credential_path(response.get('path'), generation, request)
        status = response.get("status")
        if status == "receive" and not invalidate:
            token = (retrieve or retrieve_host_token)()
            if token is None:
                return None
            validate_token(token)
            output, _ = process.communicate(struct.pack("!I", len(token)) + token, timeout=30)
            if json.loads(output) != {"status": "ready", "path": expected_path}:
                raise ValueError("guest credential transfer was not published")
        elif invalidate and status == "invalidated":
            output, _ = process.communicate(timeout=30)
            if output:
                raise ValueError("unexpected guest credential response")
        else:
            raise ValueError("invalid guest credential response")
        if process.returncode:
            raise ValueError("guest credential operation failed")
        return None if invalidate else Path(expected_path)
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
        for stream in (process.stdin, process.stdout, process.stderr):
            if stream is not None:
                stream.close()


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
        result = boot_credential(image_runtime(args.provider, args.state), invalidate=args.operation == "invalidate")
        if result is None and args.operation == "prepare":
            print("[WARN] GitHub token unavailable; skipping optional credential provisioning.", file=sys.stderr)
        else:
            print("Guest boot credential " + ("invalidated." if args.operation == "invalidate" else "ready."))


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, subprocess.SubprocessError):
        sys.exit("GitHub credential operation failed; no plaintext fallback is permitted")
