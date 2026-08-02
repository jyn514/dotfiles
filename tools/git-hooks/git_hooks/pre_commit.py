"""Materialize the staged snapshot and run repository pre-commit checks."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
import contextlib
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile


GENERAL_CHECKS = (
    "case_conflict",
    "end_of_file",
    "executables_have_shebangs",
    "json",
    "merge_conflict",
    "shebang_scripts_are_executable",
    "toml",
    "vcs_permalinks",
)
MAX_BATCH_BYTES = 128 * 1024


class Interrupted(RuntimeError):
    def __init__(self, signum: int) -> None:
        self.signum = signum


def exit_status(returncode: int) -> int:
    return returncode if returncode >= 0 else 128 - returncode


def run(
    arguments: Sequence[bytes],
    *,
    environment: dict[bytes, bytes] | dict[str, str] | None = None,
    capture: bool = False,
) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        arguments,
        check=False,
        env=environment,
        stdout=subprocess.PIPE if capture else None,
    )


def query(
    arguments: Sequence[bytes],
    environment: dict[bytes, bytes] | dict[str, str] | None,
) -> tuple[int, bytes]:
    result = run(arguments, environment=environment, capture=True)
    return exit_status(result.returncode), result.stdout


def absolute_directory(raw: bytes, working_directory: bytes) -> bytes:
    path = raw if os.path.isabs(raw) else os.path.join(working_directory, raw)
    resolved = os.path.realpath(path)
    if not os.path.isdir(resolved):
        raise NotADirectoryError(os.fsdecode(resolved))
    return resolved


def git_environment(
    git_directory: bytes, work_tree: bytes
) -> dict[bytes, bytes] | dict[str, str]:
    if hasattr(os, "environb"):
        environment = os.environb.copy()
        environment[b"GIT_DIR"] = git_directory
        environment[b"GIT_WORK_TREE"] = work_tree
        return environment
    environment = os.environ.copy()
    environment["GIT_DIR"] = os.fsdecode(git_directory)
    environment["GIT_WORK_TREE"] = os.fsdecode(work_tree)
    return environment


def snapshot_environment(
    environment: dict[bytes, bytes] | dict[str, str], snapshot: bytes
) -> dict[bytes, bytes] | dict[str, str]:
    updated = environment.copy()
    if b"GIT_DIR" in updated:
        updated[b"GIT_WORK_TREE"] = snapshot  # type: ignore[index]
    else:
        updated["GIT_WORK_TREE"] = os.fsdecode(snapshot)  # type: ignore[index]
    return updated


def path_batches(paths: Sequence[bytes]) -> Iterator[list[bytes]]:
    batch: list[bytes] = []
    size = 0
    for path in paths:
        cost = len(path) + 1
        if batch and size + cost > MAX_BATCH_BYTES:
            yield batch
            batch = []
            size = 0
        batch.append(path)
        size += cost
    if batch:
        yield batch


def output_path(output: bytes) -> bytes:
    """Remove the one record newline emitted by `git rev-parse`."""
    return output[:-1] if output.endswith(b"\n") else output


def snapshot_entries(root: bytes) -> tuple[list[bytes], list[bytes]]:
    files: list[bytes] = []
    links: list[bytes] = []

    def visit(directory: bytes) -> None:
        with os.scandir(directory) as entries:
            for entry in sorted(entries, key=lambda item: item.name):
                absolute = os.path.join(directory, entry.name)
                relative = b"./" + os.path.relpath(absolute, root)
                if entry.is_symlink():
                    links.append(relative)
                elif entry.is_dir(follow_symlinks=False):
                    visit(absolute)
                elif entry.is_file(follow_symlinks=False):
                    files.append(relative)

    visit(root)
    return files, links


def run_checker(
    hook_directory: bytes,
    script: bytes,
    paths: Sequence[bytes],
    environment: dict[bytes, bytes] | dict[str, str],
    *,
    run_when_empty: bool,
) -> int:
    batches = list(path_batches(paths))
    if not batches and run_when_empty:
        batches = [[]]
    for batch in batches:
        result = run(
            [os.fsencode(sys.executable), os.path.join(hook_directory, script), b"--", *batch],
            environment=environment,
        )
        if result.returncode:
            return exit_status(result.returncode)
    return 0


@contextlib.contextmanager
def interrupt_cleanup() -> Iterator[None]:
    def interrupted(signum: int, _frame: object) -> None:
        raise Interrupted(signum)

    signals = (signal.SIGHUP, signal.SIGINT, signal.SIGTERM)
    previous = {signum: signal.signal(signum, interrupted) for signum in signals}
    try:
        yield
    finally:
        for signum, handler in previous.items():
            signal.signal(signum, handler)


def main(_arguments: list[str], *, hook_directory: Path) -> int:
    working_directory = os.getcwdb()
    try:
        changed = run([
            b"git",
            b"diff",
            b"--quiet",
            b"--cached",
            b"--no-ext-diff",
            b"--diff-filter=d",
            b"--",
        ])
        if changed.returncode == 0:
            return 0
        if changed.returncode != 1:
            return exit_status(changed.returncode)

        status, raw_git_directory = query([b"git", b"rev-parse", b"--git-dir"], None)
        if status:
            return status
        git_directory = absolute_directory(output_path(raw_git_directory), working_directory)
        environment = git_environment(git_directory, working_directory)

        status, raw_common_directory = query(
            [b"git", b"rev-parse", b"--git-common-dir"], environment
        )
        if status:
            return status
        common_directory = absolute_directory(
            output_path(raw_common_directory), working_directory
        )
        local_hook = os.path.join(common_directory, b"hooks", b"pre-commit")
        if os.path.exists(local_hook):
            local = run([local_hook], environment=environment)
            if local.returncode:
                return exit_status(local.returncode)

        status, raw_paths = query([
            b"git",
            b"diff",
            b"--name-only",
            b"-z",
            b"--cached",
            b"--no-ext-diff",
            b"--diff-filter=d",
            b"--",
        ], environment)
        if status:
            return status
        paths = sorted(path for path in raw_paths.split(b"\0") if path)
        temporary_root = os.fsencode(os.environ.get("TMPDIR", tempfile.gettempdir()))
        prefix = os.path.basename(working_directory) + b"-pre-commit."
        with interrupt_cleanup():
            snapshot = tempfile.mkdtemp(prefix=prefix, dir=temporary_root)
            try:
                checkout_prefix = snapshot + os.sep.encode()
                for path in paths:
                    checkout = run(
                        [b"git", b"checkout-index", b"--prefix=" + checkout_prefix, b"--", path],
                        environment=environment,
                    )
                    if checkout.returncode:
                        return exit_status(checkout.returncode)

                files, links = snapshot_entries(snapshot)
                os.chdir(snapshot)
                hook_bytes = os.fsencode(hook_directory)
                checker_environment = snapshot_environment(environment, snapshot)
                checks: list[tuple[bytes, Sequence[bytes], bool]] = [
                    (b"pre_commit_hooks/check_symlinks.py", links, True),
                    (b"pre_commit_hooks/destroyed_symlinks.py", files, True),
                ]
                checks.extend(
                    (f"pre_commit_hooks/check_{name}.py".encode(), files, True)
                    for name in GENERAL_CHECKS
                )
                checks.extend(
                    [
                        (
                            b"pre_commit_hooks/check_xml.py",
                            [path for path in files if path.endswith(b".xml")],
                            False,
                        ),
                        (
                            b"pre_commit_hooks/check_yaml.py",
                            [path for path in files if path.endswith((b".yaml", b".yml"))],
                            False,
                        ),
                    ]
                )
                for script, selected, run_when_empty in checks:
                    status = run_checker(
                        hook_bytes,
                        script,
                        selected,
                        checker_environment,
                        run_when_empty=run_when_empty,
                    )
                    if status:
                        return status
            finally:
                os.chdir(working_directory)
                shutil.rmtree(snapshot)
        return 0
    except Interrupted as error:
        return 128 + error.signum
    except OSError as error:
        print(f"error: pre-commit setup failed: {error}", file=sys.stderr)
        return 1
