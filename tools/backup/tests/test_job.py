import json
import os
from pathlib import Path
import plistlib
import pwd
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

TOOL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOL))
import job
import install


class CaptureTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / 'agent'
        (self.source / 'notes').mkdir(parents=True)
        (self.source / 'notes/memory.md').write_text('remember me\n')
        (self.source / 'records.log').write_text('before shutdown\n')
        self.external = self.root / 'external'
        self.external.write_text('not agent state\n')
        (self.source / 'external-link').symlink_to(self.external)
        self.state = self.root / 'state'
        self.state.mkdir()
        self.record = self.root / 'docker.json'
        self.record.write_text(json.dumps({'engine': 'owned-engine', 'running': True,
                                          'source': str(self.source)}))
        self.config = {'owner': pwd.getpwuid(os.getuid()).pw_name,
                       'mica': {'docker': str(TOOL / 'tests/docker_fixture.py'),
                                'socket': '/disposable/socket', 'engine': 'owned-engine',
                                'container': 'mica-mica-1', 'source': str(self.source)}}
        self.job = job.Job(self.config, self.state)

        def run_fixture(user, arguments, **kwargs):
            return subprocess.run([sys.executable, *arguments], check=True, text=True,
                                  capture_output=kwargs.get('capture', False),
                                  env=os.environ | {'DOCKER_FIXTURE': str(self.record)})

        self.addCleanup(patch.stopall)
        patch.object(job, 'run_as', side_effect=run_fixture).start()
        # Capture ownership changes use this disposable test account.
        patch.object(job.pwd, 'getpwnam', return_value=pwd.getpwuid(os.getuid())).start()

    def read_state(self):
        return json.loads(self.record.read_text())

    def test_capture_contains_shutdown_flush_then_restarts_before_upload(self):
        captured = self.job.capture()
        self.assertEqual('flushed before capture\n', (captured / 'records.log').read_text())
        self.assertEqual('live after restart\n', (self.source / 'records.log').read_text())
        self.assertEqual('remember me\n', (captured / 'notes/memory.md').read_text())
        self.assertTrue((captured / 'external-link').is_symlink())
        self.assertTrue(self.read_state()['running'])
        self.assertFalse(self.job.marker.exists())

    def test_copy_failure_restarts_and_preserves_previous_capture(self):
        old = self.state / 'mica-state'
        old.mkdir()
        (old / 'records.log').write_text('last good capture\n')
        with patch.object(job.shutil, 'copytree', side_effect=OSError('copy failed')):
            with self.assertRaisesRegex(OSError, 'copy failed'):
                self.job.capture()
        self.assertTrue(self.read_state()['running'])
        self.assertFalse(self.job.marker.exists())
        self.assertEqual('last good capture\n', (old / 'records.log').read_text())

    def test_marker_recovers_exact_container_after_interruption(self):
        state = self.read_state()
        state['running'] = False
        self.record.write_text(json.dumps(state))
        self.job.marker.write_text(json.dumps({'container': 'owned-container'}))
        self.job.recover()
        self.assertTrue(self.read_state()['running'])
        self.assertFalse(self.job.marker.exists())

    def test_previously_stopped_container_stays_stopped(self):
        state = self.read_state()
        state['running'] = False
        self.record.write_text(json.dumps(state))
        self.job.capture()
        self.assertFalse(self.read_state()['running'])
        self.assertNotIn('start', self.read_state()['calls'])

    def test_wrong_engine_or_mount_never_stops_any_container(self):
        for key, value in [('engine', 'other-engine'), ('source', '/other/state')]:
            with self.subTest(key=key):
                state = self.read_state()
                original = state[key]
                state[key] = value
                self.record.write_text(json.dumps(state))
                with self.assertRaises(RuntimeError):
                    self.job.capture()
                self.assertNotIn('stop', self.read_state()['calls'])
                state = self.read_state()
                state[key] = original
                self.record.write_text(json.dumps(state))

    def test_forced_shutdown_is_rejected_and_mica_restarted(self):
        state = self.read_state()
        state['exit'] = 137
        self.record.write_text(json.dumps(state))
        with self.assertRaisesRegex(RuntimeError, 'cleanly'):
            self.job.capture()
        self.assertTrue(self.read_state()['running'])
        self.assertFalse((self.state / 'mica-state').exists())

    def test_upload_failure_happens_after_restart_and_does_not_skip_documents(self):
        calls = []

        def fail_mica(tag, root=None):
            calls.append(tag)
            self.assertTrue(self.read_state()['running'])
            if tag == 'mica-state':
                raise RuntimeError('network unavailable')

        with patch.object(self.job, 'upload', side_effect=fail_mica):
            with self.assertRaisesRegex(RuntimeError, 'network unavailable'):
                self.job.daily()
        self.assertEqual(['mica-state', 'documents-backup'], calls)
        self.assertTrue((self.state / 'mica-state/records.log').exists())

    def test_failed_recovery_still_attempts_documents_and_retains_marker(self):
        self.job.marker.write_text(json.dumps({'container': 'owned-container'}))
        with patch.object(self.job, 'recover', side_effect=RuntimeError('Docker unavailable')):
            with patch.object(self.job, 'upload') as upload:
                with self.assertRaisesRegex(RuntimeError, 'Docker unavailable'):
                    self.job.daily()
        upload.assert_called_once_with('documents-backup')
        self.assertTrue(self.job.marker.exists())


