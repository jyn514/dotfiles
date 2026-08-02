"""Create a Git bundle and checkout archive inside one tar file."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Sequence


def exit_status(returncode: int) -> int:
    return returncode if returncode >= 0 else 128 - returncode


def run(arguments: Sequence[bytes], *, cwd: bytes, output: int | None = None) -> int:
    try:
        result = subprocess.run(
            arguments,
            cwd=cwd,
            check=False,
            stdout=output,
            stderr=output,
        )
    except OSError as error:
        print(
            f"git-backup: could not execute {os.fsdecode(arguments[0])!r}: {error}",
            file=sys.stderr,
        )
        return 127 if isinstance(error, FileNotFoundError) else 126
    return exit_status(result.returncode)


def progress(message: str) -> None:
    print(f"INFO: {message}... ", end="", file=sys.stderr, flush=True)


def fail_step(status: int, log: bytes | None = None) -> int:
    print("FAIL", file=sys.stderr)
    if log is not None:
        try:
            with open(log, "rb") as source:
                shutil.copyfileobj(source, sys.stderr.buffer)
        except OSError as error:
            print(f"git-backup: could not read failure log: {error}", file=sys.stderr)
    return status


def mirror_directory(directory: bytes) -> tuple[bytes, bytes]:
    mirrors = [
        entry
        for entry in os.listdir(directory)
        if entry.lower().endswith(b".git") and os.path.isdir(os.path.join(directory, entry))
    ]
    if len(mirrors) != 1 or mirrors[0].lower() == b".git":
        raise ValueError("clone did not create exactly one named .git directory")
    return mirrors[0], mirrors[0][:-4]


def publish(source: bytes, destination: bytes) -> None:
    parent = os.path.dirname(destination)
    prefix = b"." + os.path.basename(destination) + b"."
    descriptor, pending = tempfile.mkstemp(prefix=prefix, suffix=b".tmp", dir=parent)
    try:
        with os.fdopen(descriptor, "wb") as output, open(source, "rb") as archive:
            shutil.copyfileobj(archive, output)
            output.flush()
            os.fsync(output.fileno())
        os.link(pending, destination)
    finally:
        try:
            os.unlink(pending)
        except FileNotFoundError:
            pass


def backup(repository: bytes, destination: bytes) -> int:
    destination = os.path.realpath(destination) + b".tar"
    if os.path.lexists(destination):
        print(f"ERROR: backup file {os.fsdecode(destination)!r} already exists.", file=sys.stderr)
        return 1

    with tempfile.TemporaryDirectory(prefix="git-backup.") as temporary_text:
        temporary = os.fsencode(temporary_text)

        progress("cloning repository")
        status = run(
            [b"git", b"clone", b"--quiet", b"--mirror", b"--bare", repository],
            cwd=temporary,
        )
        if status:
            return fail_step(status)
        print("DONE", file=sys.stderr)

        try:
            mirror, name = mirror_directory(temporary)
        except ValueError as error:
            print(f"git-backup: {error}", file=sys.stderr)
            return 1
        print(f"INFO: inferred repo name is {os.fsdecode(name)!r}")

        contents = os.path.join(temporary, name)
        os.mkdir(contents)
        bundle = os.path.join(contents, name + b".bundle")
        log = os.path.join(temporary, b"bundle.log")

        progress("creating bundle")
        with open(log, "wb") as output:
            status = run(
                [b"git", b"bundle", b"create", bundle, b"--all"],
                cwd=os.path.join(temporary, mirror),
                output=output.fileno(),
            )
        if status:
            return fail_step(status, log)
        print("DONE", file=sys.stderr)

        progress("archiving default branch")
        checkout = os.path.join(contents, b"master")
        status = run([b"git", b"clone", b"--quiet", bundle, checkout], cwd=contents)
        if status:
            return fail_step(status)
        shutil.rmtree(os.path.join(checkout, b".git"))
        status = run([b"tar", b"cfJ", b"master.tar.xz", b"master"], cwd=contents)
        if status:
            return fail_step(status)
        shutil.rmtree(checkout)
        print("DONE", file=sys.stderr)

        progress("generating backup file")
        archive = os.path.join(temporary, name + b".tar")
        status = run([b"tar", b"cf", archive, name], cwd=temporary)
        if status:
            return fail_step(status)
        try:
            publish(archive, destination)
        except FileExistsError:
            print(
                f"FAIL\nERROR: backup file {os.fsdecode(destination)!r} already exists.",
                file=sys.stderr,
            )
            return 1
        except OSError as error:
            print(f"FAIL\ngit-backup: could not publish backup: {error}", file=sys.stderr)
            return 1
        print("DONE", file=sys.stderr)
    return 0


def main(arguments: list[str]) -> int:
    if len(arguments) != 2:
        print("ERROR: incorrect usage", file=sys.stderr)
        print("git-backup [URL] [local file]", file=sys.stderr)
        return 1
    return backup(os.fsencode(arguments[0]), os.fsencode(arguments[1]))
