"""Generate byte-safe GitHub and GitLab source links."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from typing import NamedTuple
from urllib.parse import quote_from_bytes
from urllib.parse import unquote_to_bytes
from urllib.parse import urlsplit


POSITIVE_LINE = re.compile(r"[0-9]+")


class RepositoryUrl(NamedTuple):
    host: bytes
    path: bytes


def exit_status(returncode: int) -> int:
    return returncode if returncode >= 0 else 128 - returncode


def git(cwd: bytes, *arguments: bytes) -> subprocess.CompletedProcess[bytes] | None:
    try:
        return subprocess.run(
            [b"git", *arguments],
            cwd=cwd,
            check=False,
            stdout=subprocess.PIPE,
        )
    except OSError as error:
        print(f"remote-git-url: could not execute git: {error}", file=sys.stderr)
        return None


def repository_url(remote: bytes) -> RepositoryUrl:
    value = remote.removesuffix(b"/").removesuffix(b".git")
    if b"://" in value:
        parsed = urlsplit(value)
        host = parsed.hostname or b""
        path = unquote_to_bytes(parsed.path).lstrip(b"/")
    else:
        authority, separator, path = value.partition(b":")
        if not separator:
            raise ValueError("unsupported remote URL")
        host = authority.rsplit(b"@", 1)[-1]
        path = path.lstrip(b"/")
    host = host.lower()
    if host not in (b"github.com", b"gitlab.com"):
        raise ValueError("unsupported upstream")
    if len([component for component in path.split(b"/") if component]) < 2:
        raise ValueError("upstream URL does not identify a repository")
    return RepositoryUrl(host, path)


def source_url(
    repository: RepositoryUrl,
    revision: bytes,
    relative: bytes,
    line: int,
    length: int,
) -> bytes:
    repo = quote_from_bytes(repository.path, safe="/").encode()
    file_path = quote_from_bytes(relative, safe="/").encode()
    if repository.host == b"github.com":
        end = b"" if length == 1 else b"-L" + str(line + length - 1).encode()
        return (
            b"https://github.com/"
            + repo
            + b"/blob/"
            + revision
            + b"/"
            + file_path
            + b"#L"
            + str(line).encode()
            + end
        )
    end = b"" if length == 1 else b"-" + str(line + length - 1).encode()
    return (
        b"https://gitlab.com/"
        + repo
        + b"/-/blob/"
        + revision
        + b"/"
        + file_path
        + b"#L"
        + str(line).encode()
        + end
    )


def selected_lines(path: bytes, start: int, end: int) -> list[bytes] | None:
    try:
        with open(path, "rb") as source:
            lines = source.read().splitlines()
    except OSError as error:
        print(f"remote-git-url: could not read {os.fsdecode(path)!r}: {error}", file=sys.stderr)
        return None
    selected = lines[start - 1 : end]
    return selected if len(selected) == end - start + 1 else []


def locate(lines: list[bytes], remote_contents: bytes) -> int | None:
    if not lines or not lines[0]:
        return None
    haystack = remote_contents.splitlines()
    for index in range(len(haystack) - len(lines) + 1):
        if haystack[index : index + len(lines)] == lines:
            return index + 1
    return None


def checked(result: subprocess.CompletedProcess[bytes] | None) -> tuple[int, bytes]:
    if result is None:
        return 127, b""
    return exit_status(result.returncode), result.stdout


def generate(file_argument: str, start: int, end: int) -> tuple[int, bytes | None]:
    original = os.fsencode(file_argument)
    cwd = os.getcwdb()
    prefix = cwd + os.fsencode(os.sep)
    display_file = original[len(prefix) :] if original.startswith(prefix) else original
    path = os.path.realpath(original)
    directory = os.path.dirname(path)

    status, root_output = checked(git(directory, b"rev-parse", b"--show-toplevel"))
    if status:
        if status == 127:
            return status, None
        print(f"unknown git repo for {os.fsdecode(path)}", file=sys.stderr)
        return 1, None
    root = root_output.removesuffix(b"\n")
    try:
        inside = os.path.commonpath((root, path)) == root
    except ValueError:
        inside = False
    if not inside or path == root:
        print(
            f"{os.fsdecode(path)} is outside git repository {os.fsdecode(root)}",
            file=sys.stderr,
        )
        return 1, None
    relative = os.path.relpath(path, root)

    lines = selected_lines(path, start, end)
    if lines is None:
        return 1, None
    length = end - start + 1

    status, remotes_output = checked(git(directory, b"remote"))
    if status:
        return status, None
    remote = b"upstream" if b"upstream" in remotes_output.splitlines() else b"origin"

    commit: bytes | None = None
    remote_line: int | None = None
    if lines and lines[0]:
        status, revision_output = checked(
            git(directory, b"rev-list", b"--remotes", remote + b"/HEAD~^!", b"--max-count=1")
        )
        if status:
            return status, None
        revision = revision_output.strip()
        if revision:
            status, tree_output = checked(
                git(directory, b"ls-tree", b"-r", b"-z", b"--name-only", revision, b"--", relative)
            )
            if status:
                return status, None
            if relative in tree_output.rstrip(b"\0").split(b"\0"):
                status, remote_contents = checked(
                    git(directory, b"show", revision + b":" + relative)
                )
                if status:
                    return status, None
                remote_line = locate(lines, remote_contents)
                if remote_line is not None:
                    commit = revision

    result_status = 0
    if commit is None or remote_line is None:
        commit = b"HEAD"
        remote_line = start
        print(
            f"warning: {os.fsdecode(display_file)}:{remote_line} does not exist in upstream",
            file=sys.stderr,
        )
        result_status = 1

    status, remote_output = checked(git(directory, b"remote", b"get-url", remote))
    if status:
        return status, None
    remote_value = remote_output.removesuffix(b"\n")
    try:
        repository = repository_url(remote_value)
    except (UnicodeError, ValueError) as error:
        print(f"{error}: {os.fsdecode(remote_value)}", file=sys.stderr)
        return 2, None
    return result_status, source_url(repository, commit, relative, remote_line, length)


def main(arguments: list[str]) -> int:
    if len(arguments) not in (2, 3):
        print("usage: remote-git-url <file> <line-start> [<line-end>]", file=sys.stderr)
        return 1
    start_text = arguments[1]
    end_text = arguments[2] if len(arguments) == 3 else start_text
    if POSITIVE_LINE.fullmatch(start_text) is None or int(start_text) < 1:
        print(f"invalid start line: {start_text}", file=sys.stderr)
        return 2
    if POSITIVE_LINE.fullmatch(end_text) is None or int(end_text) < 1:
        print(f"invalid end line: {end_text}", file=sys.stderr)
        return 2
    start = int(start_text)
    end = int(end_text)
    if end < start:
        print("end line precedes start line", file=sys.stderr)
        return 2

    status, url = generate(arguments[0], start, end)
    if url is None:
        return status
    if os.environ.get("DISPLAY"):
        try:
            opened = subprocess.run([b"xdg-open", url], check=False)
        except OSError as error:
            print(f"remote-git-url: could not execute xdg-open: {error}", file=sys.stderr)
            return 127
        if opened.returncode:
            return exit_status(opened.returncode)
    else:
        sys.stdout.buffer.write(url + b"\n")
        status = 1
    return status
