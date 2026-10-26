"""Fixture-only checker invoked by the tools of an ordinary interactive host Pi.

No Pi SDK, token copying, native API server, fallback, or mutation retry.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

FIXTURE_SCOPE = 'new disposable Linux acceptance'


def publish(path, value):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, indent=2) + '\n')
    temporary.rename(path)


def wait(path, timeout=180):
    deadline = time.monotonic() + timeout
    while not path.is_file():
        if time.monotonic() >= deadline:
            raise RuntimeError(f'timed out waiting for {path.name}; do not replay mutations')
        time.sleep(.02)
    return json.loads(path.read_text())


def run(root, failed=False):
    root = root.resolve(strict=True)
    evidence = root / 'evidence'
    report = evidence / 'guest.json'
    # Exclusive claim survives a crash and prevents outcome-unknown replay.
    (evidence / 'guest.claim').open('x').close()
    result = dict(scope='actual ordinary-Pi guest tools (host composition must verify separately)',
                  passed=False, commands=[])

    def command(argv, success=True):
        output = subprocess.run(argv, cwd=root, capture_output=True, text=True, timeout=50)
        item = dict(argv=argv, exit=output.returncode, stdout=output.stdout,
                    stderr=output.stderr)
        result['commands'].append(item)
        publish(report, result)
        if success and output.returncode:
            raise RuntimeError(f'{argv[0]} failed; inspect guest.json; no retry')
        return item

    try:
        if Path.cwd().resolve() != root or not (root / 'fixture.json').is_file():
            raise RuntimeError('wrong checker/cwd; stop before ti')
        if json.loads((root / 'fixture.json').read_text()) != dict(owned=True, scope=FIXTURE_SCOPE):
            raise RuntimeError('not this workflow\'s fresh owned fixture; stop before ti')
        if os.environ.get('DOTFILES_SANDBOX') != '1':
            raise RuntimeError('requires ordinary sandbox guest tools, not a nested Pi runner')
        for argv, expected in ((['git', 'rev-parse', '--show-toplevel'], root),
                               (['jj', 'root'], root),
                               (['git', 'rev-parse', '--path-format=absolute', '--git-common-dir'], root / '.git')):
            if Path(command(argv)['stdout'].strip()).resolve() != expected:
                raise RuntimeError('wrong canonical Git/JJ/common authority; no ti')
        if Path(__file__).resolve().parent != root:
            raise RuntimeError('checker must be inside the admitted main root')
        if shutil.which('ti') != '/libexec/sandbox-wrappers/ti':
            raise RuntimeError('fixed guest ti guard is not first on PATH')
        result['endpoint_present'] = bool(os.environ.get('SANDBOX_TIC_ENDPOINT'))
        result['token_present'] = bool(os.environ.get('SANDBOX_TIC_TOKEN'))
        if failed:
            if result['endpoint_present'] or result['token_present']:
                raise RuntimeError('failed startup projected TicGit authority')
            output = command(['ti', 'list', '--json'], success=False)
            if output['exit'] == 0 or 'unavailable' not in output['stderr'].lower():
                raise RuntimeError('failed startup did not leave unavailable guard')
            # This subsequent ordinary guest command demonstrates usable tools.
            command(['python3', '-c', 'print("Pi guest tools remain usable")'])
        else:
            if not result['endpoint_present'] or not result['token_present']:
                raise RuntimeError('TicGit unavailable; no fallback')
            client = Path('/opt/agent-tools/bin/ti')
            with client.open('rb') as stream:
                result['client_sha256'] = hashlib.file_digest(stream, 'sha256').hexdigest()
            host = wait(evidence / 'host-created.json')
            shown = command(['ti', 'show', host['id'], '--json'])
            if host['title'] not in shown['stdout']:
                raise RuntimeError('host-created ticket not visible in guest')
            body = 'Guest confirms host-linked ticket α'
            command(['ti', 'comment', '--ticket', host['id'], body])
            result['comment'] = body
            publish(evidence / 'guest-ready.json', {'ready': True})
            wait(evidence / 'host-go.json')
            writes = []
            for index in range(4):
                title = f'guest concurrent {index}'
                output = command(['ti', 'new', '--title', title, '--id-only'], success=False)
                if output['exit'] and not any(word in output['stderr'].lower() for word in ('locked', 'busy')):
                    raise RuntimeError('guest writer failed for reason other than native contention')
                writes.append(dict(title=title, **output))
            if not any(item['exit'] == 0 for item in writes):
                raise RuntimeError('no successful guest writer')
            result['writes'] = writes
        result['passed'] = True
    finally:
        publish(report, result)
    print('PASS: guest phase; exit this TEST Pi normally so its host can finish the smoke checks.')


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--failed-startup', action='store_true')
    arguments = parser.parse_args()
    run(Path(__file__).resolve().parent, arguments.failed_startup)
