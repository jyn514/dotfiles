#!/usr/bin/env python3
"""Export a tracked regular-file Flower snapshot, without checking out Flower.

CLI: prepare.py --repository REPO --output NEW_DIRECTORY
The output contains flower.tar, manifest.json, and data/. It needs no repository
at evaluation time. Use a distinct output directory per preparation process.
Nonregular tracked entries are recorded, not dereferenced or reconstructed.
"""

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile

REVISION = "5078c7c6def97fed8827d616b7745656d6dd01b9"
CHRONOLOGY_CAVEAT = (
    "Chronology candidate for session 019ee348-05e2-70c0-a2be-6b820eac388b, "
    "not a proven exact worker checkout. This is a fresh baseline, not historical "
    "replay. The existing template defect is intentionally retained."
)
FILE_TEMPLATE = 'path.display() ++ "\\0" ++ file_type ++ "\\0" ++ executable ++ "\\0"'


def jj(repository: Path, *arguments: str) -> bytes:
    """Read checked stdout only; errors never become exported file contents."""
    result = subprocess.run(
        ["jj", *arguments], cwd=repository, capture_output=True, check=False
    )
    if result.returncode:
        diagnostic = result.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"jj {' '.join(arguments)} failed ({result.returncode}): {diagnostic}")
    return result.stdout


def entries(raw: bytes) -> list[tuple[str, str, bool]]:
    """Decode NUL-framed jj TreeEntry fields and reject unsafe archive names."""
    fields = raw.decode("utf-8").split("\0")
    if fields.pop() != "" or len(fields) % 3:
        raise ValueError("Malformed jj file list framing")
    result = []
    seen = set()
    for index in range(0, len(fields), 3):
        path, kind, executable = fields[index:index + 3]
        if (not path or path.startswith("/") or "\\" in path
                or any(part in ("", ".", "..") for part in path.split("/"))):
            raise ValueError(f"Unsafe tracked path: {path!r}")
        if path in seen or not kind or executable not in ("true", "false"):
            raise ValueError(f"Malformed or duplicate jj file entry: {path!r}")
        seen.add(path)
        result.append((path, kind, executable == "true"))
    # Even excluded entries must not collide with archive directory prefixes.
    for path in seen:
        parts = path.split("/")
        if any("/".join(parts[:i]) in seen for i in range(1, len(parts))):
            raise ValueError(f"Tracked file/directory collision: {path!r}")
    if not result:
        raise ValueError("Empty tracked snapshot")
    return sorted(result)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def prepare(repository: Path, output: Path) -> None:
    """Publish only a complete snapshot; leave no output directory on failure."""
    repository = repository.resolve(strict=True)
    output = output.absolute()
    if os.path.lexists(output):
        raise FileExistsError(f"Output already exists: {output}")
    listed = entries(jj(repository, "file", "list", "-r", REVISION, "-T", FILE_TEMPLATE))
    regular = [entry for entry in listed if entry[1] == "file"]
    if not regular:
        raise ValueError("Snapshot has no regular files")
    excluded = [{"path": path, "type": kind} for path, kind, _ in listed if kind != "file"]
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f".{output.name}-", dir=output.parent) as temporary:
        stage = Path(temporary) / "fixture"
        stage.mkdir()
        files = []

        def export(entry: tuple[str, str, bool]) -> tuple[str, bool, bytes]:
            path, _, executable = entry
            return path, executable, jj(repository, "file", "show", "-r", REVISION, "root:" + json.dumps(path, ensure_ascii=False))

        # Four checked subprocesses at most; tar writes stay serial and deterministic.
        with ThreadPoolExecutor(max_workers=4) as executor:
            with tarfile.open(stage / "flower.tar", "w", format=tarfile.PAX_FORMAT) as archive:
                for path, executable, data in executor.map(export, regular):
                    mode = 0o755 if executable else 0o644
                    member = tarfile.TarInfo(f"flower/{path}")
                    member.size = len(data)
                    member.mode = mode
                    archive.addfile(member, io.BytesIO(data))
                    files.append({"path": path, "sha256": sha256(data), "mode": mode})
        shutil.copytree(Path(__file__).with_name("data"), stage / "data")
        manifest = {
            "schema_version": 1,
            "revision": REVISION,
            "snapshot_kind": "tracked regular-file snapshot",
            "chronology_caveat": CHRONOLOGY_CAVEAT,
            "excluded_entries_note": ".claude/skills is a convenience alias; no symlink targets are invented.",
            "files": files,
            "excluded_paths": excluded,
            "archive": {"path": "flower.tar", "sha256": sha256((stage / "flower.tar").read_bytes())},
            "data_files": {
                path.name: sha256(path.read_bytes()) for path in sorted((stage / "data").iterdir())
            },
        }
        (stage / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        if os.path.lexists(output):
            raise FileExistsError(f"Output appeared during preparation: {output}")
        stage.rename(output)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    try:
        prepare(arguments.repository, arguments.output)
    except (OSError, RuntimeError, ValueError) as error:
        print(f"Fixture preparation failed: {error}. No new fixture was published; use a new output path and retry.", file=sys.stderr)
        return 1
    print(f"Prepared fixture: {arguments.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
