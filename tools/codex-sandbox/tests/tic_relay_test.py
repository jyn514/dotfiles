"""Private relay CLI and TCP-only probe; composed binary tests live with client."""
import contextlib
import io
from pathlib import Path
import signal
import socket
import sys
import time
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import tic_relay


class TicRelayTest(unittest.TestCase):
    def test_serve_uses_fixed_port_and_explicit_private_capacity(self):
        stopped = mock.Mock()
        stopped.wait.return_value = True
        bridge = mock.Mock()
        before = {signum: signal.getsignal(signum) for signum in (signal.SIGTERM, signal.SIGINT)}
        with mock.patch.object(tic_relay, 'FixedTcpBridge', return_value=bridge) as factory, mock.patch.object(
                tic_relay.threading, 'Event', return_value=stopped), \
                contextlib.redirect_stdout(io.StringIO()) as stdout:
            self.assertEqual(0, tic_relay.main(['--target-host', '192.0.2.1', '--target-port', '4321']))
        self.assertEqual(f'{tic_relay.READY_MESSAGE}\n', stdout.getvalue())
        factory.assert_called_once_with(('192.0.2.1', 4321), listen_address=('0.0.0.0', tic_relay.PORT),
                                        allow_all_peers=True, max_connections=16)
        bridge.start.assert_called_once_with()
        bridge.stop.assert_called_once_with()
        for signum, handler in before.items():
            self.assertIs(handler, signal.getsignal(signum))

    def test_start_failure_stops_without_retry_or_fallback(self):
        bridge = mock.Mock()
        bridge.start.side_effect = OSError('owned failed target')
        with mock.patch.object(tic_relay, 'FixedTcpBridge', return_value=bridge) as factory, contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(125, tic_relay.main(['--target-host', '192.0.2.1', '--target-port', '4321']))
        factory.assert_called_once()
        bridge.start.assert_called_once()
        bridge.stop.assert_called_once()

    def test_probe_connects_only_to_loopback_fixed_port_and_sends_no_application_bytes(self):
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            listener.listen(1)
            listener.settimeout(1)
            with mock.patch.object(tic_relay, 'PORT', listener.getsockname()[1]), mock.patch.object(
                    tic_relay, 'serve') as serve:
                self.assertEqual(0, tic_relay.main(['--probe']))
            serve.assert_not_called()
            with listener.accept()[0] as peer:
                peer.settimeout(1)
                self.assertEqual(b'', peer.recv(1), 'probe must not send credentials or a request')

    def test_absent_listener_probe_has_one_five_second_budget(self):
        # Bound but not listening: exclusively owned refused TCP endpoint, never
        # another user's service. No monkeypatched clock can hide an unbounded retry.
        with socket.socket() as reserved:
            reserved.bind(('127.0.0.1', 0))
            with mock.patch.object(tic_relay, 'PORT', reserved.getsockname()[1]), contextlib.redirect_stderr(io.StringIO()):
                start = time.monotonic()
                self.assertEqual(125, tic_relay.main(['--probe']))
                elapsed = time.monotonic() - start
        self.assertGreaterEqual(elapsed, 4.8)
        self.assertLess(elapsed, 6)

    def test_cli_cannot_select_listener_or_mix_probe_with_target(self):
        for argv in [[], ['--target-host', '192.0.2.1'], ['--target-host', '192.0.2.1', '--target-port', '0'],
                     ['--target-host', '192.0.2.1', '--target-port', '65536'],
                     ['--probe', '--target-port', '1'], ['--probe', '--target-host', '192.0.2.1'],
                     ['--probe', '--listen-port', '3333']]:
            with self.subTest(argv=argv), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as error:
                    tic_relay.main(argv)
                self.assertEqual(2, error.exception.code)


if __name__ == '__main__':
    unittest.main()
