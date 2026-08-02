"""Build a validated Oryx source archive and optionally flash it with QMK."""

from __future__ import annotations

import fcntl
import os
from pathlib import Path
from pathlib import PurePosixPath
import secrets
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
from typing import Any
from typing import BinaryIO
from typing import Callable
from urllib.parse import quote
import urllib.error
import urllib.request
from zipfile import BadZipFile
from zipfile import ZipFile
from zipfile import ZipInfo

import oryx_sync
import patch_keymap


ROOT = Path(__file__).resolve().parents[2]
TOOL_DIR = Path(__file__).resolve().parent
SNAPSHOT = ROOT / "lib/moonlander-layout.json"
ADDITIONS = ROOT / "lib/keymap-additions.c"
KEYBOARD = "zsa/moonlander/reva"
QMK_BRANCH = "firmware25"


class FlashError(RuntimeError):
    pass


class CommandFailure(FlashError):
    def __init__(self, status: int, operation: str):
        super().__init__(f"{operation} failed with status {status}")
        self.status = status


def exit_status(returncode: int) -> int:
    return returncode if returncode >= 0 else 128 - returncode


def run(
    arguments: list[str],
    *,
    cwd: Path | None = None,
    environment: dict[str, str] | None = None,
    stdout: int | BinaryIO | None = None,
) -> int:
    if os.environ.get("V") == "1":
        print("+ " + shlex.join(arguments), file=sys.stderr)
    try:
        result = subprocess.run(
            arguments,
            cwd=cwd,
            env=environment,
            check=False,
            stdout=stdout,
        )
    except OSError as error:
        print(f"flash-moonlander: could not execute {arguments[0]!r}: {error}", file=sys.stderr)
        return 127 if isinstance(error, FileNotFoundError) else 126
    return exit_status(result.returncode)


def require_success(status: int, operation: str) -> None:
    if status:
        raise CommandFailure(status, operation)


def identifier(value: object, field: str) -> str:
    allowed = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"
    if not isinstance(value, str) or not value or any(character not in allowed for character in value):
        raise FlashError(f"Oryx returned an unsafe {field}")
    return value


def latest_revision(client: oryx_sync.GraphQLClient) -> tuple[str, str]:
    snapshot = oryx_sync.load_snapshot(SNAPSHOT)
    oryx_sync.validate_snapshot(snapshot)
    _, raw = oryx_sync.fetch_snapshot(client, snapshot)
    layout = identifier(snapshot["layout"]["hashId"], "layout ID")
    revision = identifier(raw.get("revision", {}).get("hashId"), "revision ID")
    return layout, revision


def safe_member(member: ZipInfo) -> bool:
    path = PurePosixPath(member.filename)
    mode = member.external_attr >> 16
    return (
        bool(path.parts)
        and not path.is_absolute()
        and ".." not in path.parts
        and "\\" not in member.filename
        and not stat.S_ISLNK(mode)
    )


def archive_root(archive: ZipFile) -> str:
    members = archive.infolist()
    if not members or any(not safe_member(member) for member in members):
        raise FlashError("Oryx archive contains an unsafe path or symlink")
    roots = {PurePosixPath(member.filename).parts[0] for member in members}
    candidates = [
        root
        for root in roots
        if root.startswith("zsa_moonlander_") and root.endswith("_source")
    ]
    if len(roots) != 1 or len(candidates) != 1:
        raise FlashError("Oryx archive must contain exactly one source directory")
    corrupt = archive.testzip()
    if corrupt is not None:
        raise FlashError(f"Oryx archive contains a corrupt member: {corrupt}")
    return candidates[0]


def validate_archive(path: Path) -> str:
    try:
        with ZipFile(path) as archive:
            return archive_root(archive)
    except (BadZipFile, OSError) as error:
        raise FlashError(f"invalid Oryx archive {path}: {error}") from error


def copy_response(response: object, output: BinaryIO) -> None:
    reader = getattr(response, "read", None)
    if reader is None:
        raise FlashError("Oryx archive response is not readable")
    while chunk := reader(1024 * 1024):
        output.write(chunk)


def ensure_archive(
    revision: str,
    destination: Path,
    opener: Callable[[str], Any] = urllib.request.urlopen,
) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    lock_path = destination.with_name(destination.name + ".lock")
    with lock_path.open("a+b") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            validate_archive(destination)
            return destination
        except FlashError:
            pass

        pending: Path | None = None
        descriptor: int | None = None
        try:
            descriptor, name = tempfile.mkstemp(
                prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent
            )
            pending = Path(name)
            url = f"https://oryx.zsa.io/source/{quote(revision, safe='')}"
            with opener(url) as response:
                with os.fdopen(descriptor, "wb") as output:
                    descriptor = None
                    copy_response(response, output)
                    output.flush()
                    os.fsync(output.fileno())
            validate_archive(pending)
            pending.replace(destination)
            pending = None
            return destination
        except (OSError, urllib.error.HTTPError, urllib.error.URLError) as error:
            raise FlashError(f"could not download Oryx archive: {error}") from error
        finally:
            if descriptor is not None:
                os.close(descriptor)
            if pending is not None:
                pending.unlink(missing_ok=True)


