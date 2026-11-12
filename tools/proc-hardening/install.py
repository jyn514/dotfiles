#!/usr/bin/env python3
"""Build and install the uid-scoped proc read guard."""

import argparse
import os
from pathlib import Path
import pwd
import shlex
import shutil
import stat
import subprocess
import sys


SOURCE = Path(__file__).resolve().parent
ROOT = SOURCE.parents[1]
BUILD_DIR = ROOT / "target/proc-hardening"
LOADER = BUILD_DIR / "proc-read-guard"
UNIT_SOURCE = SOURCE / "proc-read-guard@.service"
INSTALL_LOADER = Path("/usr/local/libexec/proc-read-guard")
INSTALL_UNIT = Path("/etc/systemd/system/proc-read-guard@.service")
LSM_LIST = Path("/sys/kernel/security/lsm")
YAMA_PTRACE_SCOPE = Path("/proc/sys/kernel/yama/ptrace_scope")
INSTALL_BIN = Path("/usr/bin/install")
SYSTEMCTL_BIN = Path("/usr/bin/systemctl")
ELEVATORS = (Path("/usr/bin/sudo"), Path("/usr/bin/doas"))


def command(*args: object, input_data: bytes | None = None) -> None:
    subprocess.run([str(arg) for arg in args], input=input_data, check=True)


def elevated_command(*args: object, input_data: bytes | None = None) -> None:
    argv = [str(arg) for arg in args]
    print(f"setup: elevated command: {shlex.join(argv)}", file=sys.stderr)
    command(*argv, input_data=input_data)


def require_command(name: str) -> None:
    if shutil.which(name) is None:
        raise ValueError(f"{name} is required")


def require_linux_bpf_build() -> None:
    if not sys.platform.startswith("linux"):
        raise ValueError("proc-read-guard only supports Linux")
    if not Path("/sys/kernel/btf/vmlinux").is_file():
        raise ValueError("/sys/kernel/btf/vmlinux is required")
    if "bpf" not in LSM_LIST.read_text().strip().split(","):
        raise ValueError("the running kernel must load the bpf LSM")
    if YAMA_PTRACE_SCOPE.read_text().strip() != "1":
        raise ValueError("kernel.yama.ptrace_scope must be 1")
    for name in ("make", "clang", "bpftool", "pkg-config"):
        require_command(name)
    if subprocess.run(["pkg-config", "--atleast-version=1.0", "libbpf"]).returncode != 0:
        raise ValueError("libbpf >= 1.0 development files are required")


def build() -> Path:
    require_linux_bpf_build()
    command("make", "-C", str(SOURCE))
    info = LOADER.stat()
    if not stat.S_ISREG(info.st_mode) or (info.st_mode & 0o111) == 0:
        raise ValueError(f"build did not produce an executable loader: {LOADER}")
    return LOADER


def require_trusted_executable(path: Path) -> Path:
    resolved = path.resolve(strict=True)
    info = resolved.stat()
    if not stat.S_ISREG(info.st_mode) or (info.st_mode & 0o111) == 0:
        raise ValueError(f"trusted executable is not runnable: {resolved}")
    if info.st_uid != 0 or info.st_mode & 0o022:
        raise ValueError(f"trusted executable must be root-owned and not writable by others: {resolved}")
    return resolved


def read_regular_file(path: Path, *, executable: bool = False) -> bytes:
    with path.open("rb") as input_file:
        info = os.fstat(input_file.fileno())
        if not stat.S_ISREG(info.st_mode):
            raise ValueError(f"expected a regular file: {path}")
        if executable and (info.st_mode & 0o111) == 0:
            raise ValueError(f"loader artifact is not executable: {path}")
        return input_file.read()


def find_elevator() -> Path:
    for candidate in ELEVATORS:
        try:
            return require_trusted_executable(candidate)
        except FileNotFoundError:
            continue
    raise ValueError("installing proc-read-guard requires sudo or doas")


def publish(elevator: Path, contents: bytes, destination: Path, mode: int) -> None:
    elevated_command(
        elevator,
        INSTALL_BIN,
        "-D",
        "-m",
        f"{mode:04o}",
        "/dev/stdin",
        destination,
        input_data=contents,
    )


def systemctl(elevator: Path, *args: str) -> None:
    elevated_command(elevator, SYSTEMCTL_BIN, *args)


def install(owner: str, loader: bytes, unit_source: bytes) -> None:
    account = pwd.getpwnam(owner)
    if account.pw_uid == 0:
        raise ValueError("proc-read-guard must protect an unprivileged user")
    elevator = find_elevator()
    require_trusted_executable(INSTALL_BIN)
    require_trusted_executable(SYSTEMCTL_BIN)
    # Root only receives the already-read bytes below; it never reopens the
    # user-writable checkout after the privilege boundary.
    publish(elevator, loader, INSTALL_LOADER, 0o755)
    publish(elevator, unit_source, INSTALL_UNIT, 0o644)
    unit = f"proc-read-guard@{account.pw_uid}.service"
    systemctl(elevator, "daemon-reload")
    systemctl(elevator, "enable", unit)
    systemctl(elevator, "reload-or-restart", unit)
    systemctl(elevator, "is-enabled", unit)
    systemctl(elevator, "is-active", unit)
    print(f"proc-read-guard: {unit} is active")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--owner",
        default=os.environ.get("SUDO_USER") or pwd.getpwuid(os.getuid()).pw_name,
    )
    args = parser.parse_args()
    if os.geteuid() == 0:
        raise ValueError("run ./setup proc-hardening without sudo")
    artifact = build()
    loader = read_regular_file(artifact, executable=True)
    unit_source = read_regular_file(UNIT_SOURCE)
    install(args.owner, loader, unit_source)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print(f"proc-read-guard setup failed: {error}", file=sys.stderr)
        raise SystemExit(1)
