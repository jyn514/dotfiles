#!/usr/bin/env python3
"""Prepare the browser isolation recipe for this user; never invoke sudo."""
from __future__ import annotations

import configparser
from dataclasses import dataclass
import grp
import importlib.util
import os
from pathlib import Path
import pwd
import re
import shutil
import subprocess
import sys
import tempfile

SOURCE = Path(__file__).resolve().parent
ROOT = SOURCE.parents[1]


def sibling(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, SOURCE / filename)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


desktop = sibling("proc_hardening_desktop", "desktop.py")
guard = sibling("proc_hardening_install", "install.py")


@dataclass(frozen=True)
class Step:
    argv: tuple[str, ...]
    root: bool = True
    negate: bool = False


def fish_quote(value: object) -> str:
    text = str(value)
    if re.fullmatch(r"[A-Za-z0-9_./:@+=,-]+", text):
        return text
    return "'" + text.replace("\\", "\\\\").replace("'", "\\'") + "'"


def render_steps(steps: list[Step]) -> str:
    lines = ["# Review and paste this complete block into Fish. Do not sudo this file.",
             "# If anything fails, inspect partial state before retrying.", "begin"]
    for index, step in enumerate(steps):
        prefix = "    " + ("and " if index else "") + ("not " if step.negate else "")
        argv = (("/usr/bin/sudo", "-u", "root", "--") if step.root else ()) + step.argv
        lines.append(prefix + " ".join(fish_quote(value) for value in argv))
    return "\n".join([*lines, "end", "if test $status -ne 0",
                      "    echo 'Installation stopped. Inspect the failed operation before retrying.' >&2",
                      "    /usr/bin/false", "end", ""])


def snapshot(source: Path, destination: Path) -> None:
    subprocess.run(["cp", "--", str(source), str(destination)], check=True)
    subprocess.run(["cmp", "--", str(source), str(destination)], check=True)


def profile_steps(account: pwd.struct_passwd, stage: Path, storage: Path) -> tuple[list[Step], str]:
    """Move the complete native registry tree, or leave an existing install alone.

    This recipe supports the normal ~/.config/glide/glide layout. Stop before
    emitting moves for external profiles or an unexpected existing destination;
    do not rewrite registries or guess how to merge trees.
    """
    registry = Path(account.pw_dir) / ".config/glide/glide"
    destination = storage / "profiles"
    if registry.is_symlink() and Path(os.readlink(registry)) == destination:
        info = storage.stat()
        group = grp.getgrnam(desktop.APPLICATIONS["glide"].group).gr_gid
        if storage.is_symlink() or (info.st_uid, info.st_gid, info.st_mode & 0o777) != (0, group, 0o710):
            raise ValueError(f"invalid managed storage permissions: {storage}")
        return [], "existing protected profiles stay in place"
    if storage.exists() or storage.is_symlink():
        raise ValueError(f"unmanaged or partial installation at {storage}; inspect before retrying")
    if registry.is_symlink():
        raise ValueError(f"unexpected registry symlink: {registry}; inspect before migration")
    mkdir = ("/usr/bin/install", "-d", "-o", str(account.pw_uid), "-g", str(account.pw_gid), "-m", "0700")
    steps = [Step(("/usr/bin/test", "!", "-e", str(destination)))]
    if registry.exists():
        if not registry.is_dir() or registry.stat().st_uid != account.pw_uid:
            raise ValueError(f"registry must be a directory owned by {account.pw_name}: {registry}")
        if any(registry.iterdir()):
            desktop.check_registered_profiles(registry, registry.resolve(strict=True))
        for name in ("profiles.ini", "installs.ini"):
            path = registry / name
            if path.exists():
                before = stage / name
                snapshot(path, before)
                steps.append(Step(("/usr/bin/cmp", "--", str(before), str(path)), root=False))
            else:
                steps.extend([Step(("/usr/bin/test", "!", "-e", str(path)), root=False),
                              Step(("/usr/bin/test", "!", "-L", str(path)), root=False)])
        steps.append(Step(("/usr/bin/mv", "-T", "--", str(registry), str(destination))))
        description = "move the whole native profile tree without changing its contents"
    else:
        steps.extend([Step(("/usr/bin/test", "!", "-e", str(registry)), root=False),
                      Step(("/usr/bin/test", "!", "-L", str(registry)), root=False),
                      Step((*mkdir, str(destination))),
                      Step((*mkdir, str(registry.parent)), root=False)])
        description = "Glide will initialize a fresh protected profile"
    steps.append(Step(("/usr/bin/ln", "-s", "--", str(destination), str(registry)), root=False))
    return steps, description


