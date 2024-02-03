"""Check that executable text files have a shebang."""
from __future__ import annotations

import argparse
from typing import Generator
from typing import NamedTuple
from typing import Sequence

from util import cmd_output
from util import zsplit

EXECUTABLE_VALUES = frozenset(('1', '3', '5', '7'))

def check_executables(paths: list[str]) -> set[str]:
    seen: set[str] = set()
    for ls_file in git_ls_files(paths):
        is_executable = any(b in EXECUTABLE_VALUES for b in ls_file.mode[-3:])
        if is_executable and not has_shebang(ls_file.filename):
            seen.add(ls_file.filename)

    return seen

class GitLsFile(NamedTuple):
    mode: str
    filename: str


def git_ls_files(paths: Sequence[str]) -> Generator[GitLsFile, None, None]:
    outs = cmd_output('git', 'ls-files', '-z', '--stage', '--', *paths)
    for out in zsplit(outs):
        metadata, filename = out.split('\t')
        mode, _, _ = metadata.split()
        yield GitLsFile(mode, filename)


def has_shebang(path: str) -> int:
    with open(path, 'rb') as f:
        first_bytes = f.read(2)

    return first_bytes == b'#!'


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('filenames', nargs='*')
    args = parser.parse_args(argv)

    if bad := check_executables(args.filenames):
        print("Files marked executable but have no (or invalid) shebang:")
        for f in bad:
            print(f)
        return 1
    else:
        return 0


if __name__ == '__main__':
    raise SystemExit(main())
