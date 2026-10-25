"""Local Linux client -> relay process -> host bridge -> broker proof. No provider.

Set TIC_CANCELLATION_BUNDLE to a freshly built local bundle. Native process-bound
cases deliberately use a private fake executable; this does not prove native
TicGit command semantics. The production relay wrapper runs in an owned local
process, not a sidecar/VM. No socat or provider is involved.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import select
import signal
import socket
import subprocess
import sys
import tempfile
import time
import unittest

HERE = Path(__file__).resolve().parent
SANDBOX = HERE.parents[1] / 'codex-sandbox'
sys.path.insert(0, str(SANDBOX))
from host_tcp_bridge import FixedTcpBridge
from tic_relay import PORT

TOKEN = '0123456789abcdef0123456789abcdef'
PIN = (HERE.parent / 'native-revision').read_text().strip()


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def until(predicate, message, timeout=5):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        value = predicate()
        if value:
            return value
        time.sleep(0.01)
    raise AssertionError(message)


def frame(argv):
    data = json.dumps(dict(token=TOKEN, request=dict(version=2, command='tic', argv=argv, stdin=''))).encode()
    return len(data).to_bytes(4, 'big') + data


def alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False


@unittest.skipUnless(sys.platform.startswith('linux') and os.environ.get('TIC_CANCELLATION_BUNDLE'),
                     'set TIC_CANCELLATION_BUNDLE to a fresh reviewed local Linux build')
class LocalCancellationProof(unittest.TestCase):
    def setUp(self):
        self.owned = tempfile.TemporaryDirectory(prefix='tic-client-cancellation-')
        self.addCleanup(self.owned.cleanup)
        self.root = Path(self.owned.name)
        self.repo = self.root / 'repo'
        self.repo.mkdir()
        self.set_mode('block')
        subprocess.run(['git', 'init', '-qb', 'main', str(self.repo)], check=True, capture_output=True)
        self.bundle = Path(os.environ['TIC_CANCELLATION_BUNDLE']).resolve(strict=True)
        installed = json.loads((self.bundle / 'manifest.json').read_bytes())
        self.assertEqual(PIN, installed['native_revision'])
        for key in ('broker', 'client', 'native'):
            self.assertEqual(installed[key]['sha256'], digest(self.bundle / installed[key]['path']))
        self.client = self.bundle / installed['client']['path']
        self.native = self.root / 'client_fake_native'
        self.native.write_bytes((HERE / 'client_native.py').read_bytes())
        self.native.chmod(0o700)
        native_hash = digest(self.native)
        Path(str(self.native) + '.tic-proxy.json').write_text(json.dumps(dict(native_revision=PIN, policy_version=1, sha256=native_hash)))
        config = self.root / 'config.json'
        config.write_text(json.dumps(dict(version=1, workspace=str(self.repo), common_dir=str(self.repo / '.git'),
            native_executable=str(self.native), native_sha256=native_hash, user_name='Owned Fixture',
            user_email='owned@example.invalid', namespace='tickets', token=TOKEN)))
        config.chmod(0o600)
        reader, self.lifetime = os.pipe()
        try:
            self.broker = subprocess.Popen([str(self.bundle / installed['broker']['path']), '--config', str(config),
                '--lifetime-fd', str(reader)], pass_fds=(reader,), stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        finally:
            os.close(reader)
        self.addCleanup(self.stop_broker)
        self.assertTrue(select.select([self.broker.stdout], [], [], 5)[0], 'broker readiness missing')
        readiness = self.broker.stdout.readline()
        self.assertTrue(readiness, self.broker.stderr.read().decode() if self.broker.poll() is not None else 'empty readiness')
        host, port = json.loads(readiness)['address'].rsplit(':', 1)
        self.bridge = FixedTcpBridge((host, int(port)))
        self.bridge.allow_peers({'127.0.0.1'})
        self.bridge.start()
        self.addCleanup(self.bridge.stop)
        # The private wrapper has one fixed port. Reserve/check it without
        # contacting another service, then launch the exact production CLI.
        with socket.socket() as reserved:
            # Match the production relay: natural FIN leaves owned TIME_WAIT
            # sockets between cases, not a conflicting live listener.
            reserved.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                reserved.bind(('0.0.0.0', PORT))
            except OSError as error:
                self.skipTest(f'owned relay test port unavailable: {error}')
        self.relay = subprocess.Popen([sys.executable, str(SANDBOX / 'tic_relay.py'),
            '--target-host', '127.0.0.1', '--target-port', str(self.bridge.port)],
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.addCleanup(self.stop_relay)
        self.endpoint = ('127.0.0.1', PORT)
        probe = subprocess.run([sys.executable, str(SANDBOX / 'tic_relay.py'), '--probe'],
            stdin=subprocess.DEVNULL, capture_output=True, timeout=6)
        self.assertEqual(0, probe.returncode, probe.stderr)
        self.assertIsNone(self.relay.poll(), 'relay did not remain live')
        help_client = self.start_client(['--help'])
        stdout, stderr = help_client.communicate(timeout=5)
        self.assertEqual(0, help_client.returncode, stderr)
        self.assertIn(b'TicGit agent interface', stdout)
        self.assertEqual([], self.events(), 'TCP probe/authenticated help executed native')

    def stop_relay(self):
        if self.relay.poll() is None:
            self.relay.terminate()
        try:
            self.relay.communicate(timeout=3)
        except subprocess.TimeoutExpired:
            self.relay.kill()
            self.relay.communicate()
            self.fail('relay did not stop within signal cleanup bound')

    def stop_broker(self):
        if self.broker.poll() is None:
            os.kill(self.broker.pid, signal.SIGCONT)
        if self.lifetime is not None:
            os.close(self.lifetime)
            self.lifetime = None
        try:
            self.broker.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            self.broker.kill()
            self.broker.communicate()
            self.fail('broker did not stop/reap within lifetime bound')

    def set_mode(self, mode):
        (self.repo / 'client_mode').write_text(mode)

    def events(self):
        path = self.repo / 'client_events.jsonl'
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text().splitlines()]

    def start_client(self, argv):
        child = subprocess.Popen([str(self.client), *argv], cwd=self.repo,
            env={'SANDBOX_TIC_ENDPOINT': f'{self.endpoint[0]}:{self.endpoint[1]}', 'SANDBOX_TIC_TOKEN': TOKEN},
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        def cleanup():
            if child.poll() is None:
                child.kill()
            child.communicate()
        self.addCleanup(cleanup)
        return child

    def raw(self, argv, eof=False):
        client = socket.create_connection(self.endpoint, timeout=3)
        self.addCleanup(client.close)
        client.sendall(frame(argv))
        if eof:
            client.shutdown(socket.SHUT_WR)
        return client

    def test_open_request_side_survives_a_delayed_native_response(self):
        self.set_mode('delay')
        start = time.monotonic()
        client = self.start_client(['list'])
        stdout, stderr = client.communicate(timeout=5)
        self.assertEqual(17, client.returncode, stderr)
        self.assertIn(b'local native fixture completed', stdout)
        self.assertGreaterEqual(time.monotonic() - start, 1.25)
        self.assertEqual(1, len(self.events()))

    def test_delayed_backpressured_response_preserves_complete_frame_and_real_eof(self):
        self.set_mode('delay')
        client = self.raw(['list'])
        client.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 16384)
        until(lambda: self.events(), 'native did not start')
        time.sleep(1.6)  # Native responds after 1.25s; delay draining the relay.
        def exact(size):
            result = bytearray()
            while len(result) < size:
                chunk = client.recv(size - len(result))
                self.assertTrue(chunk, f'truncated response after {len(result)} of {size} bytes')
                result.extend(chunk)
            return bytes(result)
        size = int.from_bytes(exact(4), 'big')
        self.assertLessEqual(size, 32 * 1024 * 1024)
        response = json.loads(exact(size))
        self.assertEqual(b'', client.recv(1), 'RST must not be accepted as response EOF')
        self.assertEqual(17, response['exit'], response['stderr'])
        self.assertTrue(response['stdout'].endswith('x' * (2 * 1024 * 1024)))
        self.assertEqual(1, len(self.events()))

    def test_relay_signal_shutdown_cancels_and_reaps_its_running_request(self):
        client = self.start_client(['list'])
        events = until(lambda: self.events(), 'native did not start')
        pid = events[0]['pid']
        start = time.monotonic()
        self.relay.terminate()
        self.relay.communicate(timeout=3)
        self.assertEqual(0, self.relay.returncode)
        until(lambda: not alive(pid), 'native not reaped after relay signal', timeout=4)
        _, stderr = client.communicate(timeout=3)
        self.assertEqual(125, client.returncode, stderr)
        self.assertLess(time.monotonic() - start, 4)

    def test_process_exit_fin_cancels_and_reaps_running_native(self):
        client = self.start_client(['list'])
        events = until(lambda: self.events(), 'native did not start')
        pid = events[0]['pid']
        self.assertTrue(alive(pid))
        # Native fixture ignores SIGTERM. No response bytes exist; cancellation
        # must traverse the quiet bridge as ordinary EOF, then force kill and reap.
        start = time.monotonic()
        client.kill()
        client.communicate(timeout=3)
        until(lambda: not alive(pid), 'native not canceled/reaped after client exit', timeout=4)
        self.assertLess(time.monotonic() - start, 4)
        self.assertEqual(1, len(self.events()))
        self.set_mode('exit')
        fresh = self.start_client(['list'])
        _, stderr = fresh.communicate(timeout=5)
        self.assertEqual(17, fresh.returncode, stderr)

    def test_incomplete_frame_fin_through_bridge_executes_nothing(self):
        with socket.create_connection(self.endpoint, timeout=3) as client:
            client.sendall(frame(['list'])[:-1])
            client.shutdown(socket.SHUT_WR)
            # Request EOF is cancellation, never the missing admission step.
            def exact(size):
                data = bytearray()
                while len(data) < size:
                    part = client.recv(size - len(data))
                    self.assertTrue(part, 'truncated cancellation response')
                    data.extend(part)
                return bytes(data)
            size = int.from_bytes(exact(4), 'big')
            self.assertLessEqual(size, 32 * 1024 * 1024)
            response = json.loads(exact(size))
            self.assertEqual(2, response['version'])
            self.assertEqual(125, response['exit'])
            self.assertEqual(b'', client.recv(1))
        self.assertEqual([], self.events())
        self.set_mode('exit')
        fresh = self.start_client(['list'])
        _, stderr = fresh.communicate(timeout=5)
        self.assertEqual(17, fresh.returncode, stderr)
        self.assertEqual([['list']], [event['argv'] for event in self.events()])

    def test_fresh_broker_rejects_excess_real_clients_without_late_execution(self):
        active = [self.raw(['list']) for _ in range(8)]
        until(lambda: len(self.events()) == 8, 'native worker capacity not occupied')
        old_pids = [event['pid'] for event in self.events()]
        started = time.monotonic()
        excess = [self.start_client(['new', '--title', f'excess-{index}']) for index in range(17)]
        for child in excess:
            _, stderr = child.communicate(timeout=5)
            self.assertEqual(125, child.returncode, stderr)
        self.assertLess(time.monotonic() - started, 5, 'excess clients waited behind native work')
        self.assertEqual(8, len(self.events()))
        for client in active:
            client.close()
        until(lambda: all(not alive(pid) for pid in old_pids), 'active natives not reaped')
        self.set_mode('exit')
        fresh = self.start_client(['list'])
        _, stderr = fresh.communicate(timeout=5)
        self.assertEqual(17, fresh.returncode, stderr)
        time.sleep(0.5)
        self.assertEqual(9, len(self.events()))
        self.assertFalse(any(event['argv'][0] == 'new' for event in self.events()), 'rejected request executed later')


if __name__ == '__main__':
    unittest.main()
