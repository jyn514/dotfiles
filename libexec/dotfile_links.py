"""Resolve this repository's string and glob Dotbot link mappings.

Consumers receive symbolic destination names (such as $HOME paths) and absolute
source paths. Expansion does not modify files. Dotbot remains the installer;
setup backups and sandbox staging use these same resolved source mappings.
"""

from collections.abc import Iterator
import glob
import json
import os
from pathlib import Path


def link_paths(repository: Path, destination: str, specification: object) -> Iterator[tuple[str, Path]]:
    options = specification if isinstance(specification, dict) else {}
    path = options["path"] if options else specification
    pattern = os.path.normpath(os.path.expanduser(os.path.expandvars(str(repository / path))))
    if not options.get("glob") or not any(character in pattern for character in "?*["):
        yield destination, Path(pattern)
        return

    excluded = set()
    for exclusion in options.get("exclude", []):
        excluded.update(glob.glob(str(repository / exclusion), recursive=True))
    for match in sorted(glob.glob(pattern, recursive=True)):
        if match in excluded:
            continue
        # Dotbot recursive file globs omit directories, keeping runtime state local.
        if "**" in pattern and not Path(match).is_file():
            continue
        prefix = os.path.dirname(os.path.commonprefix([pattern, match]))
        relative = os.path.relpath(match, prefix) if prefix else match
        yield os.path.join(destination, relative), Path(match)


def configured_links(config_path: Path) -> dict[str, Path]:
    """Expand explicit glob/exclude mappings without expanding destination variables."""
    config_path = config_path.resolve()
    configuration = json.loads(config_path.read_text())
    return {
        destination: source
        for directive in configuration if "link" in directive
        for name, specification in directive["link"].items()
        for destination, source in link_paths(config_path.parent, name, specification)
    }
