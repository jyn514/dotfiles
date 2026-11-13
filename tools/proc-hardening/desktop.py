#!/usr/bin/python3
"""Launch fixed desktop applications through supplementary-group system services.

The socket worker runs only after systemd changes uid and groups. Neither this
module nor its request parser runs as root. See README.md for installation and
storage requirements. The basename entrypoints forward all arguments unchanged.
"""

from __future__ import annotations

import argparse
import array
import configparser
from dataclasses import dataclass
import grp
import json
import os
from pathlib import Path
import pwd
import re
import socket
import stat
import struct
import subprocess
import sys


INSTALLED = Path("/usr/local/libexec/dotfiles-private-desktop")
PRIVATE_STORAGE = Path("/var/lib/glide-private")
MAX_FRAME = 256 * 1024
REQUEST_TIMEOUT = 10
ENVIRONMENT = frozenset({
    "PATH", "LANG", "LANGUAGE", "DISPLAY", "WAYLAND_DISPLAY", "XAUTHORITY",
    "DBUS_SESSION_BUS_ADDRESS", "XDG_RUNTIME_DIR", "XDG_SESSION_TYPE",
    "XDG_CURRENT_DESKTOP", "XDG_SESSION_DESKTOP", "DESKTOP_SESSION",
    "XDG_DATA_DIRS", "XDG_DATA_HOME", "XDG_CACHE_HOME",
    "XDG_ACTIVATION_TOKEN", "DESKTOP_STARTUP_ID", "GDK_BACKEND",
    "GDK_SCALE", "GDK_DPI_SCALE", "QT_QPA_PLATFORM", "SSH_AUTH_SOCK",
})


@dataclass(frozen=True)
class Application:
    executable: str
    group: str
    arguments: tuple[str, ...] = ()
    private_profiles: bool = False


APPLICATIONS = {
    "glide": Application("/opt/glide-browser-bin/glide-bin", "browser", private_profiles=True),
    "onepassword": Application("/opt/1Password/1password", "onepassword"),
}
ENTRYPOINTS = {"glide-bin": "glide", "1password": "onepassword"}


def socket_path(app: str, uid: int) -> Path:
    return Path(f"/run/dotfiles-private-desktop-{uid}/{app}.sock")


def allowed_environment(name: str) -> bool:
    return name in ENVIRONMENT or re.fullmatch(r"LC_[A-Z_]+", name) is not None


def string(value: object) -> bool:
    return isinstance(value, str) and "\0" not in value


def parse_request(value: object) -> dict:
    """Recognize the complete private request before creating any subprocess."""
    if not isinstance(value, dict) or set(value) != {"argv", "cwd", "env"}:
        raise ValueError("expected argv, cwd, and env")
    argv, cwd, env = value["argv"], value["cwd"], value["env"]
    if not isinstance(argv, list) or not all(string(arg) for arg in argv):
        raise ValueError("argv must contain strings without NUL")
    if not string(cwd) or not os.path.isabs(cwd):
        raise ValueError("cwd must be an absolute path")
    if not isinstance(env, dict) or not all(
        string(key) and allowed_environment(key) and string(item)
        for key, item in env.items()
    ):
        raise ValueError("unsupported environment variable or value")
    return value


def read_exact(connection: socket.socket, length: int) -> bytes:
    result = bytearray()
    while len(result) < length:
        chunk = connection.recv(length - len(result))
        if not chunk:
            raise ValueError("incomplete request or response")
        result.extend(chunk)
    return bytes(result)


def send_frame(connection: socket.socket, value: dict) -> None:
    data = json.dumps(value, ensure_ascii=True).encode("ascii")
    if len(data) > MAX_FRAME:
        raise ValueError("request or response exceeds 256 KiB")
    connection.sendall(struct.pack("!I", len(data)) + data)


def receive_frame(connection: socket.socket) -> object:
    length, = struct.unpack("!I", read_exact(connection, 4))
    if length > MAX_FRAME:
        raise ValueError("request or response exceeds 256 KiB")
    return json.loads(read_exact(connection, length))


def receive_stdio(connection: socket.socket) -> list[int]:
    """Receive exactly stdin/out/err; caller closes all returned descriptors."""
    descriptors: list[int] = []
    try:
        data, ancillary, flags, _ = connection.recvmsg(
            1, socket.CMSG_SPACE(3 * array.array("i").itemsize), socket.MSG_CMSG_CLOEXEC
        )
        for level, kind, payload in ancillary:
            if level != socket.SOL_SOCKET or kind != socket.SCM_RIGHTS:
                raise ValueError("unexpected socket control message")
            values = array.array("i")
            values.frombytes(payload[:len(payload) - len(payload) % values.itemsize])
            descriptors.extend(values)
        if data != b"S" or flags & socket.MSG_CTRUNC or len(descriptors) != 3:
            raise ValueError("expected exactly three standard-stream descriptors")
        return descriptors
    except BaseException:
        for descriptor in descriptors:
            os.close(descriptor)
        raise


