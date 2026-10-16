"""Real socket and child-process tests for the fixed Keychain capability."""

import json
import os
from pathlib import Path
import socket
import signal
import struct
import subprocess
import sys
import threading
import time
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import keychain_bridge as relay


def frame(value):
    data = json.dumps(value).encode()
    return struct.pack('>I', len(data)) + data


class BridgeTest(unittest.TestCase):
    def setUp(self):
        self.children = []
        self.accounts = []
        self.mode = 'ok'
        popen = subprocess.Popen

        def spawn(argv, **options):
            self.assertEqual(argv[:4], ['/usr/bin/security', 'find-generic-password',
                                       '-s', 'dev.jyn.flower.r2'])
            self.assertEqual(argv[4], '-a')
            self.assertEqual(argv[6:], ['-w'])
            self.accounts.append(argv[5])
            reader, writer = os.pipe()
            try:
                child = popen([sys.executable, str(Path(__file__).with_name('keychain_child.py')),
                               self.mode, argv[5], str(writer)], pass_fds=(writer,), **options)
                os.close(writer)
                writer = None
                self.assertEqual(os.read(reader, 1), b'1')
            finally:
                os.close(reader)
                if writer is not None:
                    os.close(writer)
            self.children.append(child)
            return child

        self.patch = mock.patch.object(relay.subprocess, 'Popen', side_effect=spawn)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.bridge = relay.HostKeychainBridge()
        self.addCleanup(self.bridge.stop)
        self.bridge.start()
        self.bridge.allow_peers({'127.0.0.1'})

    def connect(self):
        connection = socket.create_connection(('127.0.0.1', self.bridge.port), timeout=3)
        self.addCleanup(connection.close)
        return connection

    def request(self):
        return {'version': 1, 'token': self.bridge.token, 'operation': 'flower-r2/read'}

    def response(self, connection):
        data = bytearray()
        while part := connection.recv(16384):
            data.extend(part)
        self.assertEqual(struct.unpack('>I', data[:4])[0], len(data) - 4)
        response = json.loads(data[4:])
        # Socket EOF can precede the handler thread's return. These sequential
        # fixture requests must not race the bridge's explicit excess-connection
        # rejection, which remains covered separately below.
        worker = self.bridge.worker
        self.assertIsNotNone(worker)
        worker.join(timeout=3)
        self.assertFalse(worker.is_alive(), 'completed request worker did not exit')
        return response

    def test_response_waits_for_worker_exit_after_native_handler_closes_socket(self):
        native_handle = self.bridge._handle
        handler_closed = threading.Event()
        release_worker = threading.Event()
        eof_observed = threading.Event()
        response_done = threading.Event()
        outcome = {}

        def hold_after_close(connection):
            native_handle(connection)
            handler_closed.set()
            # Model the scheduling window after native socket closure but
            # before request-thread exit makes admission available again.
            release_worker.wait(6)

        def read_response(connection):
            try:
                outcome['response'] = self.response(connection)
            except BaseException as error:
                outcome['error'] = error
            finally:
                response_done.set()

        self.mode = 'deny-first'
        reader = None
        try:
            with mock.patch.object(self.bridge, '_handle', side_effect=hold_after_close):
                connection = self.connect()
                connection.sendall(frame(self.request()))
                self.assertTrue(handler_closed.wait(3), 'native handler did not close socket')
                worker = self.bridge.worker
                self.assertTrue(worker.is_alive())

                def receive(size):
                    part = connection.recv(size)
                    if not part:
                        eof_observed.set()
                    return part

                observed = mock.Mock(wraps=connection)
                observed.recv.side_effect = receive
                reader = threading.Thread(target=read_response, args=(observed,))
                reader.start()
                self.assertTrue(eof_observed.wait(3), 'response reader did not observe native EOF')
                self.assertFalse(response_done.wait(.1),
                                 'response helper completed while the request worker was still held')
                release_worker.set()
                reader.join(timeout=3)
                self.assertFalse(reader.is_alive())
            if 'error' in outcome:
                raise outcome['error']
            self.assertEqual(outcome['response'], {'version': 1, 'status': 'unavailable'})
            self.assertFalse(worker.is_alive())
            self.assertEqual(self.accounts, ['access-key'])
            self.mode = 'ok'
            second = self.connect()
            second.sendall(frame(self.request()))
            self.assertEqual(self.response(second), {
                'version': 1, 'status': 'ok', 'access_key': 'canary-access-key',
                'secret_key': 'canary-secret-key'})
            self.assertEqual(self.accounts, ['access-key', 'access-key', 'secret-key'])
        finally:
            release_worker.set()
            if reader is not None:
                reader.join(timeout=3)

    def test_success_returns_pair_in_order_and_closes(self):
        connection = self.connect()
        connection.sendall(frame(self.request()))
        self.assertEqual(self.response(connection), {
            'version': 1, 'status': 'ok', 'access_key': 'canary-access-key',
            'secret_key': 'canary-secret-key'})
        self.assertEqual(self.accounts, ['access-key', 'secret-key'])
        self.assertTrue(all(child.poll() == 0 for child in self.children))

    def test_invalid_authority_never_starts_child(self):
        for changes in ({'token': 'wrong'}, {'version': True}, {'operation': 'exec'},
                        {'account': 'arbitrary'}, {'token': '\u2603'}):
            with self.subTest(changes=changes):
                connection = self.connect()
                connection.sendall(frame(self.request() | changes))
                self.assertEqual(self.response(connection), {'version': 1, 'status': 'unavailable'})
        self.assertEqual(self.children, [])

    def test_duplicate_fields_rejected(self):
        data = json.dumps(self.request())[:-1] + ', "version": 1}'
        connection = self.connect()
        connection.sendall(struct.pack('>I', len(data)) + data.encode())
        self.assertEqual(self.response(connection)['status'], 'unavailable')
        self.assertEqual(self.children, [])

    def test_denial_discards_partial_credentials(self):
        for mode, accounts in [('deny-first', ['access-key']),
                               ('deny-second', ['access-key', 'secret-key'])]:
            with self.subTest(mode=mode):
                self.mode = mode
                self.accounts.clear()
                connection = self.connect()
                connection.sendall(frame(self.request()))
                self.assertEqual(self.response(connection), {'version': 1, 'status': 'unavailable'})
                self.assertEqual(self.accounts, accounts)

    def test_oversized_child_output_is_unavailable(self):
        self.mode = 'oversize'
        connection = self.connect()
        connection.sendall(frame(self.request()))
        self.assertEqual(self.response(connection)['status'], 'unavailable')
        self.assertEqual(self.accounts, ['access-key'])

    def test_disconnect_kills_resistant_child_and_rejects_excess(self):
        self.mode = 'stall'
        connection = self.connect()
        connection.sendall(frame(self.request()))
        deadline = time.monotonic() + 3
        while not self.children and time.monotonic() < deadline:
            time.sleep(.01)
        self.assertEqual(len(self.children), 1)
        excess = self.connect()
        self.assertEqual(excess.recv(1), b'')
        connection.shutdown(socket.SHUT_WR)
        self.assertEqual(self.response(connection)['status'], 'unavailable')
        self.assertIsNotNone(self.children[0].poll())
        self.assertEqual(self.children[0].returncode, -signal.SIGKILL)
        self.assertEqual(self.accounts, ['access-key'])

    def test_partial_request_deadline(self):
        with mock.patch.object(relay, 'REQUEST_SECONDS', .05):
            connection = self.connect()
            connection.sendall(b'\x00')
            self.assertEqual(self.response(connection)['status'], 'unavailable')
        self.assertEqual(self.children, [])

    def test_stop_cancels_active_request(self):
        self.mode = 'stall'
        connection = self.connect()
        connection.sendall(frame(self.request()))
        deadline = time.monotonic() + 3
        while not self.children and time.monotonic() < deadline:
            time.sleep(.01)
        self.bridge.stop()
        self.assertTrue(self.children)
        self.assertTrue(all(child.poll() is not None for child in self.children))
        self.assertEqual(self.bridge.token, '')

    def test_read_timeout_discards_value_and_kills_child(self):
        self.mode = 'stall'
        with mock.patch.object(relay, 'READ_SECONDS', .1):
            connection = self.connect()
            connection.sendall(frame(self.request()))
            self.assertEqual(self.response(connection), {'version': 1, 'status': 'unavailable'})
        self.assertEqual(self.children[0].returncode, -signal.SIGKILL)
        self.assertEqual(self.accounts, ['access-key'])

    def test_wrong_peer_never_starts_child(self):
        self.bridge.allow_peers(set())
        connection = self.connect()
        self.assertEqual(connection.recv(1), b'')
        self.assertEqual(self.children, [])


class SetupCleanupTest(unittest.TestCase):
    def test_failed_bridge_start_restores_subprocess_for_later_tests(self):
        original = subprocess.Popen
        case = BridgeTest('test_success_returns_pair_in_order_and_closes')
        result = unittest.TestResult()
        try:
            with mock.patch.object(relay.HostKeychainBridge, 'start',
                                   side_effect=PermissionError('socket denied')):
                case.run(result)
            self.assertEqual(len(result.errors), 1)
            self.assertIn('socket denied', result.errors[0][1])
            self.assertIs(subprocess.Popen, original)
            self.assertTrue(case.bridge.stopping.is_set())
        finally:
            # Keep this regression test isolated even when the fixture regresses.
            case.patch.stop()
            case.bridge.stop()


if __name__ == '__main__':
    unittest.main()
