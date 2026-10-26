#!/usr/bin/env python3
"""Opt-in Linux functional smoke test, not a new launcher or lifecycle proof.

Run on the actual Linux host with terminal stdin/stdout. The ordinary launcher's
resolver selects/provisions its protected cache bundle automatically. This creates
only new owned repositories under target/.
Pi keeps its ordinary interactive frontend and configured provider. The user
exits each TEST Pi normally after the fixture checker completes. No VM stop,
profile mutation, or session adoption is performed. Concurrent writer loops are
a smoke workflow, not proof of interleaving or simultaneous SQLite commits.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import runpy
import shutil
import sqlite3
import subprocess
import sys
import threading
import tempfile
import time
import uuid

TESTS = Path(__file__).resolve().parent
PROXY = TESTS.parent
DOTFILES = PROXY.parents[1]
sys.path.insert(0, str(PROXY))
from bundle import host_platform, protected_bundle
from linux_acceptance_guest import FIXTURE_SCOPE, publish, wait


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def isolated_environment(root):
    environment = dict(os.environ)
    # Test fixture configuration must never inherit real tracker identity or
    # caller Git routing. Pi itself retains normal host configuration separately.
    for key in list(environment):
        if key.startswith(('GIT_', 'JJ_')) or key in ('TICGIT_STATE_FILE', 'SANDBOX_TIC_ENDPOINT', 'SANDBOX_TIC_TOKEN'):
            environment.pop(key)
    environment.update(HOME=str(root / 'home'), XDG_CONFIG_HOME=str(root / 'config'),
                       XDG_CACHE_HOME=str(root / 'cache'), XDG_STATE_HOME=str(root / 'state'),
                       GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL='/dev/null',
                       TICGIT_STATE_FILE=str(root / 'human-ui.json'))
    return environment


class Fixture:
    def __init__(self, root):
        self.root = root.resolve(strict=True)
        self.main = self.root / 'main'
        self.linked = self.root / 'linked'
        self.environment = isolated_environment(self.root)
        self.log = self.root / 'host-commands.jsonl'
        self.lock = threading.Lock()

    def command(self, cwd, argv, success=True):
        output = subprocess.run([str(arg) for arg in argv], cwd=cwd, env=self.environment,
                                capture_output=True, text=True, timeout=50)
        item = dict(cwd=str(cwd), argv=[str(arg) for arg in argv], exit=output.returncode,
                    stdout=output.stdout, stderr=output.stderr)
        with self.lock, self.log.open('a') as stream:
            stream.write(json.dumps(item) + '\n')
        require(not success or output.returncode == 0,
                f'{argv[0]} failed; inspect {self.log}; no mutation retry')
        return item

    def git(self, cwd, *args):
        return self.command(cwd, ['git', *args])['stdout'].strip()

    def prepare(self):
        require(not self.main.exists() and not self.linked.exists(), 'fixture must be fresh')
        self.git(self.root, 'init', '-qb', 'main', str(self.main))
        for key, value in (('user.name', 'Linux Acceptance'),
                           ('user.email', 'linux-acceptance@example.invalid'),
                           ('meta.namespace', 'acceptance-' + uuid.uuid4().hex)):
            self.git(self.main, 'config', key, value)
        self.git(self.main, 'commit', '--allow-empty', '-qm', 'Owned disposable acceptance fixture')
        self.git(self.main, 'worktree', 'add', '-qb', 'linked', str(self.linked))
        # Resolve the actual native JJ before isolation; host workflow uses the
        # host's ordinary jj. This never initializes linked JJ or another frontend.
        jj = os.environ.get('DOTFILES_TEST_JJ_REAL', 'jj')
        # JJ consults cwd's repository before init; starting in this nested
        # Git-only fixture can try locking its protected ancestor JJ repo.
        # An owned neutral cwd avoids that ancestor without altering discovery.
        with tempfile.TemporaryDirectory(prefix='tic-jj-bootstrap-') as neutral:
            self.command(Path(neutral), [jj, 'git', 'init', '--colocate', str(self.main)])
        (self.main / 'evidence').mkdir()
        publish(self.main / 'fixture.json', dict(owned=True, scope=FIXTURE_SCOPE))
        policy = self.main / '.agents/sandbox'
        policy.mkdir(parents=True)
        publish(policy / 'proxy-commands.json', {'version': 2, 'capabilities': {'tic': True, 'zulip': False,
                'nested-containers': False, 'flower-r2': False, 'host-editor': False},
                'commands': {}})
        shutil.copyfile(TESTS / 'linux_acceptance_guest.py', self.main / 'check_guest.py')
        self.guard()

    def guard(self):
        require(self.main.resolve() == self.main and self.main.is_dir(), 'noncanonical main')
        require(json.loads((self.main / 'fixture.json').read_text()) == dict(owned=True, scope=FIXTURE_SCOPE),
                'not this workflow\'s owned fixture; no ti')
        require(self.git(self.main, 'rev-parse', '--show-toplevel') == str(self.main), 'wrong main Git root')
        jj = os.environ.get('DOTFILES_TEST_JJ_REAL', 'jj')
        require(self.command(self.main, [jj, 'root'])['stdout'].strip() == str(self.main), 'wrong main JJ root')
        require((self.main / '.git').is_dir() and not (self.main / '.git').is_symlink(), 'nonstandalone main')
        for cwd in (self.main, self.linked):
            require(self.git(cwd, 'rev-parse', '--path-format=absolute', '--git-common-dir') == str(self.main / '.git'),
                    'wrong main/linked common authority')
        require((self.main / 'check_guest.py').parent == self.main, 'checker outside admitted root')
        for suffix in ('', '-wal', '-shm'):
            require(not os.path.lexists(self.main / '.git/worktrees/linked' / ('git-meta.sqlite' + suffix)),
                    'independent linked store; stop without adoption or migration')

    def ti(self, native, cwd, *argv, success=True):
        # Every mutation and inspection is scoped again, before invoking native.
        self.guard()
        return self.command(cwd, [native, *argv], success)


def verify_shared(fixture, native, host, guest, writes):
    fixture.guard()
    outputs = [fixture.ti(native, cwd, 'show', host['id'], '--json')['stdout']
               for cwd in (fixture.main, fixture.linked)]
    require(all(guest['comment'] in text and host['title'] in text for text in outputs),
            'guest change absent from one host worktree')
    histories = [fixture.ti(native, cwd, 'history', '--ticket', host['id'], '--json')['stdout']
                 for cwd in (fixture.main, fixture.linked)]
    require(json.loads(histories[0]) == json.loads(histories[1]) and '(comment added)' in histories[0],
            'shared history differs or lacks guest comment event')
    successful = [item for item in writes + guest['writes'] if item['exit'] == 0]
    require(any(item['exit'] == 0 for item in writes), 'no successful host concurrent writer')
    require(any(item['exit'] == 0 for item in guest['writes']), 'no successful guest writer')
    listings = [json.loads(fixture.ti(native, cwd, 'list', '--all', '--json')['stdout'])
                for cwd in (fixture.main, fixture.linked)]
    require(listings[0] == listings[1], 'main/linked list differs')
    ids = [item['stdout'].strip() for item in successful]
    require(len(ids) == len(set(ids)) and all(ids), 'successful creates lost distinct ticket identities')
    creation_fields, creation_histories = {}, {}
    for item in successful:
        ticket_id = item['stdout'].strip()
        creation_histories[ticket_id] = {}
        for cwd in (fixture.main, fixture.linked):
            ticket = json.loads(fixture.ti(native, cwd, 'show', ticket_id, '--json')['stdout'])
            require(ticket['title'] == item['title'], 'successful concurrent creation absent')
            require(bool(ticket['created_at']) and bool(ticket['created_by']), 'creation identity/time absent')
            # Native93 Store::create sets these five fields unconditionally;
            # history::query_history renders their JSON string values directly.
            # Presence in show/list is not evidence that any log event survived.
            expected = dict(title=item['title'], status='open', state='new',
                            **{'created-at': ticket['created_at'], 'created-by': ticket['created_by']})
            if ticket_id in creation_fields:
                require(creation_fields[ticket_id] == expected, 'main/linked creation fields differ')
            creation_fields[ticket_id] = expected
            history = json.loads(fixture.ti(native, cwd, 'history', '--ticket', ticket_id, '--json')['stdout'])
            for field, value in expected.items():
                require(any(event.get('field') == field and event.get('value') == value
                            and event.get('operation') == 'set' and event.get('email') == ticket['created_by']
                            for event in history),
                        f'native creation history missing {field} for {ticket_id} in {cwd.name}')
            creation_histories[ticket_id][cwd.name] = history
    database = fixture.main / '.git/git-meta.sqlite'
    with sqlite3.connect(f'file:{database}?mode=ro', uri=True) as connection:
        require(connection.execute('pragma integrity_check').fetchone() == ('ok',), 'SQLite integrity failed')
        require(connection.execute('pragma journal_mode').fetchone() == ('wal',), 'SQLite not in WAL mode')
        # Independent read-only SQLite oracle: do not infer persistence merely
        # because two CLI calls render the same cached/incorrect JSON.
        values = [json.loads(row[0]) for row in connection.execute('select value from metadata')]
        for title in [host['title'], *(item['title'] for item in successful)]:
            require(values.count(title) == 1, 'SQLite lost or duplicated a successful ticket title')
        comments = [json.loads(row[0]) for row in connection.execute('select value from list_values')]
        require(any(isinstance(value, dict) and value.get('body') == guest['comment'] for value in comments),
                'SQLite lacks the guest comment')
        events = connection.execute('select key,operation,email from metadata_log').fetchall()
        require(any(key.endswith(':comments') and operation == 'push' for key, operation, _ in events),
                'SQLite history lacks the guest comment event')
        sqlite_creation_events = {}
        for ticket_id, expected in creation_fields.items():
            sqlite_creation_events[ticket_id] = {}
            for field, value in expected.items():
                # Exact per-ticket keys and project target are Native93's store
                # contract, checked independently of the CLI history renderer.
                rows = connection.execute(
                    'select value,value_type,operation,email from metadata_log '
                    'where target_type = ? and target_value = ? and key = ?',
                    ('project', '', f'ticgit:tickets:{ticket_id}:{field}')).fetchall()
                require(any(json.loads(raw) == value and kind == 'string' and operation == 'set'
                            and email == expected['created-by'] for raw, kind, operation, email in rows),
                        f'SQLite creation history missing {field} for {ticket_id}')
                sqlite_creation_events[ticket_id][field] = rows
    files = {path.name: [path.stat().st_dev, path.stat().st_ino] for suffix in ('', '-wal', '-shm')
             if (path := Path(str(database) + suffix)).exists()}
    publish(fixture.root / 'shared-store.json', dict(files=files, successful_ids=ids,
            history=json.loads(histories[0]), sqlite_events=events,
            creation_histories=creation_histories, sqlite_creation_events=sqlite_creation_events,
            scope='functional shared-store smoke: independent host SQLite plus actual CLI outputs'))


def interactive(fixture, pi, failed=False):
    prompt = fixture.main / 'acceptance-prompt.md'
    prompt.write_text('This is a newly owned disposable acceptance fixture. Do not edit the checker, policy, or metadata. '
                      'Use your ordinary guest bash tool from the repository root to run exactly `python3 check_guest.py'
                      + (' --failed-startup' if failed else '') + '`. Do not retry on failure. '
                      'Report its result and then wait. The human will exit this TEST Pi normally. '
                      'Never stop a VM, another session, or provider.\n')
    environment = dict(os.environ)
    # Command-line Git overrides can outrank even fixture-local identity and
    # namespace. Clear them for this owned launch without changing host files.
    for key in list(environment):
        if key.startswith('GIT_'):
            environment.pop(key)
    # Isolate tracker/UI/config inheritance only for native fixture commands;
    # ordinary Pi deliberately uses installed host configuration and credentials.
    report = dict(scope='ordinary interactive TEST Pi exit only', passed=False)
    try:
        completed = subprocess.run([str(pi), '--no-session', '@' + str(prompt)], cwd=fixture.main, env=environment)
        report['exit'] = completed.returncode
        require(completed.returncode == 0, 'TEST Pi exited unsuccessfully; inspect pi-exit.json')
        report['passed'] = True
    except BaseException as error:
        report['failure'] = str(error)
        raise
    finally:
        publish(fixture.root / 'pi-exit.json', report)


def select_bundle(override=None):
    if override is not None:
        return override.resolve(strict=True)
    print('Selecting the ordinary Pi TicGit bundle; a cold cache may fetch and build the pinned source.',
          file=sys.stderr, flush=True)
    # This in-tree workflow deliberately couples to the launcher's private API,
    # not a second discovery/cache implementation or an independently deployed API.
    # Load only after host/TTY admission: image_runtime may consult real providers.
    launcher = runpy.run_path(str(DOTFILES / 'tools/codex-sandbox/codex-sandbox'))
    resolve = launcher['resolved_tic_build']
    resolve.__globals__['OUTER_RUNTIME'] = launcher['image_runtime']()
    # No fixture workspace exists yet. Use normal host State/configuration and
    # the admitted runtime's build_platform, never infer the guest from the host.
    state = launcher['new_state']([])
    try:
        build = resolve(state)
    except launcher['LauncherError'] as error:
        raise RuntimeError(str(error)) from error
    return build.broker_executable.parent.parent


def run_host(bundle, pi, destination):
    require(sys.platform.startswith('linux'), 'actual Linux host is required; macOS remains unproved')
    require(os.environ.get('DOTFILES_SANDBOX') != '1', 'BLOCKED: guest container is not the actual host/provider')
    require(sys.stdin.isatty() and sys.stdout.isatty(), 'interactive terminal required; do not pipe Pi into print mode')
    bundle = select_bundle(bundle)
    encoded, manifest, _ = protected_bundle(bundle)
    require(manifest['build']['host_platform'] == host_platform(), 'selected native does not match this Linux host')
    require(bundle.is_relative_to(Path.home() / '.cache/codex-sandbox/tic'),
            'select the actual launcher protected cache bundle, not a test-staged or writable development bundle')
    destination.mkdir(parents=True, exist_ok=True)
    root = destination / ('run-' + uuid.uuid4().hex)
    root.mkdir(mode=0o700)
    receipt = dict(scope='actual Linux interactive Pi functional smoke; no lifecycle or interleaving proof',
                   passed=False, phase='preparing',
                   bundle=str(bundle), manifest=json.loads(encoded), manifest_sha256=hashlib.sha256(encoded).hexdigest())
    publish(root / 'receipt.json', receipt)
    print(f'Preparing fresh acceptance repositories under {root}', flush=True)
    fixture = Fixture(root)
    try:
        fixture.prepare()
        native = bundle / manifest['native']['path']
        title = 'Host linked created before guest launch'
        created = fixture.ti(native, fixture.linked, 'new', '--title', title, '--id-only')['stdout'].strip()
        require(bool(created) and '\n' not in created, 'ambiguous host creation; no replay')
        host = dict(id=created, title=title)
        evidence = fixture.main / 'evidence'
        publish(evidence / 'host-created.json', host)
        errors, writes = [], []
        exited = threading.Event()

        def coordinate():
            try:
                deadline = time.monotonic() + 600
                while not (evidence / 'guest-ready.json').is_file():
                    require(not exited.wait(.02), 'TEST Pi exited before guest handshake')
                    require(time.monotonic() < deadline, 'guest handshake timed out')
                require(not exited.is_set(), 'TEST Pi exited before host writers started')
                publish(evidence / 'host-go.json', {'ready': True})
                for index in range(4):
                    title = f'host concurrent {index}'
                    output = fixture.ti(native, fixture.linked, 'new', '--title', title, '--id-only', success=False)
                    writes.append(dict(title=title, **output))
                    require(output['exit'] == 0 or any(word in output['stderr'].lower() for word in ('busy', 'locked')),
                            'host writer failed other than native contention')
            except Exception as error:
                errors.append(str(error))
            finally:
                publish(root / 'host-writes.json', dict(writes=writes, errors=errors))

        worker = threading.Thread(target=coordinate)
        worker.start()
        print('Opening NEW TEST Pi. After checker PASS, exit this Pi normally; keep other sessions untouched.', flush=True)
        receipt['phase'] = 'first-pi'
        try:
            interactive(fixture, pi)
            receipt['pi_exited'] = True
        finally:
            exited.set()
            # Once dispatched, mutation outcomes must be collected, never
            # abandoned/replayed when the interactive frontend closes early.
            worker.join()
        require(not errors, '; '.join(errors))
        guest = wait(evidence / 'guest.json', timeout=1)
        require(guest['passed'], 'guest phase failed; inspect guest.json')
        require(guest.get('client_sha256') == manifest['client']['sha256'],
                'actual guest client does not match selected protected cache manifest')
        receipt['phase'] = 'shared-store'
        verify_shared(fixture, native, host, guest, writes)
        receipt['shared_store'] = True
        receipt['phase'] = 'after-exit-host-use'
        # Native host remains independent after this owning TEST Pi exits.
        fixture.ti(native, fixture.linked, 'new', '--title', 'Host works after TEST Pi exit', '--id-only')
        receipt['after_exit_host_native'] = True
        receipt['phase'] = 'failed-startup'
        failure_root = root / 'failed-startup'
        failure_root.mkdir()
        failure = Fixture(failure_root)
        failure.prepare()
        # A local include is deliberately unsupported broker context, independent
        # of source fetching/cache state. It affects only this second fresh repo.
        failure.git(failure.main, 'config', 'include.path', str(failure.root / 'missing-config'))
        print('Opening second NEW TEST Pi: Tic startup must warn/disable; ordinary tools must work.', flush=True)
        interactive(failure, pi, failed=True)
        rejected = wait(failure.main / 'evidence/guest.json', timeout=1)
        require(rejected['passed'], 'failed-startup usable-Pi/guard check did not pass')
        require(not (failure.main / '.git/git-meta.sqlite').exists(), 'failed Tic startup opened a store')
        receipt.update(passed=True, phase='complete', shared_store=True, pi_exited=True,
                       after_exit_host_native=True, failed_startup_usable=True)
        print(f'PASS: Linux functional smoke. Receipts retained at {root}; no lifecycle or interleaving proof.')
    except BaseException as error:
        receipt['failure'] = str(error)
        raise
    finally:
        publish(root / 'receipt.json', receipt)
        print(f'Fixture and reports retained at {root}. Do not replay its checker; no provider stop attempted.', flush=True)
    return root


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--actual-linux-host', action='store_true', required=True,
                        help='explicitly authorize fresh fixture and two NEW ordinary interactive TEST Pi launches')
    parser.add_argument('--bundle', type=Path,
                        help='optional actual protected cache bundle override; default: ordinary Pi resolver')
    arguments = parser.parse_args()
    try:
        run_host(arguments.bundle, (DOTFILES / 'bin/pi').resolve(strict=True),
                 DOTFILES / 'target/tic-acceptance/linux')
    except (OSError, RuntimeError, subprocess.SubprocessError, ValueError) as error:
        print(f'STOP: {error}. No automatic retry or provider stop; inspect retained evidence before a NEW run.', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