def check_identity(application: Application, account: pwd.struct_passwd) -> None:
    if account.pw_uid == 0 or os.getresuid() != (account.pw_uid,) * 3:
        raise ValueError("worker must run as the desktop user, never root")
    if os.getresgid() != (account.pw_gid,) * 3:
        raise ValueError("worker primary gids must match the desktop user")
    if grp.getgrnam(application.group).gr_gid not in os.getgroups():
        raise ValueError(f"worker is missing supplementary group {application.group}")


def registered_profiles(registry: Path) -> set[Path]:
    """Resolve every registered profile and installation default, including links."""
    parser = configparser.ConfigParser(interpolation=None)
    with (registry / "profiles.ini").open() as source:
        parser.read_file(source)
    profiles = set()
    for section in parser.sections():
        if section.startswith("Profile"):
            path = Path(parser.get(section, "Path"))
            relative = parser.get(section, "IsRelative")
            if relative not in ("0", "1") or (relative == "0") != path.is_absolute():
                raise ValueError(f"invalid profile path in {section}")
            profiles.add((registry / path if relative == "1" else path).resolve(strict=True))
        elif section.startswith("Install") and parser.has_option(section, "Default"):
            path = Path(parser.get(section, "Default"))
            profiles.add((registry / path).resolve(strict=True))
    installs = registry / "installs.ini"
    if installs.exists():
        installed = configparser.ConfigParser(interpolation=None)
        with installs.open() as source:
            installed.read_file(source)
        for section in installed.sections():
            if installed.has_option(section, "Default"):
                profiles.add((registry / installed.get(section, "Default")).resolve(strict=True))
    if not profiles:
        raise ValueError("profile registry contains no profiles")
    return profiles


def check_registered_profiles(registry: Path, storage: Path) -> None:
    if not (registry / "profiles.ini").exists() and not any(registry.iterdir()):
        # A fresh installation initializes its registry on first launch. The
        # caller checks the protected parent and registry link before this.
        return
    for profile in registered_profiles(registry):
        if not profile.is_relative_to(storage) or not profile.is_dir():
            raise ValueError(f"registered profile is outside protected storage: {profile}")


def check_profiles(account: pwd.struct_passwd, group: str) -> None:
    parent = PRIVATE_STORAGE.stat()
    if (parent.st_uid, parent.st_gid, stat.S_IMODE(parent.st_mode)) != (
        0, grp.getgrnam(group).gr_gid, 0o710
    ) or PRIVATE_STORAGE.is_symlink():
        raise ValueError(f"{PRIVATE_STORAGE} must be root:{group}, mode 0710")
    registry = Path(account.pw_dir) / ".config/glide/glide"
    if registry.resolve(strict=True) != PRIVATE_STORAGE / "profiles":
        raise ValueError(f"profile migration required: {registry} must link to {PRIVATE_STORAGE / 'profiles'}")
    check_registered_profiles(registry, PRIVATE_STORAGE / "profiles")


def application_arguments(application: Application, argv: list[str], env: dict) -> list[str]:
    if application == APPLICATIONS["onepassword"]:
        # Electron debug switches can execute arbitrary commands with the trusted
        # group. The desktop entry only needs --silent and its two URI schemes.
        if not all(arg == "--silent" or re.match(r"onepassword(?:8)?:", arg) for arg in argv):
            raise ValueError("1Password accepts only --silent and onepassword:/onepassword8: URLs")
        ozone = ["--ozone-platform=wayland"] if env.get("WAYLAND_DISPLAY") else []
        return [*application.arguments, *ozone, *argv]
    return [*application.arguments, *argv]


def child_environment(request: dict, account: pwd.struct_passwd) -> dict[str, str]:
    """Keep identity fixed; forward only desktop/session variables, not loaders."""
    runtime = f"/run/user/{account.pw_uid}"
    return {
        "HOME": account.pw_dir,
        "USER": account.pw_name,
        "LOGNAME": account.pw_name,
        "SHELL": account.pw_shell,
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "LANG": "C.UTF-8",
        "XDG_RUNTIME_DIR": runtime,
        "DBUS_SESSION_BUS_ADDRESS": f"unix:path={runtime}/bus",
        **request["env"],
    }


