"""Interactive macOS consent probe using disposable items and dummy values.

Run: python3 tools/codex-sandbox/tests/r2_keychain_consent_probe.py
Observe every dialog; choose Allow once, never Always Allow. The disposable
keychain password is r2-probe-password. Repeat from a restarted terminal session.
Passing this probe does not establish the ACL configuration of production items.
"""

from pathlib import Path
import subprocess
import sys
import tempfile


SECURITY = "/usr/bin/security"
SERVICE = "dev.jyn.flower.r2"
PASSWORD = "r2-probe-password"
DUMMY = b"r2-probe-dummy"


def security(*arguments):
    return subprocess.run(
        [SECURITY, *arguments], stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120,
        env={"PATH": "/usr/bin:/bin"},
    )


def require_success(result):
    if result.returncode:
        raise RuntimeError(f"Keychain setup/cleanup failed (exit {result.returncode})")


def read_item(path, account, action):
    input(f"Next: {account}; choose {action}. Press Enter to start the read. ")
    result = security("find-generic-password", "-s", SERVICE, "-a", account,
                      "-w", str(path))
    expected_success = action == "Allow once"
    if (result.returncode == 0) != expected_success:
        raise RuntimeError("Read outcome did not match the requested action")
    if expected_success and result.stdout.rstrip(b"\r\n") != DUMMY:
        raise RuntimeError("Read returned unexpected dummy data")
    observed = input("Did this read show a confirmation prompt, with Always Allow "
                     "unavailable or unselected? Type yes: ")
    if observed.strip().lower() != "yes":
        raise RuntimeError("Every-read consent was not confirmed")


def main():
    if sys.platform != "darwin":
        raise RuntimeError("This probe requires macOS")
    if not sys.stdin.isatty():
        raise RuntimeError("Run this probe in an interactive terminal")
    with tempfile.TemporaryDirectory(prefix="r2-consent-probe-") as temporary:
        path = Path(temporary) / "owned.keychain-db"
        require_success(security("create-keychain", "-p", PASSWORD, str(path)))
        try:
            for account in ("access-key", "secret-key"):
                require_success(security("add-generic-password", "-s", SERVICE,
                                         "-a", account, "-w", DUMMY.decode(),
                                         "-T", "", str(path)))
            for account in ("access-key", "secret-key"):
                for action in ("Allow once", "Allow once", "Deny", "Allow once",
                               "Cancel", "Allow once"):
                    read_item(path, account, action)
            require_success(security("lock-keychain", str(path)))
            require_success(security("unlock-keychain", "-p", PASSWORD, str(path)))
            for account in ("access-key", "secret-key"):
                read_item(path, account, "Allow once")
            print("Observed consent checks passed for this terminal session.")
            print("Repeat from a restarted terminal and verify production item ACLs "
                  "before declaring the design precondition satisfied.")
        finally:
            require_success(security("delete-keychain", str(path)))


if __name__ == "__main__":
    try:
        main()
    except RuntimeError as error:
        print(f"Probe incomplete: {error}", file=sys.stderr)
        sys.exit(1)
    except (subprocess.TimeoutExpired, EOFError, KeyboardInterrupt) as error:
        print(f"Probe incomplete: {type(error).__name__}", file=sys.stderr)
        sys.exit(1)
