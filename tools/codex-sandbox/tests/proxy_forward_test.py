"""Recovery must remove only the recorded session's socket capability."""

import os
from pathlib import Path
import socket
import subprocess
import sys
import unittest
import uuid
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lima import proxy_forward, proxy_socket
from sandbox_runtime import RuntimeError


class ForwardRecoveryTest(unittest.TestCase):
    def setUp(self):
        self.owner = uuid.uuid4().hex
        self.record = {'owner': self.owner, 'target': '/owned/volume/socket'}
        self.path = proxy_socket.directory(self.owner)
        self.addCleanup(self.cleanup)

    def cleanup(self):
        if self.path.is_symlink():
            self.path.unlink()
        elif self.path.exists():
            for child in self.path.iterdir():
                child.unlink()
            self.path.rmdir()

    def test_failed_registration_can_be_cleaned_up_twice(self):
        with patch.object(proxy_forward, 'guest_alias') as guest, patch.object(
                proxy_forward, 'control', return_value=subprocess.CompletedProcess([], 1, '', 'failed')):
            with self.assertRaises(RuntimeError):
                proxy_forward.start(Mock(), self.record)
            proxy_forward.stop(Mock(), self.record)
            proxy_forward.stop(Mock(), self.record)
        self.assertFalse(self.path.exists())
        self.assertEqual([call.args[1] for call in guest.call_args_list], ['create', 'remove', 'remove'])

    def test_replacement_master_allows_removal_of_stale_listener(self):
        self.path.mkdir(mode=0o700)
        with socket.socket(socket.AF_UNIX) as listener:
            listener.bind(str(proxy_forward.local_path(self.owner)))
        with patch.object(proxy_forward, 'guest_alias'), patch.object(proxy_forward, 'control',
                return_value=subprocess.CompletedProcess([], 1, '', 'not forwarded')):
            proxy_forward.stop(Mock(), self.record)
        self.assertFalse(self.path.exists())

    def test_failed_cancellation_retains_live_listener_and_guest_alias(self):
        self.path.mkdir(mode=0o700)
        with socket.socket(socket.AF_UNIX) as listener:
            listener.bind(str(proxy_forward.local_path(self.owner)))
            listener.listen()
            with patch.object(proxy_forward, 'guest_alias') as guest, patch.object(proxy_forward, 'control',
                    return_value=subprocess.CompletedProcess([], 1, '', 'failed')):
                with self.assertRaises(RuntimeError):
                    proxy_forward.stop(Mock(), self.record)
                guest.assert_not_called()
        self.assertTrue(proxy_forward.local_path(self.owner).exists())

    def test_replaced_directory_does_not_cancel_any_forward(self):
        self.path.symlink_to('/tmp', target_is_directory=True)
        with patch.object(proxy_forward, 'control') as control:
            with self.assertRaises(ValueError):
                proxy_forward.stop(Mock(), self.record)
            control.assert_not_called()

    def test_guest_alias_recovery_after_directory_creation(self):
        self.path.mkdir(mode=0o700)
        proxy_socket.alias('remove', self.owner, self.record['target'])
        proxy_socket.alias('remove', self.owner, self.record['target'])
        self.assertFalse(self.path.exists())

    def test_guest_alias_refuses_changed_target(self):
        proxy_socket.alias('create', self.owner, self.record['target'])
        with self.assertRaises(ValueError):
            proxy_socket.alias('remove', self.owner, '/other/socket')
        self.assertEqual(os.readlink(self.path / 's'), self.record['target'])

    def test_guest_helper_does_not_require_a_shared_checkout(self):
        runtime = Mock()
        runtime.host.guest_argv.return_value = ['ssh', 'guest', 'python3 -']
        with patch.object(proxy_forward.subprocess, 'run') as run:
            proxy_forward.guest_alias(runtime, 'create', self.record)
        self.assertEqual(runtime.host.guest_argv.call_args.args[1:3], ('python3', '-'))
        self.assertIn(b"def alias(", run.call_args.kwargs['input'])


if __name__ == '__main__':
    unittest.main()