def serve(connection: socket.socket, application: Application,
          account: pwd.struct_passwd) -> int:
    """Handle one connection and retain its app in the service until app exit.

    Disconnecting the client does not terminate the app. Passed standard streams
    preserve CLI output without giving the app the request socket. The service,
    not the requesting process, is the app's ancestor for proc-read protection.
    """
    descriptors: list[int] = []
    child = None
    try:
        connection.settimeout(REQUEST_TIMEOUT)
        _, uid, _ = struct.unpack("3i", connection.getsockopt(
            socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i")
        ))
        if uid != account.pw_uid:
            raise ValueError("request uid does not match service uid")
        check_identity(application, account)
        descriptors = receive_stdio(connection)
        request = parse_request(receive_frame(connection))
        if connection.recv(1):
            raise ValueError("unexpected data after request")
        if application.private_profiles:
            check_profiles(account, application.group)
        env = child_environment(request, account)
        arguments = application_arguments(application, request["argv"], env)
        child = subprocess.Popen(
            [application.executable, *arguments],
            cwd=request["cwd"], env=env,
            stdin=descriptors[0], stdout=descriptors[1], stderr=descriptors[2],
            close_fds=True,
        )
        for descriptor in descriptors:
            os.close(descriptor)
        descriptors.clear()
        try:
            send_frame(connection, {"started": child.pid})
        except OSError:
            pass
        code = child.wait()
        try:
            send_frame(connection, {"exit": code if code >= 0 else 128 - code})
        except OSError:
            pass
        return 0
    except (OSError, ValueError, KeyError, configparser.Error) as error:
        if child is not None:
            child.wait()
        try:
            send_frame(connection, {"error": str(error)})
        except OSError:
            pass
        print(f"private-desktop: {error}", file=sys.stderr)
        return 1
    finally:
        for descriptor in descriptors:
            os.close(descriptor)


def launch(app: str, argv: list[str], path: Path | None = None) -> int:
    request = parse_request({
        "argv": argv,
        "cwd": os.getcwd(),
        "env": {key: value for key, value in os.environ.items() if allowed_environment(key)},
    })
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.settimeout(REQUEST_TIMEOUT)
        connection.connect(str(path or socket_path(app, os.getuid())))
        descriptors = array.array("i", (0, 1, 2))
        connection.sendmsg([b"S"], [(socket.SOL_SOCKET, socket.SCM_RIGHTS, descriptors)])
        send_frame(connection, request)
        connection.shutdown(socket.SHUT_WR)
        response = receive_frame(connection)
        if not isinstance(response, dict) or "started" not in response:
            raise ValueError(response.get("error", "invalid launch response") if isinstance(response, dict) else "invalid launch response")
        connection.settimeout(None)
        response = receive_frame(connection)
        if not isinstance(response, dict) or type(response.get("exit")) is not int:
            raise ValueError("invalid exit response")
        return response["exit"]


def render_units(uid: int, gid: int) -> dict[str, str]:
    """Render per-account fixed services; no request text enters systemd syntax."""
    if uid <= 0 or gid <= 0:
        raise ValueError("desktop uid and primary gid must be non-root")
    result = {}
    for name, application in APPLICATIONS.items():
        unit = f"private-desktop-{uid}-{name}"
        result[f"{unit}.socket"] = (
            f"[Unit]\nDescription=Private desktop launch socket ({name}, uid {uid})\n\n"
            f"[Socket]\nListenStream={socket_path(name, uid)}\n"
            f"SocketUser={uid}\nSocketMode=0600\nDirectoryMode=0755\n"
            "Accept=yes\nRemoveOnStop=yes\nMaxConnections=64\n\n"
            "[Install]\nWantedBy=sockets.target\n"
        )
        result[f"{unit}@.service"] = (
            f"[Unit]\nDescription=Private desktop launch ({name}, uid {uid})\n"
            f"Requires=proc-read-guard@{uid}.service\nAfter=proc-read-guard@{uid}.service\n\n"
            f"[Service]\nType=exec\nUser={uid}\nGroup={gid}\n"
            f"SupplementaryGroups={application.group}\n"
            f"ExecStart=/usr/bin/python3 -I {INSTALLED} serve {name}\n"
            "StandardInput=socket\nStandardOutput=journal\nStandardError=journal\n"
        )
    return result


def main() -> int:
    entry = ENTRYPOINTS.get(Path(sys.argv[0]).name)
    if entry is not None:
        if not INSTALLED.exists():
            # The tracked PATH wrapper can precede rollout. Once installed,
            # unavailable sockets are errors, never unprotected native launches.
            os.execv(APPLICATIONS[entry].executable, [APPLICATIONS[entry].executable, *sys.argv[1:]])
        # Client and worker use the same installed protocol version even when
        # this live checkout changes before the next privileged installation.
        os.execv("/usr/bin/python3", ["/usr/bin/python3", "-I", str(INSTALLED), "launch", entry, "--", *sys.argv[1:]])
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    worker = commands.add_parser("serve", help="systemd worker (not for direct use)")
    worker.add_argument("app", choices=APPLICATIONS)
    client = commands.add_parser("launch", help="launch an app and preserve its exit status and standard streams")
    client.add_argument("app", choices=APPLICATIONS)
    client.add_argument("argv", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if args.command == "serve":
        with socket.socket(fileno=0) as connection:
            return serve(connection, APPLICATIONS[args.app], pwd.getpwuid(os.getuid()))
    argv = args.argv[1:] if args.argv[:1] == ["--"] else args.argv
    return launch(args.app, argv)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError) as error:
        sys.exit(f"private-desktop: {error}")
    except KeyboardInterrupt:
        sys.exit(130)
