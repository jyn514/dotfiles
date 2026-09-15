"""Launcher capability publication and failure ownership, without Keychain UI."""

from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import json
import runpy
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest import mock


class KeychainLauncherTest(unittest.TestCase):
    def setUp(self):
        launcher = runpy.run_path(str(Path(__file__).resolve().parents[1] / 'codex-sandbox'))
        self.launcher = launcher
        self.start = launcher['start_keychain']
        self.state = SimpleNamespace(suffix='owned-test', sidecar_image='image', keychain_handle=None)

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
        self.assertEqual(self.state.keychain_handle.container, 'codex-keychain-owned-test')
        self.assertTrue(self.state.keychain_handle.projected)
        self.assertEqual(self.launcher['keychain_environment'](self.state),
                         {'CODEX_SANDBOX_KEYCHAIN_TOKEN': 'capability'})

    def test_partial_startup_invalidates_listener_but_keeps_cleanup_registration(self):
        bridge = mock.Mock(port=12345)
        with mock.patch.dict(self.start.__globals__,
                HostKeychainBridge=mock.Mock(return_value=bridge),
                run=mock.Mock(side_effect=OSError('private setup detail')),
                create_relay_network=mock.Mock(), proxy_flags=lambda: []), \
                mock.patch('sys.platform', 'darwin'), \
                mock.patch('pathlib.Path.is_file', return_value=True):
            self.assertEqual(self.start(self.state), [])
        bridge.stop.assert_not_called()
        self.assertFalse(self.state.keychain_handle.projected)
        self.assertEqual(self.launcher['keychain_environment'](self.state), {})
        self.assertIs(self.state.keychain_handle.bridge, bridge)
        self.assertEqual(len(self.state.keychain_handle.registry.identities), 4)
        self.state.keychain_handle.cleanup()
        bridge.stop.assert_called_once()

    def test_unsupported_host_creates_nothing(self):
        with mock.patch('sys.platform', 'linux'):
            self.assertEqual(self.start(self.state), [])
        self.assertIsNone(self.state.keychain_handle)

    def test_failed_network_waits_for_concurrent_creation_before_cleanup(self):
        egress_started = threading.Event()
        link_failed = threading.Event()
        release_egress = threading.Event()
        egress_finished = threading.Event()

        def create(state, name, *, internal, owner):
            self.assertRegex(owner, r'\A[0-9a-f]{32}\Z')
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
        self.assertEqual(len(self.state.keychain_handle.registry.identities), 2)

    def test_foreign_replacement_is_retained_and_never_removed(self):
        handle = self.launcher['KeychainHandle'](
            self.state, 'link', 'egress', 'relay')
        self.state.keychain_handle = handle
        owner = handle.owner
        handle.registry.register(self.launcher['OwnedResource'](
            'container:relay', owner,
            lambda: self.launcher['ResourcePresence'].MISMATCHED,
            mock.Mock()))
        result = handle.cleanup(37)
        self.assertEqual(result.primary_status, 37)
        self.assertEqual(result.remaining, ('container:relay',))
        self.assertEqual(result.failures[0].code, 'resource-owner-mismatch')

    def test_recovery_record_is_credential_free_and_strictly_parsed(self):
        with tempfile.TemporaryDirectory() as home:
            handle = self.launcher['KeychainHandle'](
                self.state, 'link', 'egress', 'relay')
            self.state.keychain_handle = handle
            self.state.home = Path(home)
            path = self.launcher['persist_relay_recovery'](
                self.state, handle.resources, handle.owner,
                ('container:relay', 'network:link', 'network:egress'))
            self.assertIsNotNone(path)
            data = path.read_bytes()
            self.assertNotIn(b'token', data.lower())
            owner, resources = self.launcher['_parse_relay_recovery'](data)
            self.assertEqual(owner, handle.owner)
            self.assertEqual({item['name'] for item in resources}, {'relay', 'link', 'egress'})
            malformed = json.loads(data)
            malformed['resources'][0]['owner'] = 'foreign-owner'
            with self.assertRaises(self.launcher['LauncherError']):
                self.launcher['_parse_relay_recovery'](json.dumps(malformed).encode())

    def test_cleanup_closes_registration_gate_before_removal(self):
        handle = self.launcher['KeychainHandle'](
            self.state, 'link', 'egress', 'relay')
        handle.cleanup(0)
        with self.assertRaises(self.launcher['LifecycleError']):
            handle.registry.register(self.launcher['OwnedResource'](
                'network:late', handle.owner,
                lambda: self.launcher['ResourcePresence'].ABSENT,
                lambda: None))


if __name__ == '__main__':
    unittest.main()
