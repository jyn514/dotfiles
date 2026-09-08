#!/usr/bin/python3
"""Container-side assertions for a disposable host-share layout."""

from pathlib import Path


def denied(path):
    try:
        path.write_text("changed")
    except OSError:
        return
    raise AssertionError(f"protected path was writable: {path}")


assert Path.cwd() == Path("/src/project with spaces/nested")
assert Path("../live.txt").read_text() == "second host edit"
Path("../written.txt").write_text("container edit")
assert Path("../.git/config").read_text() == "protected metadata"
denied(Path("../.git/config"))
assert not list(Path("../.agents").iterdir())
denied(Path("../.agents/injected"))
denied(Path("/src/sibling/injected"))
assert Path("/metadata/config").read_text() == "external metadata"
denied(Path("/metadata/config"))
