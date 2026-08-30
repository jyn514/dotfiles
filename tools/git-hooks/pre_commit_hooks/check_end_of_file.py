from __future__ import annotations

import argparse
import os
from typing import IO
from typing import Sequence


TOO_FEW_NEWLINES = -1
TOO_MANY_NEWLINES = 1
JUST_RIGHT = 0

def check_file(file_obj: IO[bytes]) -> int:
    # Test for newline at end of file
    # Empty files will throw IOError here
    try:
        file_obj.seek(-1, os.SEEK_END)
    except OSError:
        return 0
    last_character = file_obj.read(1)
    # last_character will be '' for an empty file
    if last_character not in {b'\n', b'\r'} and last_character != b'':
        return TOO_FEW_NEWLINES

    while last_character in {b'\n', b'\r'}:
        # If we've reached the beginning of the file, it is all linebreaks
        if file_obj.tell() == 1:
            return TOO_MANY_NEWLINES

        # Go back two bytes and read a character
        file_obj.seek(-2, os.SEEK_CUR)
        last_character = file_obj.read(1)

    # Our current position is at the end of the file just before any amount of
    # newlines.  If we find extraneous newlines, then backtrack and trim them.
    remaining = file_obj.read()
    for sequence in (b'\n', b'\r\n', b'\r'):
        if remaining == sequence:
            return JUST_RIGHT
        elif remaining.startswith(sequence):
            return TOO_MANY_NEWLINES

    return JUST_RIGHT  # HMMMM


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('filenames', nargs='*', help='Filenames to fix')
    args = parser.parse_args(argv)

    bad_files = {TOO_FEW_NEWLINES: set(), TOO_MANY_NEWLINES: set()}
    for filename in args.filenames:
        # Read as binary so we can read byte-by-byte
        with open(filename, 'rb+') as file_obj:
            if status := check_file(file_obj):
                bad_files[status].add(filename)

    if too_few := bad_files[TOO_FEW_NEWLINES]:
        print("files are missing trailing newline:")
        for f in too_few:
            print(f)

    if too_few := bad_files[TOO_MANY_NEWLINES]:
        print("files have too many trailing newlines:")
        for f in too_few:
            print(f)

    return any(bad_files.values())


if __name__ == '__main__':
    raise SystemExit(main())
