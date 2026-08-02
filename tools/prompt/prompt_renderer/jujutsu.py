"""Shared Jujutsu query protocol for prompt renderers."""

from __future__ import annotations

import os


QUERY = [
    b"jj",
    b"log",
    b"-r",
    b"@|@-",
    b"-T",
    b'empty++":"++if(bookmarks.len()>0,bookmarks.first(),"")++":"++description.first_line()++"\\n"',
    b"--no-graph",
    b"--ignore-working-copy",
    b"--config",
    b"ui.paginate=never",
]


def parse_log(output: bytes) -> tuple[bool, str] | None:
    lines = output.splitlines()
    if len(lines) != 2:
        return None
    current_empty = lines[0].split(b":", 1)[0] == b"true"
    fields = lines[1].split(b":", 2)
    if len(fields) != 3:
        return None
    bookmark, description = fields[1:]
    return current_empty, os.fsdecode(bookmark or description)