def extract_archive(archive_path: Path, destination: Path) -> Path:
    try:
        with ZipFile(archive_path) as archive:
            root = archive_root(archive)
            archive.extractall(destination)
    except (BadZipFile, OSError) as error:
        raise FlashError(f"could not extract Oryx archive: {error}") from error
    source = destination / root
    if not source.is_dir():
        raise FlashError("Oryx archive source root is not a directory")
    return source


def patch_source(source: Path) -> None:
    keymap = source / "keymap.c"
    try:
        keymap.write_text(patch_keymap.patch_keymap(keymap.read_text()))
        with keymap.open("a") as output, ADDITIONS.open() as additions:
            shutil.copyfileobj(additions, output)
        with (source / "rules.mk").open("a") as rules:
            rules.write(
                "KEY_OVERRIDE_ENABLE = yes\n"
                "UNICODE_COMMON = yes\n"
                "OS_DETECTION_ENABLE = yes\n"
            )
        with (source / "config.h").open("a") as config:
            config.write(
                "#define UNICODE_SELECTED_MODES "
                "UNICODE_MODE_LINUX, UNICODE_MODE_MACOS, UNICODE_MODE_WINCOMPOSE\n"
            )
    except (OSError, UnicodeError, patch_keymap.PatchError) as error:
        raise FlashError(f"could not patch Oryx source: {error}") from error


def install_source(staged: Path, destination: Path) -> None:
    backup = destination.with_name(
        f".{destination.name}.backup-{os.getpid()}-{secrets.token_hex(6)}"
    )
    previous = os.path.lexists(destination)
    try:
        if previous:
            destination.rename(backup)
        staged.rename(destination)
    except OSError as error:
        if previous and backup.exists() and not destination.exists():
            backup.rename(destination)
        raise FlashError(f"could not install patched keymap: {error}") from error
    if backup.exists():
        try:
            shutil.rmtree(backup)
        except OSError as error:
            raise FlashError(f"could not remove replaced keymap: {error}") from error


def qmk_prefix() -> list[str]:
    qmk = shutil.which("qmk")
    return [qmk] if qmk is not None else ["uvx", "qmk"]


def flash(arguments: list[str], client: oryx_sync.GraphQLClient | None = None) -> int:
    if arguments:
        print("usage: flash-moonlander", file=sys.stderr)
        return 2

    require_success(
        run([str(TOOL_DIR / "sync-moonlander")], stdout=subprocess.DEVNULL),
        "layout synchronization check",
    )
    layout, revision = latest_revision(client or oryx_sync.GraphQLClient())

    home = Path.home()
    qmk_home = Path(os.environ.get("QMK_HOME", home / "src/qmk_firmware"))
    qmk = qmk_prefix()
    if not qmk_home.is_dir():
        require_success(
            run(
                [*qmk, "setup", "zsa/qmk_firmware", "-b", QMK_BRANCH, "-H", str(qmk_home)]
            ),
            "QMK setup",
        )

    revision_name = f"{layout}-{revision}"
    keymaps = qmk_home / "keyboards/zsa/moonlander/keymaps"
    if not keymaps.is_dir():
        raise FlashError(f"QMK keymap directory does not exist: {keymaps}")
    destination = keymaps / revision_name
    archive = ensure_archive(revision, home / ".local/share/oryx" / f"{revision}.zip")

    with tempfile.TemporaryDirectory(prefix=f".{revision_name}.", dir=keymaps) as temporary:
        staged = extract_archive(archive, Path(temporary))
        patch_source(staged)
        install_source(staged, destination)

    binary = qmk_home / f"zsa_moonlander_{revision_name}.bin"
    if not binary.exists():
        require_success(
            run(
                [*qmk, "compile", "-kb", KEYBOARD, "-km", revision_name],
                cwd=qmk_home,
            ),
            "QMK compilation",
        )
    if os.environ.get("COMPILE_ONLY") == "1":
        return 0
    environment = os.environ.copy()
    environment["PYTHONWARNINGS"] = "ignore"
    return run(
        [*qmk, "flash", "-kb", KEYBOARD, "-km", revision_name, "-e", "SILENT=true"],
        cwd=qmk_home,
        environment=environment,
    )


def main(arguments: list[str]) -> int:
    try:
        return flash(arguments)
    except CommandFailure as error:
        print(f"flash-moonlander: {error}", file=sys.stderr)
        return error.status
    except (FlashError, oryx_sync.SyncError) as error:
        print(f"flash-moonlander: {error}", file=sys.stderr)
        return 1
