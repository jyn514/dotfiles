"""Opt-in disposable Linux boundary acceptance through a selected immutable bundle.

Run with TIC_BOUNDARY_BUNDLE and optionally TIC_BOUNDARY_EVIDENCE. No builder,
launcher, provider, user store, or persistent host configuration is touched.
Trace assertions cover this bounded command sample, not arbitrary native code.
Helper observations are not a blanket no-child-program acceptance requirement;
the boundary is guest control over executable/path/unsafe arguments/environment.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import select
import shutil
import socket
import sqlite3
import struct
import subprocess
import tempfile
import time
import unittest

TOKEN = 'boundary-owned-authentication-token-20261025'
MAX_REQUEST = 8 * 1024 * 1024


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class Fixture:
    def __init__(self, case, label, separate=False):
        self.case = case
        self.label = label
        self.root = Path(case.temporary.name) / label
        self.root.mkdir()
        self.workspace = self.root / 'workspace'
        self.common = self.root / 'nonstandard-metadata' if separate else self.workspace / '.git'
        args = ['init', '-qb', 'main']
        if separate:
            args += ['--separate-git-dir', str(self.common)]
        self.git(*args, str(self.workspace), cwd=self.root)
        self.home = self.root / 'home'
        self.home.mkdir()
        self.canary = self.root / 'unauthorized-host-file'
        self.canary.write_text('BOUNDARY_EXTERNAL_CANARY_α\n')
        (self.workspace / 'workspace-link').symlink_to(self.canary)
        self.marker = self.root / 'helper-executed'
        self.helper = self.root / 'hostile-editor'
        self.helper.write_text('#!/bin/sh\nprintf helper > "' + str(self.marker) + '"\nexit 1\n')
        self.helper.chmod(0o700)
        self.git('config', 'core.editor', str(self.helper))
        self.git('config', 'user.name', 'Local Wrong Name')
        self.git('config', 'user.email', 'local-wrong@example.invalid')
        self.git('config', 'meta.namespace', 'local-wrong')
        (self.workspace / '.git-meta').write_text(
            '[meta]\nremote = http://127.0.0.1:9/never\nnamespace = hostile-dot-git-meta\n')
        self.process = None
        self.writer = None

    def git(self, *args, cwd=None):
        result = subprocess.run(['git', *args], cwd=cwd or self.workspace,
                                env={'PATH': os.environ['PATH'], 'HOME': str(self.root),
                                     'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': '/dev/null'},
                                capture_output=True, text=True, timeout=10)
        self.case.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.strip()

    def linked(self):
        self.git('-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid',
                 'commit', '--allow-empty', '-qm', 'fixture')
        linked = self.root / 'linked'
        self.git('worktree', 'add', '-qb', 'linked', str(linked))
        self.workspace = linked
        self.invocation = self.common / 'worktrees' / 'linked'
        return self

    def environment(self):
        global_config = self.home / '.gitconfig'
        global_config.write_text('[user]\nname = Global Wrong\nemail = global-wrong@example.invalid\n'
                                 '[meta]\nnamespace = global-wrong\n[include]\npath = ' + str(self.canary) + '\n')
        self.system = self.root / 'system-gitconfig'
        self.system.write_text('[user]\nname = System Wrong\nemail = system-wrong@example.invalid\n')
        return {'PATH': str(self.workspace) + os.pathsep + os.environ['PATH'], 'HOME': str(self.home),
                'TERM': 'guest-controlled-terminal', 'TERMINFO': str(self.canary),
                'TERMINFO_DIRS': str(self.workspace),
                'GIT_CONFIG_SYSTEM': str(self.system), 'GIT_CONFIG_GLOBAL': str(global_config),
                'GIT_CONFIG_COUNT': '3', 'GIT_CONFIG_KEY_0': 'user.name',
                'GIT_CONFIG_VALUE_0': 'Inherited Wrong', 'GIT_CONFIG_KEY_1': 'user.email',
                'GIT_CONFIG_VALUE_1': 'inherited-wrong@example.invalid',
                'GIT_CONFIG_KEY_2': 'meta.namespace', 'GIT_CONFIG_VALUE_2': 'inherited-wrong',
                'EDITOR': str(self.helper), 'VISUAL': str(self.helper), 'GIT_EDITOR': str(self.helper),
                'SSH_AUTH_SOCK': str(self.root / 'never-socket')}

    def trace_command(self, executable, args):
        self.trace = self.case.evidence / (self.label + '.strace')
        return ['strace', '-f', '-qq', '-s', '2048', '-e', 'trace=%process,%file,%network',
                '-o', str(self.trace), str(executable), *args]

    def start(self, native=None, reject=False):
        native = native or self.case.bundle / 'native/ti'
        config = {'version': 1, 'workspace': str(self.workspace), 'common_dir': str(self.common),
                  'native_executable': str(native), 'native_sha256': digest(native),
                  'user_name': 'Boundary Accepted', 'user_email': 'accepted@example.invalid',
                  'namespace': 'accepted-boundary', 'token': TOKEN}
        config_path = self.root / 'broker.json'
        config_path.write_text(json.dumps(config))
        config_path.chmod(0o600)
        reader, self.writer = os.pipe()
        command = self.trace_command(self.case.bundle / 'host/tic-broker',
                                     ['--config', str(config_path), '--lifetime-fd', str(reader)])
        self.process = subprocess.Popen(command, env=self.environment(), pass_fds=(reader,),
                                        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        os.close(reader)
        if reject:
            stdout, stderr = self.process.communicate(timeout=8)
            self.case.record(self.label + '-startup', {'exit': self.process.returncode,
                                                      'stdout': stdout.decode(), 'stderr': stderr.decode()})
            self.case.assertNotEqual(self.process.returncode, 0)
            self.case.assertEqual(stdout, b'')
            self.no_store()
            return stderr.decode()
        readable, _, _ = select.select([self.process.stdout], [], [], 8)
        self.case.assertTrue(readable, 'broker readiness timeout')
        line = self.process.stdout.readline()
        self.case.assertTrue(line, self.process.stderr.read().decode()) if not line else None
        ready = json.loads(line)
        self.case.assertEqual(ready['version'], 1)
        self.case.assertEqual(ready['native_revision'], self.case.manifest['native_revision'])
        self.case.record(self.label + '-ready', ready)
        host, port = ready['address'].split(':')
        self.address = (host, int(port))
        self.no_store()
        return self

    def no_store(self):
        dirs = [self.common, getattr(self, 'invocation', self.common)]
        for directory in dirs:
            for name in ['git-meta.sqlite', 'git-meta.sqlite-wal', 'git-meta.sqlite-shm']:
                self.case.assertFalse(os.path.lexists(directory / name), str(directory / name))

    def request(self, argv, stdin='', oversize=False):
        envelope = {'token': TOKEN, 'request': {'version': 2, 'command': 'tic', 'argv': argv, 'stdin': stdin}}
        body = json.dumps(envelope, ensure_ascii=False).encode()
        with socket.create_connection(self.address, timeout=8) as connection:
            connection.settimeout(35)
            if oversize:
                connection.sendall(struct.pack('>I', MAX_REQUEST + 1))
            else:
                connection.sendall(struct.pack('>I', len(body)) + body)
            def receive(size):
                result = b''
                while len(result) < size:
                    part = connection.recv(size - len(result))
                    if not part:
                        raise AssertionError('unexpected broker EOF')
                    result += part
                return result
            length = struct.unpack('>I', receive(4))[0]
            result = json.loads(receive(length))
            self.case.assertEqual(connection.recv(1), b'')
        self.case.record(self.label + '-requests', {'argv': argv, 'stdin': stdin,
                                                  'oversize_header': oversize, 'response': result}, append=True)
        return result

    def success(self, argv, stdin=''):
        result = self.request(argv, stdin)
        self.case.assertEqual(result['exit'], 0, result)
        return result['stdout']

    def stop(self):
        if self.writer is not None:
            os.close(self.writer)
            self.writer = None
        if self.process:
            try:
                stdout, stderr = self.process.communicate(timeout=6)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.communicate()
                raise AssertionError('fixture broker did not stop after lifetime EOF')
            self.case.record(self.label + '-shutdown', {'exit': self.process.returncode,
                                                       'stdout': stdout.decode(), 'stderr': stderr.decode()})
            self.process = None

    def assert_trace_boundary(self, native=None):
        self.stop()
        trace = self.trace.read_text()
        native = native or self.case.bundle / 'native/ti'
        execs = [line for line in trace.splitlines() if re.search(r'\bexecve(at)?\(', line)]
        self.case.assertGreaterEqual(len(execs), 2, 'trace must observe broker and native')
        # A fixed helper in trusted native code is not a guest-selected command.
        # Record helper effects; assert the concrete editor/canary boundaries.
        helper_execs = [line for line in execs
                        if str(self.case.bundle / 'host/tic-broker') not in line and str(native) not in line]
        self.case.assertFalse(any(str(self.helper) in line for line in execs))
        for path in [self.canary, self.system, self.home / '.gitconfig', self.workspace / 'workspace-link']:
            opened = [line for line in trace.splitlines()
                      if re.search(r'\b(open|openat|openat2)\(', line) and '"' + str(path) + '"' in line]
            self.case.assertEqual(opened, [], str(path))
        self.case.assertFalse(self.marker.exists())
        native_pids = {line.split()[0] for line in execs if str(native) in line}
        self.case.assertTrue(native_pids)
        network = [line for line in trace.splitlines() if line.split()[0] in native_pids
                   and re.search(r'\b(socket|connect|sendto|recvfrom|bind|listen)\(', line)]
        self.case.assertEqual(network, [])
        self.case.record(self.label + '-trace-summary', {'executions': execs, 'native_pids': sorted(native_pids),
                                                       'helper_execution_observations': helper_execs,
                                                       'native_network_calls': network})


@unittest.skipUnless(os.environ.get('TIC_BOUNDARY_BUNDLE'), 'opt in with TIC_BOUNDARY_BUNDLE')
class BoundaryAcceptance(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(shutil.which('strace'), 'Linux strace required')
        self.bundle = Path(os.environ['TIC_BOUNDARY_BUNDLE']).resolve()
        self.manifest = json.loads((self.bundle / 'manifest.json').read_text())
        for key in ['native', 'broker', 'client']:
            self.assertEqual(digest(self.bundle / self.manifest[key]['path']), self.manifest[key]['sha256'])
        self.temporary = tempfile.TemporaryDirectory(prefix='tic-boundary-owned-')
        self.addCleanup(self.temporary.cleanup)
        self.evidence = Path(os.environ.get('TIC_BOUNDARY_EVIDENCE', self.temporary.name))
        self.evidence.mkdir(parents=True, exist_ok=True)
        self.record('bundle', {'bundle': str(self.bundle), 'manifest': self.manifest})

    def record(self, label, value, append=False):
        path = self.evidence / (label + ('.jsonl' if append else '.json'))
        with path.open('a' if append else 'w') as stream:
            stream.write(json.dumps(value, ensure_ascii=False, indent=None if append else 2) + '\n')

    def fixture(self, label, **kwargs):
        fixture = Fixture(self, label, **kwargs)
        self.addCleanup(fixture.stop)
        return fixture

    def test_direct_authenticated_rejections_have_zero_native_executions(self):
        f = self.fixture('direct-reject')
        f.start()
        cases = [['new'], ['new', '-t', ''], ['new', '-t', ' \t'],
                 ['new', '-t', 'title', '--comment-edit'], ['edit'], ['comment'],
                 ['comment', '-etmissing', 'body'], ['spec'], ['state'], ['status'],
                 ['state', '--json'], ['status', '--ticket', 'missing'],
                 ['writeup', 'new', '-t', 'title'], ['writeup', 'new', '-t', ' ', '--body', ''],
                 ['writeup', 'edit', 'missing'], ['mine'], ['setup'],
                 ['edit', '-F', str(f.canary)], ['new', '--file=' + str(f.canary)],
                 ['spec', '-F', './-'], ['meta', 'key', '-F', 'workspace-link'],
                 ['writeup', 'new', '-t', 'title', '-F', str(f.canary)],
                 ['writeup', 'edit', 'missing', '-F', str(f.canary)]]
        for argv in cases:
            self.assertEqual(f.request(argv)['exit'], 2, argv)
        for argv in [[], ['list'], ['comment', 'body'], ['--help'],
                     ['writeup', 'edit', 'missing', '--body', 'body']]:
            self.assertEqual(f.request(argv, 'unexpected')['exit'], 2, argv)
        self.assertEqual(f.request(['edit', '-F-'], oversize=True)['exit'], 2)
        f.no_store()
        f.stop()
        execs = [line for line in f.trace.read_text().splitlines() if re.search(r'\bexecve(at)?\(', line)]
        self.assertEqual(len(execs), 1, execs)  # strace observed only the broker.
        self.assertIn(str(self.bundle / 'host/tic-broker'), execs[0])
        self.assertFalse(f.marker.exists())
        self.record('direct-reject-execs', execs)

    def test_all_six_native_stdin_forms_empty_and_nonempty_without_editor_fallback(self):
        f = self.fixture('stdin-forms').start()
        self.assertNotEqual(f.request(['new', '-F-'], '')['exit'], 0)
        ticket = json.loads(f.success(['new', '-cF-', '--json'], 'stdin title\n\nbody α\n'))
        ticket_id = ticket['id']
        self.assertEqual(ticket['title'], 'stdin title')
        self.assertEqual(ticket['description'], 'body α')
        self.assertNotEqual(f.request(['edit', ticket_id, '-F-'], '')['exit'], 0)
        edited = json.loads(f.success(['edit', ticket_id, '-F-', '--json'], 'edited title\n\nnew body\n'))
        self.assertEqual(edited['title'], 'edited title')
        self.assertEqual(edited['description'], 'new body')
        for text, expected in [('spec α\n', 'spec α'), ('', None)]:
            value = json.loads(f.success(['spec', '-t', ticket_id, '-F-', '--json'], text))
            self.assertEqual(value['spec'], expected)
        for text in ['meta α\n', '']:
            value = json.loads(f.success(['meta', 'boundary_field', '-t', ticket_id, '-F-', '--json'], text))
            self.assertEqual(value['meta']['boundary_field'], text)
        # File input to new writeup is BODY ONLY: its first line is not the title.
        writeup = f.success(['writeup', 'new', '-t', 'fixed title', '-F-', '--id-only'],
                            'body first line\nbody second line\n').strip()
        shown = f.success(['writeup', 'show', writeup, '--all'])
        self.assertIn('fixed title', shown)
        self.assertIn('body first line\nbody second line', shown)
        self.assertNotEqual(f.request(['writeup', 'edit', writeup, '-F-'], '')['exit'], 0)
        f.success(['writeup', 'edit', writeup, '-F-'], 'renamed only\n')
        shown = f.success(['writeup', 'show', writeup, '--all'])
        self.assertIn('renamed only', shown)
        self.assertIn('Versions: 1', shown)
        f.success(['writeup', 'edit', writeup, '--body', 'body-only version'])
        shown = f.success(['writeup', 'show', writeup, '--all'])
        self.assertIn('renamed only', shown)
        self.assertIn('Versions: 2', shown)
        f.success(['writeup', 'edit', writeup, '-F-'], 'third title\n\nthird body\n')
        shown = f.success(['writeup', 'show', writeup, '--all'])
        self.assertIn('third title', shown)
        self.assertIn('third body', shown)
        self.assertIn('Versions: 3', shown)
        empty = f.request(['writeup', 'new', '-t', 'empty-body validation', '-F-', '--id-only'], '')
        self.assertEqual(empty['exit'], 1)
        self.assertIn('writeup version body cannot be empty', empty['stderr'])
        f.assert_trace_boundary()

    def test_explicit_empty_inputs_aliases_lifecycle_and_double_dash_do_not_interact(self):
        f = self.fixture('explicit-inputs').start()
        ticket = f.success(['new', '-t', 'explicit', '--id-only']).strip()
        for argv in [['comment', '-t', ticket, ''], ['comment', '-t', ticket, '--', '--edit'],
                     ['spec', '-t', ticket, ''], ['state', '-t', ticket, ''],
                     ['status', '-t', ticket, '--', 'blocked'], ['state', '-t', ticket, 'resolved'],
                     ['meta', 'missing-value', '-t', ticket], ['ls', '--json'], ['next'],
                     ['writeup', 'new', '-t', 'empty explicit body', '--body', '']]:
            result = f.request(argv)
            self.assertNotIn(result['exit'], [124, 125], result)
        f.assert_trace_boundary()

    def test_plain_list_helper_observation_does_not_follow_guest_path(self):
        # Fixed tput calls are observations, not an automatic security defect.
        # A guest-writable cwd and hostile inherited PATH must not select this
        # owned executable; native command construction clears that environment.
        f = self.fixture('plain-list')
        marker = f.root / 'guest-tput-executed'
        (f.workspace / 'tput').write_text('#!/bin/sh\nprintf unsafe > "' + str(marker) + '"\n')
        (f.workspace / 'tput').chmod(0o700)
        f.start()
        for argv in [['list'], ['ls'], []]:
            f.success(argv)
        f.assert_trace_boundary()
        self.assertFalse(marker.exists(), 'guest PATH/cwd must not select a helper executable')
        trace = f.trace.read_text()
        self.assertNotIn('execve("' + str(f.workspace / 'tput') + '"', trace)
        observations = []
        for line in trace.splitlines():
            match = re.search(r'execve\("([^"]*/tput)", \["tput", "([^"]*)"\]', line)
            if match:
                path, arg = match.groups()
                self.assertTrue(Path(path).is_absolute())
                self.assertNotEqual(Path(path).parent, f.workspace)
                self.assertIn(arg, ['cols', 'lines'])
                observations.append({'executable': path, 'argument': arg, 'trace': line})
        self.record('plain-list-helper-boundary-observation', {
            'observations': observations, 'guest_tput_marker_absent': not marker.exists(),
            'classification': 'OBSERVED fixed native helper, not a zero-child-program gate',
            'successful_system_tput_execution_tested': False})

    def test_guest_relative_guest_only_stdin_and_literal_dash_file_handoff(self):
        f = self.fixture('guest-files').start()
        guest = f.root / 'guest-only' / 'nested'
        guest.mkdir(parents=True)
        files = [('draft.md', 'guest relative title\n\nguest body'), ('-', 'literal dash title\n')]
        for filename, content in files:
            (guest / filename).write_text(content)
        for args, stdin, title in [(['new', '-F', 'draft.md', '--json'], '', 'guest relative title'),
                                    (['new', '-F', './-', '--json'], '', 'literal dash title'),
                                    (['new', '-F', '-', '--json'], 'caller stdin title\n', 'caller stdin title')]:
            env = {'SANDBOX_TIC_ENDPOINT': '%s:%s' % f.address, 'SANDBOX_TIC_TOKEN': TOKEN}
            result = subprocess.run([str(self.bundle / 'guest/ti-proxy'), *args], cwd=guest, env=env,
                                    input=stdin, capture_output=True, text=True, timeout=12)
            self.record('guest-files-client', {'argv': args, 'stdin': stdin, 'exit': result.returncode,
                                             'stdout': result.stdout, 'stderr': result.stderr}, append=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)['title'], title)
        missing = subprocess.run([str(self.bundle / 'guest/ti-proxy'), 'new', '-F', 'absent-guest-file'],
                                 cwd=guest, env=env, capture_output=True, text=True, timeout=12)
        self.assertEqual(missing.returncode, 125)
        self.assertIn('cannot open guest input', missing.stderr)
        self.record('guest-files-missing', {'exit': missing.returncode, 'stderr': missing.stderr})
        f.assert_trace_boundary()
        trace = f.trace.read_text()
        native_execs = [line for line in trace.splitlines()
                        if re.search(r'\bexecve(at)?\(', line) and str(self.bundle / 'native/ti') in line]
        self.assertEqual(len(native_execs), 3, 'missing guest file must not execute native')
        for filename, _ in files:
            self.assertNotIn('"' + str(guest / filename) + '"', trace)
        self.assertNotIn('"draft.md"', trace)
        self.assertNotIn('"./-"', trace)

    def test_nonstandard_common_context_and_accepted_identity_apply(self):
        f = self.fixture('nonstandard', separate=True)
        inspect = subprocess.run([str(self.bundle / 'host/tic-broker'), 'inspect-context',
                                  '--workspace', str(f.workspace), '--common-dir', str(f.common)],
                                 capture_output=True, text=True, timeout=8, env=f.environment())
        self.assertEqual(inspect.returncode, 0, inspect.stderr)
        self.assertEqual(json.loads(inspect.stdout)['common_dir'], str(f.common))
        f.no_store()
        f.start()
        value = json.loads(f.success(['new', '-t', 'identity proof', '--json']))
        self.record('accepted-identity-ticket', value)
        self.assertIn('accepted@example.invalid', json.dumps(value))
        self.assertNotIn('wrong@example.invalid', json.dumps(value))
        self.assertTrue((f.common / 'git-meta.sqlite').exists())
        self.assertFalse((f.workspace / '.git/git-meta.sqlite').exists())
        f.assert_trace_boundary()

    def test_exact_forwarding_and_accepted_namespace_override_reach_native_environment(self):
        # A fake receiver proves broker delivery, not native domain semantics.
        f = self.fixture('exact-forwarding')
        native = f.root / 'owned-environment-receiver'
        native.write_text('#!/usr/bin/python3\nimport json, os, sys\n'
                          'print(json.dumps({"argv": sys.argv[1:], "stdin": sys.stdin.read(), '
                          '"env": dict(os.environ), "cwd": os.getcwd()}))\n')
        native.chmod(0o700)
        Path(str(native) + '.tic-proxy.json').write_text(json.dumps({
            'native_revision': self.manifest['native_revision'], 'policy_version': 1, 'sha256': digest(native)}))
        f.start(native=native)
        homes = []
        for argv, stdin in [(['new', '-cF-', '--comment=-F-'], 'title\n\nbody α\x00\n'),
                            (['edit', '-F-', '--', '-F-'], ''),
                            (['meta', 'field', '-F-'], 'literal\n')]:
            response = json.loads(f.success(argv, stdin))
            self.assertEqual(response['argv'], argv)
            self.assertEqual(response['stdin'], stdin)
            self.assertEqual(response['cwd'], str(f.workspace))
            env = response['env']
            self.assertEqual(env['GIT_CONFIG_COUNT'], '3')
            for number, key, value in [('0', 'user.name', 'Boundary Accepted'),
                                       ('1', 'user.email', 'accepted@example.invalid'),
                                       ('2', 'meta.namespace', 'accepted-boundary')]:
                self.assertEqual(env['GIT_CONFIG_KEY_' + number], key)
                self.assertEqual(env['GIT_CONFIG_VALUE_' + number], value)
            self.assertEqual(env['GIT_CONFIG_NOSYSTEM'], '1')
            self.assertEqual(env['GIT_CONFIG_GLOBAL'], '/dev/null')
            for key in ['GIT_CONFIG_SYSTEM', 'EDITOR', 'VISUAL', 'GIT_EDITOR', 'SSH_AUTH_SOCK',
                        'PATH', 'TERM', 'TERMINFO', 'TERMINFO_DIRS']:
                self.assertNotIn(key, env)
            homes.append(env['HOME'])
            self.assertFalse(Path(env['HOME']).exists(), 'request-private HOME must be removed before response')
        self.assertEqual(len(set(homes)), 3)
        f.assert_trace_boundary(native=native)

    def test_missing_blob_errors_do_not_fetch_or_launch_configured_editor(self):
        f = self.fixture('missing-blob').start()
        ticket = f.success(['new', '-t', 'missing blob fixture', '--id-only']).strip()
        # Trusted/pre-existing serialized metadata, not an agent-created ref.
        key = 'ticgit:tickets:' + ticket + ':title'
        with sqlite3.connect(f.common / 'git-meta.sqlite') as db:
            count = db.execute('select count(*) from metadata where key=?', (key,)).fetchone()[0]
            self.assertEqual(count, 1)
            db.execute('update metadata set value=?, is_git_ref=1 where key=?', ('1' * 40, key))
        f.git('config', 'remote.inert.url', 'http://127.0.0.1:9/never')
        f.git('config', 'remote.inert.promisor', 'true')
        f.git('config', 'remote.inert.partialclonefilter', 'blob:none')
        for argv in [['show', ticket, '--json'], ['list', '--json'],
                     ['comment', '-t', ticket, 'literal comment', '--json']]:
            result = f.request(argv)
            self.assertEqual(result['exit'], 1, result)
            self.assertIn('could not be found', result['stderr'])
        f.assert_trace_boundary()

    def test_trace_controls_detect_current_native_editor_and_external_file_read(self):
        # Controls are ordinary HUMAN commands against disposable canaries only.
        # They verify that trace silence in the agent tests is meaningful.
        f = self.fixture('trace-controls')
        env = {'HOME': str(f.home), 'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': '/dev/null',
               'EDITOR': str(f.helper), 'VISUAL': str(f.helper), 'GIT_EDITOR': str(f.helper),
               'TICGIT_STATE_FILE': str(f.root / 'human-ui.json')}
        native = self.bundle / 'native/ti'
        created = subprocess.run([str(native), 'new', '-t', 'human control', '--id-only'],
                                 cwd=f.workspace, env=env, capture_output=True, text=True, timeout=8)
        self.assertEqual(created.returncode, 0, created.stderr)
        ticket = created.stdout.strip()
        editor = subprocess.run(f.trace_command(native, ['comment', '-t', ticket, '-e']),
                                cwd=f.workspace, env=env, capture_output=True, text=True, timeout=8)
        self.assertNotEqual(editor.returncode, 0)
        self.assertTrue(f.marker.exists(), 'helper execution positive control must fire')
        self.assertIn(str(f.helper), f.trace.read_text())
        editor_trace = self.evidence / 'trace-controls-editor.strace'
        shutil.copyfile(f.trace, editor_trace)
        read = subprocess.run(f.trace_command(native, ['meta', 'control', '-t', ticket,
                                                       '-F', 'workspace-link', '--json']),
                              cwd=f.workspace, env=env, capture_output=True, text=True, timeout=8)
        self.assertEqual(read.returncode, 0, read.stderr)
        self.assertIn('BOUNDARY_EXTERNAL_CANARY_α', read.stdout)
        self.assertIn('"workspace-link"', f.trace.read_text())
        self.record('trace-controls-observed', {'editor_exit': editor.returncode,
                                              'helper_marker_present': f.marker.exists(),
                                              'external_canary_returned': True,
                                              'human_external_read_stdout': read.stdout})

    def test_includes_and_alternates_reject_in_real_broker_before_native(self):
        for label, location in [('common', 'config'), ('invocation-worktree', 'invocation'),
                                 ('common-worktree', 'config.worktree'), ('alternate', 'alternates'),
                                 ('dangling-alternate', 'dangling')]:
            f = self.fixture('preflight-' + label).linked()
            canary = f.root / 'include-fifo'
            os.mkfifo(canary)
            if location in ['invocation', 'config.worktree']:
                f.git('config', 'extensions.worktreeConfig', 'true')
                target = (f.invocation if location == 'invocation' else f.common) / 'config.worktree'
                target.write_text('[includeIf "gitdir:/never-active/"]\npath = ' + str(canary) + '\n')
            elif location == 'config':
                with (f.common / 'config').open('a') as stream:
                    stream.write('\n[include]\npath = ' + str(canary) + '\n')
            elif location == 'alternates':
                (f.common / 'objects/info/alternates').write_text(str(f.root / 'outside'))
            else:
                (f.common / 'objects/info/alternates').symlink_to(f.root / 'missing')
            error = f.start(reject=True)
            self.assertIn('unsupported', error)
            f.stop()
            trace = f.trace.read_text()
            execs = [line for line in trace.splitlines() if re.search(r'\bexecve(at)?\(', line)]
            self.assertEqual(len(execs), 1, execs)
            self.assertNotIn('"' + str(canary) + '"', trace)


if __name__ == '__main__':
    unittest.main()
