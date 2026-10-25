"""Focused Linux lifecycle gaps; owned local processes, never a VM/provider.

TIC_LIFETIME_BUNDLE names an explicitly selected current compiled bundle. These
checks do not establish RootImageAdmission or actual provider acceptance. Native
TicGit is used only by the human-offline case; fake native is intentional for
precise owner-death, broker-death and blocked-output process edges.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import select
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

SANDBOX = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SANDBOX))
sys.path.insert(0, str(SANDBOX.parent / 'tic-proxy'))
from bundle import build_identity, host_platform, validate_bundle
from tic_broker import InstalledTicBuild, TicBrokerLaunch


def until(predicate, description, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(.01)
    raise AssertionError(description)


def alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False


@unittest.skipUnless(sys.platform.startswith('linux') and os.environ.get('TIC_LIFETIME_BUNDLE'),
                     'select TIC_LIFETIME_BUNDLE for local Linux acceptance')
class TicLifetimeAcceptance(unittest.TestCase):
    def setUp(self):
        self.owned = tempfile.TemporaryDirectory(prefix='tic-lifetime-acceptance-')
        self.addCleanup(self.owned.cleanup)
        self.root = Path(self.owned.name).resolve()
        self.repo = self.root / 'repo'
        subprocess.run(['git', 'init', '-qb', 'main', str(self.repo)], check=True, capture_output=True)
        self.bundle = Path(os.environ['TIC_LIFETIME_BUNDLE']).resolve(strict=True)
        expected = build_identity(host_platform(), 'linux/amd64')
        # Refuse stale binary evidence rather than calling old source current.
        validate_bundle(self.bundle, expected)
        self.manifest = json.loads((self.bundle / 'manifest.json').read_bytes())
        self.native = self.root / 'owned_native'
        self.native.write_text(f'#!{sys.executable}\n' + '''import json, os, signal, sys, time
from pathlib import Path
signal.signal(signal.SIGTERM, signal.SIG_IGN)
mode = Path('mode').read_text().strip()
private = str(Path(os.environ['HOME']).parent)
fd = os.open('events.jsonl', os.O_CREAT | os.O_APPEND | os.O_WRONLY, 0o600)
os.write(fd, (json.dumps(dict(pid=os.getpid(), argv=sys.argv[1:], private=private))+'\\n').encode())
os.close(fd)
if mode == 'block':
    while True: time.sleep(.01)
if mode == 'output':
    # Let the test pause the broker before the child fills the OS pipe.
    while not Path('output-go').exists(): time.sleep(.01)
    while True: os.write(1, b'x' * 65536)
if mode == 'finish':
    while not Path('finish-go').exists(): time.sleep(.01)
    Path('mutation-finished').write_text('completed after broker death')
print('owned native completed')
sys.exit(17)
''')
        self.native.chmod(0o700)
        self.set_mode('block')
        self.binding(self.native)

    def binding(self, native):
        digest = hashlib.sha256(native.read_bytes()).hexdigest()
        Path(str(native) + '.tic-proxy.json').write_text(json.dumps(dict(
            native_revision=self.manifest['native_revision'], policy_version=1, sha256=digest)))

    def build(self, native=None):
        native = native or self.native
        manifest = self.manifest
        return InstalledTicBuild(
            self.bundle / manifest['broker']['path'], manifest['broker']['sha256'],
            native, hashlib.sha256(native.read_bytes()).hexdigest(),
            self.bundle / manifest['client']['path'], manifest['client']['sha256'],
            manifest['client']['platform'], manifest['native_revision'])

    def launch(self, native=None):
        launch = TicBrokerLaunch(self.build(native), workspace=self.repo, common_dir=self.repo / '.git',
                                 user_name='Owned Author', user_email='owned@example.invalid', namespace='tickets')
        self.addCleanup(launch.stop)
        return launch.start()

    def set_mode(self, mode):
        (self.repo / 'mode').write_text(mode)

    def events(self):
        path = self.repo / 'events.jsonl'
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def request(self, address, token, argv=('list',), stdin=''):
        host, port = address.rsplit(':', 1)
        connection = socket.create_connection((host, int(port)), timeout=3)
        self.addCleanup(connection.close)
        data = json.dumps(dict(token=token, request=dict(version=2, command='tic', argv=list(argv), stdin=stdin))).encode()
        connection.sendall(len(data).to_bytes(4, 'big') + data)
        return connection

    def response(self, connection):
        def exact(size):
            data = bytearray()
            while len(data) < size:
                part = connection.recv(size - len(data))
                self.assertTrue(part, 'truncated frame')
                data.extend(part)
            return data
        size = int.from_bytes(exact(4), 'big')
        self.assertLessEqual(size, 32 * 1024 * 1024)
        value = json.loads(exact(size))
        self.assertEqual(b'', connection.recv(1))
        return value

    def client(self, launch, argv):
        child = subprocess.Popen([str(self.build().guest_client_executable), *argv], cwd=self.repo,
                                 env=launch.environment(), stdin=subprocess.DEVNULL,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        def cleanup():
            if child.poll() is None:
                child.kill()
            child.communicate()
        self.addCleanup(cleanup)
        return child

    def test_direct_authenticated_argv_and_frame_bounds_reject_before_native_spawn(self):
        launch = self.launch()
        statuses = []
        for argv in (['list'] * 129, ['comment', 'x' * 65537],
                     ['comment'] + ['x' * 65536] * 5, ['comment', 'nul\0body']):
            result = self.response(self.request(launch.address, launch.token, argv))
            self.assertEqual(2, result['exit'])
            statuses.append(result['exit'])
        host, port = launch.address.rsplit(':', 1)
        with socket.create_connection((host, int(port)), timeout=3) as peer:
            # Header alone must reject; never allocate/read an oversized body.
            peer.sendall((8 * 1024 * 1024 + 1).to_bytes(4, 'big'))
            result = self.response(peer)
            self.assertEqual(2, result['exit'])
            statuses.append(result['exit'])
        # JSON cannot preserve an unpaired surrogate as UTF-8 native stdin.
        result = self.response(self.request(launch.address, launch.token, ['new', '-F', '-'], '\ud800'))
        self.assertEqual(2, result['exit'])
        statuses.append(result['exit'])
        self.assertEqual([], self.events())
        self.assertFalse((self.repo / '.git/git-meta.sqlite').exists())
        print(json.dumps(dict(case='direct-bounds', reject_statuses=statuses, native_executions=0,
                              tested=['argc>128', 'arg>64KiB', 'argv>256KiB', 'argv-NUL',
                                      'request-header>8MiB', 'unpaired-surrogate-stdin'])), flush=True)

    def test_unexpected_owner_death_closes_lifetime_stops_broker_and_native(self):
        # The subprocess owns the actual production Python launch adapter. Kill
        # only this disposable owner, not Pi, the current launcher, or a VM.
        program = '''import json, sys, time
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from tic_broker import InstalledTicBuild, TicBrokerLaunch
build = InstalledTicBuild(**{key: Path(value) if key.endswith('_executable') else value for key,value in json.loads(sys.argv[2]).items()})
repo = Path(sys.argv[3])
launch = TicBrokerLaunch(build, workspace=repo, common_dir=repo/'.git', user_name='Owned', user_email='owned@example.invalid', namespace='tickets').start()
print(json.dumps(dict(pid=launch.process.pid,address=launch.address,token=launch.token,directory=str(launch.directory))), flush=True)
while True: time.sleep(1)
'''
        build = {key: str(value) if isinstance(value, Path) else value for key, value in vars(self.build()).items()}
        owner = subprocess.Popen([sys.executable, '-c', program, str(SANDBOX), json.dumps(build), str(self.repo)],
                                 stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        def owner_cleanup():
            if owner.poll() is None:
                owner.kill()
            owner.communicate()
        self.addCleanup(owner_cleanup)
        self.assertTrue(select.select([owner.stdout], [], [], 5)[0], 'owner readiness timeout')
        line = owner.stdout.readline()
        self.assertTrue(line, owner.stderr.read().decode() if owner.poll() is not None else 'owner readiness empty')
        ready = json.loads(line)
        # Abrupt death intentionally bypasses Python scratch cleanup. Own this
        # exact reported launch scratch for test cleanup, never scan other dirs.
        self.addCleanup(lambda: shutil.rmtree(ready['directory'], ignore_errors=True))
        connection = self.request(ready['address'], ready['token'])
        event = until(lambda: self.events(), 'native did not start')[0]
        start = time.monotonic()
        owner.kill()
        owner.communicate(timeout=2)
        until(lambda: not alive(event['pid']), 'broker failed to reap native after owner death', 5)
        until(lambda: not alive(ready['pid']), 'broker did not exit on owner pipe EOF', 5)
        self.assertLess(time.monotonic() - start, 5)
        self.assertFalse(Path(event['private']).exists())
        host, port = ready['address'].rsplit(':', 1)
        with self.assertRaises(OSError):
            socket.create_connection((host, int(port)), timeout=.5)
        self.assertEqual(1, len(self.events()))
        print(json.dumps(dict(case='owner-death', owner_status=owner.returncode,
                              broker_pid=ready['pid'], native_pid=event['pid'],
                              elapsed=time.monotonic()-start, private_removed=True,
                              listener_refused=True, native_executions=len(self.events()))), flush=True)
        connection.close()

    def test_broker_death_is_unknown_without_replay_replacement_or_adopting_native(self):
        self.set_mode('finish')
        launch = self.launch()
        client = self.client(launch, ['new', '--title', 'unknown-outcome'])
        event = until(lambda: self.events(), 'native did not start')[0]
        self.addCleanup(lambda: shutil.rmtree(event['private'], ignore_errors=True))
        self.addCleanup(lambda: (self.repo / 'finish-go').touch())
        process = launch.process
        process.kill()
        process.wait(timeout=2)
        stdout, stderr = client.communicate(timeout=3)
        self.assertEqual(125, client.returncode, (stdout, stderr))
        self.assertIn(b'outcome unknown', stderr)
        self.assertTrue(alive(event['pid']), 'broker death must not imply child cancellation')
        # A later owning launch has fresh endpoint/token. Starting it neither
        # replays the lost request nor adopts/kills the old in-flight child.
        replacement = self.launch()
        self.assertNotEqual(launch.token, replacement.token)
        self.assertTrue(alive(event['pid']))
        time.sleep(.2)
        self.assertEqual(1, len(self.events()), 'lost request was replayed')
        (self.repo / 'finish-go').touch()
        until(lambda: (self.repo / 'mutation-finished').exists(), 'owned in-flight mutation did not finish')
        until(lambda: not alive(event['pid']), 'finished native remained live', 5)
        self.assertEqual(1, len(self.events()))
        self.assertIsNone(replacement.process.poll())
        self.set_mode('exit')
        result = self.response(self.request(replacement.address, replacement.token))
        self.assertEqual(17, result['exit'])
        self.assertEqual([['new', '--title', 'unknown-outcome'], ['list']], [item['argv'] for item in self.events()])
        # The broker cannot clean request-private scratch after it is SIGKILLed.
        # Test cleanup owns that known scratch; no historical PID action.
        print(json.dumps(dict(case='broker-death', broker_status=process.returncode,
                              client_status=client.returncode, client_stderr=stderr.decode(),
                              old_native_finished=True, native_argv=[item['argv'] for item in self.events()],
                              replacement_live=replacement.process.poll() is None)), flush=True)

    def test_cancellation_while_native_output_is_backpressured_reaps_child(self):
        self.set_mode('output')
        launch = self.launch()
        connection = self.request(launch.address, launch.token)
        event = until(lambda: self.events(), 'native did not start')[0]
        process = launch.process
        os.kill(process.pid, signal.SIGSTOP)
        self.addCleanup(lambda: os.kill(process.pid, signal.SIGCONT) if process.poll() is None else None)
        (self.repo / 'output-go').touch()
        until(lambda: 'pipe_write' in Path(f"/proc/{event['pid']}/wchan").read_text().strip(),
              'native did not block on undrained stdout pipe')
        blocked_wait = Path(f"/proc/{event['pid']}/wchan").read_text().strip()
        connection.shutdown(socket.SHUT_WR)
        start = time.monotonic()
        os.kill(process.pid, signal.SIGCONT)
        result = self.response(connection)
        self.assertEqual(125, result['exit'])
        until(lambda: not alive(event['pid']), 'output-blocked native not reaped')
        self.assertLess(time.monotonic() - start, 4)
        self.assertFalse(Path(event['private']).exists())
        print(json.dumps(dict(case='blocked-output-cancellation', blocked_wait=blocked_wait,
                              response_status=result['exit'], native_pid=event['pid'],
                              elapsed=time.monotonic()-start, private_removed=True)), flush=True)
        self.set_mode('exit')
        self.assertEqual(17, self.response(self.request(launch.address, launch.token))['exit'])

    def test_bridge_partial_start_failure_is_registered_and_owned_cleanup_releases_it(self):
        launch = self.launch()
        with mock.patch('tic_broker.FixedTcpBridge') as factory:
            bridge = factory.return_value
            bridge.start.side_effect = OSError('owned bridge bind failure')
            with self.assertRaisesRegex(OSError, 'owned bridge bind failure'):
                launch.start_bridge({'127.0.0.1'})
            self.assertIn(launch.bridge_resource, launch.registry.identities)
            result = launch.stop(47)
            self.assertEqual(47, result.primary_status)
            self.assertFalse(result.remaining)
            bridge.stop.assert_called_once_with()
            self.assertIsNone(launch.process)
            self.assertIsNone(launch.lifetime_writer)
            self.assertEqual('', launch.token)
            self.assertFalse(launch.directory.exists())
            print(json.dumps(dict(case='bridge-start-failure', primary_status=result.primary_status,
                                  remaining=list(result.remaining), bridge_stop_calls=bridge.stop.call_count,
                                  authority_revoked=True)), flush=True)

    def test_human_native_works_after_all_owned_guest_transport_and_brokers_stop(self):
        native = self.bundle / self.manifest['native']['path']
        one, two = self.launch(native), self.launch(native)
        self.assertNotEqual(one.address, two.address)
        self.assertNotEqual(one.token, two.token)
        bridge = one.start_bridge({'127.0.0.1'})
        created = self.response(self.request(f'127.0.0.1:{bridge.port}', one.token,
                                            ['new', '--title', 'before-transport-stop', '--id-only']))
        self.assertEqual(0, created['exit'], created)
        environment = one.environment(f'127.0.0.1:{bridge.port}')
        self.assertFalse(one.stop().remaining)
        self.assertIsNone(two.process.poll(), 'other launch stopped by first owner')
        self.assertFalse(two.stop().remaining)
        offline = subprocess.run([str(self.build().guest_client_executable), 'new', '--title', 'must-not-reroute'],
                                 cwd=self.repo, env=environment, stdin=subprocess.DEVNULL,
                                 capture_output=True, timeout=5)
        self.assertEqual(125, offline.returncode, offline)
        human_env = dict(HOME=str(self.root), GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL='/dev/null',
                         GIT_CONFIG_COUNT='3', GIT_CONFIG_KEY_0='user.name', GIT_CONFIG_VALUE_0='Human',
                         GIT_CONFIG_KEY_1='user.email', GIT_CONFIG_VALUE_1='human@example.invalid',
                         GIT_CONFIG_KEY_2='meta.namespace', GIT_CONFIG_VALUE_2='tickets',
                         TICGIT_STATE_FILE=str(self.root / 'human-state'))
        human = subprocess.run([str(native), 'new', '--title', 'human-without-transport', '--id-only'],
                               cwd=self.repo, env=human_env, capture_output=True, timeout=5)
        self.assertEqual(0, human.returncode, human)
        listed = subprocess.run([str(native), 'list', '--json'], cwd=self.repo, env=human_env,
                                capture_output=True, timeout=5)
        self.assertEqual(0, listed.returncode, listed)
        self.assertIn(b'before-transport-stop', listed.stdout)
        self.assertIn(b'human-without-transport', listed.stdout)
        self.assertNotIn(b'must-not-reroute', listed.stdout)
        self.assertTrue((self.repo / '.git/git-meta.sqlite').exists())
        print(json.dumps(dict(case='human-without-transport', offline_guest_status=offline.returncode,
                              human_status=human.returncode, human_list_status=listed.returncode,
                              human_list=json.loads(listed.stdout), actual_vm_stop_attempted=False)), flush=True)
        # No actual provider was selected and no actual VM stop was attempted.


if __name__ == '__main__':
    unittest.main()
