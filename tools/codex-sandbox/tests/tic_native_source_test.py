"""Offline exact-revision acquisition through the normal setup Git primitive."""
import io
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest import mock

TOOL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOL))
import tic_artifact


class TicNativeSourceTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.home = self.root / 'home'
        self.home.mkdir()
        self.repository = self.root / 'development'
        self.git('init', '--quiet', str(self.repository))
        (self.repository / 'native.txt').write_text('pinned source\n')
        self.git('-C', str(self.repository), 'add', 'native.txt')
        self.git('-C', str(self.repository), 'commit', '--quiet', '-m', 'pinned fixture')
        self.pin = self.git('-C', str(self.repository), 'rev-parse', 'HEAD').strip()
        (self.repository / 'native.txt').write_text('newer unselected source\n')
        self.git('-C', str(self.repository), 'commit', '--quiet', '-am', 'newer fixture')
        self.next_pin = self.git('-C', str(self.repository), 'rev-parse', 'HEAD').strip()
        self.remote = self.root / 'remote.git'
        self.git('clone', '--quiet', '--bare', str(self.repository), str(self.remote))
        self.pin_patch = mock.patch.object(tic_artifact, 'PIN', self.pin)
        self.pin_patch.start()
        self.addCleanup(self.pin_patch.stop)
        url_patch = mock.patch.object(tic_artifact, 'NATIVE_REPOSITORY_URL', self.remote.as_uri())
        url_patch.start()
        self.addCleanup(url_patch.stop)

    def git(self, *arguments):
        return subprocess.check_output(['git', '-c', 'user.name=Source fixture',
                                        '-c', 'user.email=fixture@example.invalid', *arguments],
                                       text=True, stderr=subprocess.PIPE)

    def source(self, writable=()):
        return tic_artifact.native_source(self.home, writable)

    def test_missing_setting_fetches_exact_pin_not_remote_head_without_writing_configuration(self):
        with mock.patch('sys.stderr', new_callable=io.StringIO) as progress:
            source = self.source()
        self.assertIn('fetching pinned native source', progress.getvalue())
        self.assertEqual(self.pin, self.git('-C', str(source), 'rev-parse', 'HEAD').strip())
        self.assertEqual('pinned source\n', (source / 'native.txt').read_text())
        self.assertEqual(self.home / '.cache/codex-sandbox/tic-native' / self.pin, source)
        self.assertFalse((self.home / '.config').exists())
        # The existing builder's archive primitive sees the same pinned bytes.
        archive = subprocess.check_output(['git', '-C', str(source), 'archive', self.pin])
        with tarfile.open(fileobj=io.BytesIO(archive)) as captured:
            self.assertEqual(b'pinned source\n', captured.extractfile('native.txt').read())

    def test_existing_pinned_source_is_reused_offline(self):
        source = self.source()
        self.remote.rename(self.root / 'unavailable-remote.git')
        with mock.patch('sys.stderr', new_callable=io.StringIO) as progress:
            self.assertEqual(source, self.source())
        self.assertEqual('', progress.getvalue())

    def test_pin_change_acquires_new_revision_without_mutating_previous_source(self):
        original = self.source()
        before = (original / 'native.txt').stat(), (original / 'native.txt').read_bytes()
        with mock.patch.object(tic_artifact, 'PIN', self.next_pin):
            updated = self.source()
        self.assertNotEqual(original, updated)
        self.assertEqual(self.next_pin, updated.name)
        self.assertEqual('newer unselected source\n', (updated / 'native.txt').read_text())
        self.assertEqual(before, ((original / 'native.txt').stat(), (original / 'native.txt').read_bytes()))

    def test_missing_remote_pin_leaves_no_checkout_or_private_stage_and_can_retry(self):
        with mock.patch.object(tic_artifact, 'PIN', '0' * 40):
            with self.assertRaises(subprocess.CalledProcessError):
                self.source()
        cache = self.home / '.cache/codex-sandbox/tic-native'
        self.assertEqual([], list(cache.iterdir()))
        self.assertEqual('pinned source\n', (self.source() / 'native.txt').read_text())

    def test_failed_fetch_leaves_no_checkout_and_preserves_host_settings(self):
        unrelated = self.home / '.config/codex-sandbox/authored'
        unrelated.parent.mkdir(parents=True)
        unrelated.write_text('keep this\n')
        before = unrelated.stat(), unrelated.read_bytes()
        with mock.patch.object(tic_artifact, 'NATIVE_REPOSITORY_URL', (self.root / 'absent.git').as_uri()):
            with self.assertRaises(subprocess.CalledProcessError):
                self.source()
        self.assertEqual([], list((self.home / '.cache/codex-sandbox/tic-native').iterdir()))
        self.assertEqual(before, (unrelated.stat(), unrelated.read_bytes()))
        self.assertFalse(unrelated.with_name('tic-native-source').exists())

    def test_explicit_host_source_remains_authoritative_without_fetch_or_rewrite(self):
        setting = self.home / '.config/codex-sandbox/tic-native-source'
        setting.parent.mkdir(parents=True)
        setting.write_text(str(self.repository) + '\n')
        setting.chmod(0o600)
        before = setting.stat(), setting.read_bytes()
        with mock.patch.object(tic_artifact, 'clone', side_effect=AssertionError('must not fetch')):
            self.assertEqual(self.repository, self.source())
            setting.chmod(0o644)
            with self.assertRaisesRegex(ValueError, '0600'):
                self.source()
        setting.chmod(0o600)
        self.assertEqual(before[1], setting.read_bytes())
        self.assertEqual(before[0].st_ino, setting.stat().st_ino)
        self.assertFalse((self.home / '.cache').exists())

    def test_guest_writable_and_symlinked_source_cache_reject_before_fetch(self):
        with mock.patch.object(tic_artifact, 'clone', side_effect=AssertionError('must not fetch')):
            with self.assertRaisesRegex(ValueError, 'guest-writable'):
                self.source([self.home])
            parent = self.home / '.cache/codex-sandbox'
            parent.mkdir(parents=True)
            (parent / 'tic-native').symlink_to(self.remote)
            with self.assertRaisesRegex(ValueError, 'canonical'):
                self.source()

    def test_partial_checkout_is_not_adopted_or_repaired(self):
        partial = self.home / '.cache/codex-sandbox/tic-native' / self.pin
        partial.mkdir(parents=True)
        authored = partial / 'authored'
        authored.write_text('keep partial state\n')
        with self.assertRaises(subprocess.CalledProcessError):
            self.source()
        self.assertEqual(['authored'], [path.name for path in partial.iterdir()])
        self.assertEqual('keep partial state\n', authored.read_text())


if __name__ == '__main__':
    unittest.main()