def prepare(account: pwd.struct_passwd, stage: Path, loader: Path,
            storage: Path = desktop.PRIVATE_STORAGE) -> tuple[Path, str]:
    if account.pw_uid == 0 or account.pw_gid == 0:
        raise ValueError("run setup as the unprivileged desktop user")
    stage.mkdir(parents=True, exist_ok=True)
    migration, description = profile_steps(account, stage, storage)
    for name, source in {"desktop.py": SOURCE / "desktop.py", "proc-read-guard": loader,
                         "proc-read-guard@.service": SOURCE / "proc-read-guard@.service"}.items():
        snapshot(source, stage / name)
    units = desktop.render_units(account.pw_uid, account.pw_gid)
    for name, content in units.items():
        (stage / name).write_text(content)
    steps = []
    if migration:
        for name in ("glide-bin", "1password"):
            steps.append(Step(("/usr/bin/pgrep", "-a", "-u", str(account.pw_uid), "-x", name), root=False, negate=True))
    steps.extend([
        Step(("/usr/bin/groupadd", "--force", "--system", desktop.APPLICATIONS["glide"].group)),
        Step(("/usr/bin/install", "-d", "-o", "root", "-g", desktop.APPLICATIONS["glide"].group, "-m", "0710", str(storage))),
        *migration,
        Step(("/usr/bin/install", "-D", "-o", "root", "-g", "root", "-m", "0755", str(stage / "desktop.py"), str(desktop.INSTALLED))),
        Step(("/usr/bin/install", "-D", "-o", "root", "-g", "root", "-m", "0755", str(stage / "proc-read-guard"), str(guard.INSTALL_LOADER))),
        Step(("/usr/bin/install", "-o", "root", "-g", "root", "-m", "0644", str(stage / "proc-read-guard@.service"), *(str(stage / name) for name in units), "/etc/systemd/system/")),
        Step(("/usr/bin/systemctl", "daemon-reload")),
        Step(("/usr/bin/systemctl", "enable", f"proc-read-guard@{account.pw_uid}.service")),
        Step(("/usr/bin/systemctl", "reload-or-restart", f"proc-read-guard@{account.pw_uid}.service")),
        Step((str(guard.INSTALL_LOADER), "status", str(account.pw_uid))),
        Step(("/usr/bin/systemctl", "enable", "--now", *(name for name in units if name.endswith(".socket")))),
        Step((sys.executable, str(ROOT / "libexec/setup/setup_mimetypes.py"), "--private-desktop-only"), root=False),
    ])
    if cache := shutil.which("kbuildsycoca6"):
        steps.append(Step((cache, "--noincremental"), root=False))
    steps.append(Step(("/usr/bin/printf", "%s\\n", "Installed. Launch Glide and 1Password from the application menu."), root=False))
    commands = stage / "install.fish"
    commands.write_text(render_steps(steps))
    return commands, description


def preflight(account: pwd.struct_passwd) -> None:
    if not sys.platform.startswith("linux") or os.geteuid() == 0:
        raise ValueError("run ./setup private-desktop as the desktop user on Linux, without sudo")
    login_groups = set(os.getgrouplist(account.pw_name, account.pw_gid))
    for name, application in desktop.APPLICATIONS.items():
        if not os.access(application.executable, os.X_OK):
            raise ValueError(f"install the native {name} package first: {application.executable}")
        try:
            group = grp.getgrnam(application.group)
        except KeyError:
            if name == "onepassword":
                raise ValueError("install 1Password with its native onepassword group first") from None
            continue
        if group.gr_gid == 0 or group.gr_gid in {*os.getgroups(), account.pw_gid, *login_groups}:
            raise ValueError(f"{application.group} must not belong to root or the ordinary login session")


def main() -> int:
    if sys.argv[1:]:
        raise ValueError("usage: ./setup private-desktop")
    account = pwd.getpwuid(os.getuid())
    preflight(account)
    print("Building the proc read guard as the desktop user...", file=sys.stderr)
    loader = guard.build()
    (ROOT / "target").mkdir(exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix="private-desktop-", dir=ROOT / "target"))
    commands, description = prepare(account, stage, loader)
    print(f"Prepared: {description}.\nReview and paste the complete Fish block in:\n{commands}\n"
          "No profiles moved or services changed. Do not sudo this file.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError, configparser.Error, subprocess.SubprocessError) as error:
        sys.exit(f"private desktop setup: {error}")
