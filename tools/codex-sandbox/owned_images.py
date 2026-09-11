"""Bake declarations for helpers owned by the installed launcher."""

import hashlib
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
COMMANDS = {
    str(ROOT / 'tools/codex-sandbox/auth-proxy/image'): 'auth',
    str(ROOT / '.agents/sandbox/jj-proxy-image'): 'jj',
    str(ROOT / '.agents/sandbox/zulip-proxy-image'): 'zulip',
}


def target(command):
    # Only the exact installed entrypoint is owned. Repository names and target
    # declarations cannot substitute for these helpers.
    return COMMANDS.get(command[0]) if len(command) == 1 else None


def declaration(requested=('auth', 'jj', 'zulip')):
    sources = {
        'auth': ['tools/codex-sandbox/auth-proxy/Dockerfile',
                 'tools/codex-sandbox/auth-proxy/server.py'],
        'jj': ['tools/jj-proxy/Dockerfile', 'tools/jj-proxy/Cargo.toml',
               'tools/jj-proxy/Cargo.lock', 'tools/jj-proxy/jj.toml',
               'tools/jj-proxy/agent-split-editor', 'config/gitignore',
               *[str(p.relative_to(ROOT)) for p in (ROOT / 'tools/jj-proxy/src').rglob('*') if p.is_file()]],
        'zulip': ['tools/zulip-proxy/Dockerfile', 'tools/zulip-proxy/server.py',
                  'tools/zulip-proxy/forward.py'],
    }
    targets = {}
    for name, paths in sources.items():
        if name not in requested:
            continue
        key = hashlib.sha256()
        for path in sorted(paths):
            key.update(path.encode() + b'\0')
            key.update(hashlib.sha256((ROOT / path).read_bytes()).digest())
        targets[name] = {'context': '.', 'dockerfile': paths[0],
                         'tags': [f'codex-{name}:{key.hexdigest()}'],
                         'platforms': ['${BUILDPLATFORM}']}
    return {'variable': {'BUILDPLATFORM': {'default': 'linux/arm64'}}, 'target': targets}


if __name__ == '__main__':
    image = declaration([sys.argv[1]])['target'][sys.argv[1]]
    executable = str(ROOT / 'tools/codex-sandbox/sandbox-image')
    os.chdir(ROOT)
    os.execv(executable, [executable, 'build', '--if-missing', '--file',
                         image['dockerfile'], '--tag', image['tags'][0], '.'])
