"""Host Buildx upgrades cannot replace the launcher-owned executable."""

from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lima.docker_client import pin_buildx, verify_buildx
from docker_runtime import Docker


class DockerClientTest(unittest.TestCase):
    def test_version_check_uses_the_copy_even_if_homebrew_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'homebrew-buildx'
            source.write_bytes(b'original')

            def version(command, **kwargs):
                self.assertNotEqual(Path(command[0]), source)
                self.assertEqual(Path(command[0]).read_bytes(), b'original')
                source.write_bytes(b'upgraded during pin')
                return Mock(stdout='github.com/docker/buildx v0.37.0 Homebrew')

            with patch('lima.docker_client.subprocess.run', side_effect=version):
                pinned = pin_buildx(root / 'state', source)
            self.assertEqual(pinned.read_bytes(), b'original')

    def test_source_upgrade_or_removal_does_not_change_the_pinned_binary(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'homebrew-buildx'
            source.write_bytes(b'original executable')
            with patch('lima.docker_client.subprocess.run', return_value=Mock(stdout='github.com/docker/buildx v0.37.0 Homebrew')):
                pinned = pin_buildx(root / 'state', source)
            source.write_bytes(b'replacement executable')
            self.assertEqual(verify_buildx(root / 'state').read_bytes(), b'original executable')
            source.unlink()
            self.assertEqual(verify_buildx(root / 'state'), pinned)
            pinned.chmod(0o700)
            pinned.write_bytes(b'modified pinned executable')
            with self.assertRaisesRegex(ValueError, 'pin-buildx'):
                verify_buildx(root / 'state')

    def test_wrong_version_is_not_published(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'buildx'
            source.touch()
            with patch('lima.docker_client.subprocess.run', return_value=Mock(stdout='github.com/docker/buildx v0.38.0 Homebrew')):
                with self.assertRaisesRegex(ValueError, 'v0.37.0'):
                    pin_buildx(root / 'state', source)
            self.assertFalse((root / 'state/client/buildx.json').exists())

    def test_buildx_bypasses_plugin_search_and_uses_only_the_recorded_engine(self):
        runtime = object.__new__(Docker)
        runtime.host = Mock(state=Path('/owned'))
        runtime.record = {'client': '/homebrew/docker', 'socket': '/owned/docker.sock'}
        with patch('docker_runtime.verify_buildx', return_value=Path('/owned/pinned/docker-buildx')):
            command = runtime.client_argv(['buildx', 'bake', '--print'])
        self.assertNotIn('/homebrew/docker', command)
        self.assertEqual(command[-3:], ['/owned/pinned/docker-buildx', 'bake', '--print'])
        self.assertIn('DOCKER_HOST=unix:///owned/docker.sock', command)
        self.assertIn('DOCKER_CONFIG=/owned/client', command)
        self.assertIn('BUILDX_CONFIG=/owned/client/buildx-state', command)
        with patch('docker_runtime.verify_buildx', side_effect=ValueError('changed')):
            with self.assertRaisesRegex(ValueError, 'changed'):
                runtime.client_argv(['buildx', 'version'])


if __name__ == '__main__':
    unittest.main()
