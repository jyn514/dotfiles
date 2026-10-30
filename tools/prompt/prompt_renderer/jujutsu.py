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
    # JJ emits LF-delimited records; CR and other controls belong to labels.
    lines = output.split(b"\n")
    if lines[-1] == b"":
        lines.pop()
    if len(lines) < 2:
        return None
    records = [line.split(b":", 2) for line in lines]
    if any(len(fields) != 3 or fields[0] not in (b"true", b"false") for fields in records):
        return None
    current_empty = records[0][0] == b"true"
    parents = [os.fsdecode(bookmark or description) for _, bookmark, description in records[1:]]
    return current_empty, " + ".join(parents)