class NativeSchedulerTests(unittest.TestCase):
    def test_documents_only_config_records_host_without_docker(self):
        owner = pwd.getpwuid(os.getuid()).pw_name
        config = install.configuration(owner, '/usr/bin/restic', None, False, None)
        self.assertEqual(install.socket.gethostname(), config['host'])
        self.assertNotIn('mica', config)
        self.assertTrue(Path(config['credentials']).is_absolute())

    def test_install_location_updates_both_native_schedulers(self):
        with patch.object(install, 'INSTALL', Path('/different/installed/location')):
            linux = install.artifacts('linux', {})['dotfiles-backup.service']
            macos = plistlib.loads(install.artifacts('macos', {})[
                install.LABEL + '.plist'].encode())
        self.assertIn('/different/installed/location/job.py', linux)
        self.assertIn('/different/installed/location/job.py', macos['ProgramArguments'])

    def test_linux_units_are_accepted_by_systemd(self):
        import shutil
        if not shutil.which('systemd-analyze'):
            self.skipTest('systemd-analyze unavailable')
        with tempfile.TemporaryDirectory() as directory:
            rendered = install.artifacts('linux', {'owner': 'fixture'})
            for name, contents in rendered.items():
                (Path(directory) / name).write_text(contents)
            # Substitute the real checkout solely for native executable validation.
            unit = Path(directory) / 'dotfiles-backup.service'
            unit.write_text(unit.read_text().replace(str(install.INSTALL), str(TOOL)))
            result = subprocess.run(['systemd-analyze', 'verify', str(unit),
                                     str(Path(directory) / 'dotfiles-backup.timer')],
                                    text=True, capture_output=True)
            self.assertEqual(0, result.returncode, result.stderr)

    def test_macos_job_is_system_daemon_with_daily_calendar(self):
        files = install.artifacts('macos', {})
        daemon = plistlib.loads(files[install.LABEL + '.plist'].encode())
        self.assertEqual({'Hour': 12, 'Minute': 0}, daemon['StartCalendarInterval'])
        self.assertTrue(daemon['RunAtLoad'])
        self.assertNotIn('UserName', daemon)  # root orchestrates; job.py drops upload privileges
        self.assertEqual('daily', daemon['ProgramArguments'][-1])
        self.assertIn('-I', daemon['ProgramArguments'])

    def test_atomic_publish_can_be_repeated_without_duplicate_jobs(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'service'
            install.publish(path, 'first\n')
            install.publish(path, 'second\n')
            self.assertEqual('second\n', path.read_text())
            self.assertEqual([path], list(Path(directory).iterdir()))


if __name__ == '__main__':
    unittest.main()
