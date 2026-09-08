"""Opt-in macOS Keychain test; owns a disposable keychain and dummy token only."""

from contextlib import ExitStack
import ctypes as c
from pathlib import Path
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from keychain import Keychain, KeychainError


def main():
    with tempfile.TemporaryDirectory(prefix="sandbox-keychain-") as temporary:
        path = Path(temporary) / "owned.keychain-db"
        # Explicit paths keep both creation and all item access out of login.
        subprocess.run(["security", "create-keychain", "-p", "owned-test-password", str(path)], check=True)
        try:
            keychain = Keychain(path)
            keychain.bind(keychain.sec, "SecKeychainSetUserInteractionAllowed", c.c_int32, c.c_bool)
            keychain.check(keychain.sec.SecKeychainSetUserInteractionAllowed(False))
            keychain.import_token(b"owned-dummy-github-token")
            with ExitStack() as stack:
                keychain.check_access(stack, keychain.find(stack))
            try:
                keychain.retrieve()
            except KeychainError:
                pass
            else:
                raise AssertionError("empty application ACL allowed unprompted retrieval")
            try:
                keychain.import_token(b"different-dummy-token")
            except KeychainError:
                pass
            else:
                raise AssertionError("import overwrote an existing credential")
            subprocess.run(["security", "add-generic-password", "-a", "unsafe-dummy", "-s", "codex-sandbox",
                            "-w", "owned-dummy", "-A", str(path)], check=True)
            keychain.ACCOUNT = b"unsafe-dummy"
            try:
                keychain.retrieve()
            except KeychainError as error:
                assert "unprompted" in str(error)
            else:
                raise AssertionError("retrieval accepted a trust-all decrypt ACL")
            print("Native Keychain import, empty decrypt ACL, denied retrieval, and duplicate rejection passed.")
        finally:
            subprocess.run(["security", "delete-keychain", str(path)], check=True)


if __name__ == "__main__":
    main()
