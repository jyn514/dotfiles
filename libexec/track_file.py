#!/usr/bin/env python3

import argparse
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path


def atomic_write(path: Path, contents: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w") as output:
            output.write(contents)
        temporary.replace(path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def home_relative(source: Path, home: Path) -> Path | None:
    try:
        return source.resolve().relative_to(home.resolve())
    except ValueError:
        return None


def validate_name(name: str) -> str:
    if not name or Path(name).name != name or name in (".", ".."):
        raise ValueError("tracked name must be a basename")
    return name


def dotbot_links(config: list[object]) -> dict[str, object]:
    return next(directive["link"] for directive in config if "link" in directive)


def updated_dotbot_config(config_path: Path, destination: str, source: str) -> str:
    config = json.loads(config_path.read_text())
    links = dotbot_links(config)
    if destination in links:
        raise ValueError(f"dotfile destination is already tracked: {destination}")
    if any(
        specification == source
        or (isinstance(specification, dict) and specification.get("path") == source)
        for specification in links.values()
    ):
        raise ValueError(f"dotfile source is already tracked: {source}")
    links[destination] = source
    return json.dumps(config, indent=2) + "\n"


def untracked_dotbot_config(config_path: Path, destination: str) -> tuple[str, str]:
    config = json.loads(config_path.read_text())
    links = dotbot_links(config)
    try:
        specification = links.pop(destination)
    except KeyError:
        raise ValueError(f"dotfile destination is not tracked: {destination}") from None
    source = (
        specification.get("path")
        if isinstance(specification, dict)
        else specification
    )
    if not isinstance(source, str):
        raise ValueError(f"unsupported link specification for {destination}")
    return json.dumps(config, indent=2) + "\n", source


def track_home(source: Path, name: str, root: Path, home: Path, dry_run: bool) -> None:
    relative = home_relative(source, home)
    if relative is None:
        raise ValueError(f"not beneath home directory: {source}")
    tracked = root / "config" / name
    if tracked.exists() or tracked.is_symlink():
        raise ValueError(f"tracked file already exists: {tracked}")
    config_path = root / "install.conf.json"
    destination = f"$HOME/{relative.as_posix()}"
    tracked_source = f"config/{name}"
    new_config = updated_dotbot_config(config_path, destination, tracked_source)

    if dry_run:
        print(f"move {source} -> {tracked}")
        print(f"link {source} -> {tracked}")
        print(f"add {destination} -> {tracked_source} to install.conf.json")
        return

    source.rename(tracked)
    try:
        source.symlink_to(tracked.resolve())
        atomic_write(config_path, new_config)
    except BaseException:
        source.unlink(missing_ok=True)
        tracked.rename(source)
        raise


def untrack_home(source: Path, root: Path, home: Path, dry_run: bool) -> None:
    try:
        relative = source.relative_to(home.absolute())
    except ValueError:
        raise ValueError(f"not beneath home directory: {source}") from None
    config_path = root / "install.conf.json"
    old_config = config_path.read_text()
    destination = f"$HOME/{relative.as_posix()}"
    new_config, tracked_source = untracked_dotbot_config(config_path, destination)
    tracked = root / tracked_source
    try:
        tracked.relative_to(root / "config")
    except ValueError:
        raise ValueError(f"tracked source is outside config/: {tracked_source}") from None
    if not source.is_symlink() or source.resolve() != tracked.resolve():
        raise ValueError(f"tracked destination is not the expected symlink: {source}")
    if not tracked.exists():
        raise ValueError(f"tracked source does not exist: {tracked}")

    if dry_run:
        print(f"move {tracked} -> {source}")
        print(f"remove {destination} from install.conf.json")
        return

    source.unlink()
    try:
        tracked.rename(source)
        atomic_write(config_path, new_config)
    except BaseException:
        if source.exists() and not tracked.exists():
            source.rename(tracked)
        source.symlink_to(tracked.resolve())
        atomic_write(config_path, old_config)
        raise


def parse_global_manifest(contents: str) -> dict[str, str]:
    entries = {}
    for line in contents.splitlines():
        if not line or line.lstrip().startswith("#"):
            continue
        name, destination = line.split("=", 1)
        entries[name] = destination
    return entries


def track_global(source: Path, name: str, root: Path, dry_run: bool) -> None:
    tracked = root / "global" / name
    if tracked.exists() or tracked.is_symlink():
        raise ValueError(f"tracked file already exists: {tracked}")
    manifest_path = root / "install/global.txt"
    old_manifest = manifest_path.read_text()
    entries = parse_global_manifest(old_manifest)
    if name in entries:
        raise ValueError(f"global source name is already tracked: {name}")
    if str(source) in entries.values():
        raise ValueError(f"global destination is already tracked: {source}")
    new_manifest = old_manifest
    if new_manifest and not new_manifest.endswith("\n"):
        new_manifest += "\n"
    new_manifest += f"{name}={source}\n"

    if dry_run:
        print(f"copy {source} -> {tracked}")
        print(f"add {name}={source} to install/global.txt")
        print("run sudo libexec/setup/setup_sudo.sh copy_globals --force")
        return

    shutil.copy2(source, tracked)
    try:
        atomic_write(manifest_path, new_manifest)
        subprocess.run(
            ["sudo", "libexec/setup/setup_sudo.sh", "copy_globals", "--force"],
            cwd=root,
            check=True,
        )
    except BaseException:
        atomic_write(manifest_path, old_manifest)
        tracked.unlink(missing_ok=True)
        raise


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--untrack",
        action="store_true",
        help="stop tracking a home file or directory and restore it from config/",
    )
    parser.add_argument("source", type=Path)
    parser.add_argument("name", nargs="?")
    arguments = parser.parse_args()

    source = arguments.source.absolute()
    if not source.exists():
        parser.error(f"source does not exist: {source}")
    try:
        root = Path(__file__).resolve().parent.parent
        home = Path.home()
        if arguments.untrack:
            if arguments.name is not None:
                raise ValueError("a tracked name cannot be supplied with --untrack")
            untrack_home(source, root, home, arguments.dry_run)
        else:
            name = validate_name(arguments.name or source.name.lstrip("."))
            if home_relative(source, home) is not None:
                track_home(source, name, root, home, arguments.dry_run)
            else:
                track_global(source, name, root, arguments.dry_run)
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"track: {error}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
