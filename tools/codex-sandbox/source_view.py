"""Provide read-only source browsing with mountpoints for external worktrees."""

import os
from pathlib import Path


def check_mount_destinations(arguments: list[str]) -> None:
    """Reject duplicate container targets in a complete run argument list."""
    seen: set[str] = set()
    for index, argument in enumerate(arguments[:-1]):
        if argument == '--mount':
            fields = arguments[index + 1].split(',')
            destination = next((field.split('=', 1)[1] for field in fields
                                if field.startswith(('dst=', 'destination=', 'target='))), None)
        elif argument == '--tmpfs':
            destination = arguments[index + 1].split(':', 1)[0]
        else:
            continue
        if destination is None:
            raise ValueError('mount has no destination')
        destination = os.path.normpath(destination)
        if destination in seen:
            raise ValueError(f'duplicate container mount destination: {destination}')
        seen.add(destination)


def source_mounts(source: Path, destinations: list[Path], staging: Path) -> list[str]:
    target = Path('/src')
    required = [path.relative_to(target) for path in destinations if path.is_relative_to(target)]
    missing = [path for path in required if not (source / path).exists()]
    if not missing:
        return ['--mount', f'type=bind,src={source},dst={target},readonly']

    # A missing mountpoint cannot be created under a read-only parent bind.
    # Split only its ancestors into a staged directory; keep other subtrees as
    # live read-only binds, and never create placeholders in the host checkout.
    mounts = ['--mount', f'type=bind,src={staging},dst={target},readonly']

    def populate(original: Path, relative: Path) -> None:
        directory = staging / relative
        directory.mkdir(parents=True, exist_ok=True)
        for child in original.iterdir():
            entry = relative / child.name
            placeholder = staging / entry
            if any(entry.is_relative_to(path) for path in required):
                placeholder.mkdir()
            elif child.is_symlink():
                placeholder.symlink_to(os.readlink(child))
            elif child.is_dir() and any(path.is_relative_to(entry) for path in missing):
                populate(child, entry)
            else:
                if any(character in str(child) for character in (',', '\n', '\r')):
                    raise ValueError('source path contains a container-mount delimiter: ' + str(child))
                if child.is_dir():
                    placeholder.mkdir()
                else:
                    placeholder.touch()
                mounts.extend(['--mount', f'type=bind,src={child},dst={target / entry},readonly'])

    populate(source, Path('.'))
    for path in missing:
        # Do not follow a copied host symlink while constructing the scaffold.
        for parent in (*path.parents, path):
            if (staging / parent).is_symlink():
                raise ValueError('missing source mountpoint traverses a symlink: ' + str(target / path))
        (staging / path).mkdir(parents=True, exist_ok=True)
    return mounts
