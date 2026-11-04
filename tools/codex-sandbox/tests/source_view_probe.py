"""Assertions run inside the source-view integration container."""

from pathlib import Path

assert Path('/home/codex/src/team/sibling').read_text() == 'visible'
assert Path('/home/codex/src/alias').read_text() == 'visible'
assert not Path('/home/codex/src/repository/old').exists()
assert Path('/home/codex/src/team/main/.git/marker').read_text() == 'protected'
Path('/home/codex/src/repository/created').write_text('writable')
for path in ('/home/codex/src/team/sibling', '/home/codex/src/team/main/.git/marker', '/home/codex/src/unwanted'):
    try:
        Path(path).write_text('forbidden')
    except OSError:
        pass
    else:
        raise AssertionError('read-only source became writable: ' + path)
