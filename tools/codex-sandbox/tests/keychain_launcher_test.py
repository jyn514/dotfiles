"""Launcher capability publication and failure ownership, without Keychain UI."""

from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import runpy
import threading
from types import SimpleNamespace
import unittest
from unittest import mock


class KeychainLauncherTest(unittest.TestCase):
    def setUp(self):
        launcher = runpy.run_path(str(Path(__file__).resolve().parents[1] / 'codex-sandbox'))
        self.start = launcher['start_keychain']
        self.state = SimpleNamespace(suffix='owned-test', sidecar_image='image',
            keychain_networks=[], keychain_container=None, host_keychain=None)

    def test_startup_publishes_only_separate_metadata_after_peer_installation(self):
        calls = []
        bridge = mock.Mock(port=12345, token='capability')
        run = mock.Mock(return_value=SimpleNamespace(stdout='10.0.0.2'))
        with mock.patch.dict(self.start.__globals__,
                HostKeychainBridge=mock.Mock(return_value=bridge), run=run,
                create_relay_network=lambda state, name, **kw: calls.append((name, kw)),
                proxy_flags=lambda: []), mock.patch('sys.platform', 'darwin'), \
                mock.patch('pathlib.Path.is_file', return_value=True):
            arguments = self.start(self.state)
        self.assertEqual(len(calls), 2)
        self.assertEqual(dict((name, kw['internal']) for name, kw in calls), {
            'codex-keychain-link-owned-test': True,
            'codex-keychain-egress-owned-test': False,
        })
        self.assertIn('CODEX_SANDBOX_KEYCHAIN_ADDRESS=10.0.0.2:2224', arguments)
        self.assertIn('CODEX_SANDBOX_KEYCHAIN_TOKEN', arguments)
        self.assertNotIn('capability', str(run.call_args_list))
        bridge.allow_peers.assert_called_once_with({'10.0.0.2', '127.0.0.1'})
        container = run.call_args_list[0].args[0]
        self.assertIn('--cap-drop=ALL', container)
        self.assertIn('/usr/bin/socat', container)
        self.assertEqual(self.state.keychain_container, 'codex-keychain-owned-test')

    def test_partial_startup_invalidates_listener_but_keeps_cleanup_registration(self):
        bridge = mock.Mock(port=12345)
        with mock.patch.dict(self.start.__globals__,
                HostKeychainBridge=mock.Mock(return_value=bridge),
                run=mock.Mock(side_effect=OSError('private setup detail')),
                create_relay_network=mock.Mock(), proxy_flags=lambda: []), \
                mock.patch('sys.platform', 'darwin'), \
                mock.patch('pathlib.Path.is_file', return_value=True):
            self.assertEqual(self.start(self.state), [])
        bridge.stop.assert_called_once()
        self.assertIsNone(self.state.host_keychain)
        self.assertEqual(len(self.state.keychain_networks), 2)
        self.assertIsNotNone(self.state.keychain_container)

    def test_unsupported_host_creates_nothing(self):
        with mock.patch('sys.platform', 'linux'):
            self.assertEqual(self.start(self.state), [])
        self.assertEqual(self.state.keychain_networks, [])
        self.assertIsNone(self.state.host_keychain)

    def test_failed_network_waits_for_concurrent_creation_before_cleanup(self):
        egress_started = threading.Event()
        link_failed = threading.Event()
        release_egress = threading.Event()
        egress_finished = threading.Event()

        def create(state, name, *, internal):
            self.assertEqual(len(state.keychain_networks), 2)
            if internal:
                self.assertTrue(egress_started.wait(2))
                link_failed.set()
                raise OSError('network creation failed')
            egress_started.set()
            self.assertTrue(release_egress.wait(2))
            egress_finished.set()

        bridge = mock.Mock()
        with mock.patch.dict(self.start.__globals__, create_relay_network=create,
                HostKeychainBridge=bridge), mock.patch('sys.platform', 'darwin'), \
                mock.patch('pathlib.Path.is_file', return_value=True), \
                ThreadPoolExecutor(max_workers=1) as executor:
            result = executor.submit(self.start, self.state)
            try:
                self.assertTrue(link_failed.wait(2))
                self.assertFalse(result.done())
            finally:
                release_egress.set()
            self.assertEqual(result.result(timeout=2), [])
        self.assertTrue(egress_finished.is_set())
        bridge.assert_not_called()
        self.assertEqual(len(self.state.keychain_networks), 2)


if __name__ == '__main__':
    unittest.main()
