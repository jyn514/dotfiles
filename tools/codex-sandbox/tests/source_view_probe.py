"""Assertions run inside the source-view integration container."""

from pathlib import Path

assert Path('/src/team/sibling').read_text() == 'visible'
assert Path('/src/alias').read_text() == 'visible'
assert not Path('/src/repository/old').exists()
assert Path('/src/team/main/.git/marker').read_text() == 'protected'
Path('/src/repository/created').write_text('writable')
for path in ('/src/team/sibling', '/src/team/main/.git/marker', '/src/unwanted'):
    try:
        Path(path).write_text('forbidden')
    except OSError:
        pass
    else:
        raise AssertionError('read-only source became writable: ' + path)
