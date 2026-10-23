"""Report the current restart without replaying previous daemon failures."""

from contextlib import nullcontext, redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
import runpy
import shutil
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from lima.docker_host import DockerHost
from lima import docker_host


class DockerUserSetupTest(unittest.TestCase):
    def test_setup_and_upgrade_end_with_a_summary_instead_of_the_record(self):
        for operation in ('setup', 'upgrade'):
            with self.subTest(operation=operation):
                host = Mock()
                host.locked.return_value = nullcontext()
                getattr(host, operation).return_value = {'instance': 'fixture', 'files': {'internal': 'digest'}}
                output = io.StringIO()
                with patch.object(docker_host, 'DockerHost', return_value=host), \
                        patch.object(sys, 'argv', ['docker_host.py', operation]), redirect_stdout(output):
                    docker_host.main()
                self.assertEqual(output.getvalue(), f'Docker VM fixture: {operation} complete.\n')

    def test_failed_setup_or_upgrade_does_not_print_a_completion_summary(self):
        for operation in ('setup', 'upgrade'):
            with self.subTest(operation=operation):
                host = Mock()
                host.locked.return_value = nullcontext()
                getattr(host, operation).side_effect = ValueError('provisioning failed')
                output = io.StringIO()
                with patch.object(docker_host, 'DockerHost', return_value=host), \
                        patch.object(sys, 'argv', ['docker_host.py', operation]), redirect_stdout(output):
                    with self.assertRaisesRegex(ValueError, 'provisioning failed'):
                        docker_host.main()
                self.assertEqual(output.getvalue(), '')

    def test_upgrade_requires_an_explicit_running_container_override(self):
        host = Mock()
        host.locked.return_value = nullcontext()
        host.upgrade.return_value = {'instance': 'fixture', 'files': {}}
        for arguments, expected in ((['upgrade'], False),
                                    (['upgrade', '--allow-running-containers'], True)):
            with self.subTest(arguments=arguments), \
                    patch.object(docker_host, 'DockerHost', return_value=host), \
                    patch.object(sys, 'argv', ['docker_host.py', *arguments]), \
                    redirect_stdout(io.StringIO()):
                docker_host.main()
            host.upgrade.assert_called_once_with(expected)
            host.upgrade.reset_mock()

    def run_setup(self, failure='', state=None):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            home, staged, binary = root / 'home', root / 'source', root / 'bin'
            staged.mkdir()
            binary.mkdir()
            host = object.__new__(DockerHost)
            for name, source in host.source_files().items():
                shutil.copyfile(source, staged / name)
            fixture = Path(__file__).with_name('fixtures') / 'docker_setup_command.py'
            for name in ('dockerd-rootless-setuptool.sh', 'systemctl'):
                (binary / name).symlink_to(fixture)
            receipt = root / 'commands.jsonl'
            environment = {'PATH': str(binary) + os.pathsep + os.environ['PATH'],
                           'SETUP_COMMANDS': str(receipt), 'SETUP_FAIL': failure,
                           'SETUP_STATE': json.dumps(state or {})}
            real_path = Path

            def guest_path(value):
                return staged if value == '/usr/local/share/codex-sandbox' else real_path(value)

            stdout, stderr = io.StringIO(), io.StringIO()
            with patch.dict(os.environ, environment), patch('pathlib.Path', side_effect=guest_path) as paths, \
                    redirect_stdout(stdout), redirect_stderr(stderr):
                paths.home.return_value = home
                result = runpy.run_path(str(ROOT / 'lima/docker/configure-user.py'))['main']()
            commands = [json.loads(line) for line in receipt.read_text().splitlines()]
            return result, stdout.getvalue(), stderr.getvalue(), commands

    def test_success_reports_loaded_state_without_previous_daemon_logs(self):
        code, stdout, output, commands = self.run_setup()
        self.assertEqual(code, 0, output)
        self.assertEqual(stdout, '')
        self.assertIn('ActiveState=active', output)
        self.assertIn('NeedDaemonReload=no', output)
        self.assertIn('MainPID=4242', output)
        self.assertIn('ExecMainStartTimestamp=Tue 2026-10-13 08:42:47 EDT', output)
        self.assertIn('restart complete', output)
        self.assertNotIn('old daemon', output)
        self.assertNotIn('old unit', output)
        self.assertEqual([command[-1] for command in commands[:3]], ['install', 'daemon-reload', 'docker'])
        self.assertEqual(commands[-1][2:4], ['show', 'docker.service'])

    def test_failed_install_or_reload_retains_diagnostics_and_stops_before_restart(self):
        for failure in ('install', 'daemon-reload'):
            with self.subTest(failure=failure):
                code, _, output, commands = self.run_setup(failure)
                self.assertEqual(code, 7)
                self.assertIn(f'current {failure} failure', output)
                self.assertNotIn('restart complete', output)
                self.assertFalse(any('restart' in command or 'show' in command for command in commands))

    def test_failed_restart_reports_current_state_and_diagnostics(self):
        code, _, output, commands = self.run_setup('restart', {
            'ActiveState': 'failed', 'SubState': 'failed', 'Result': 'exit-code', 'ExecMainStatus': '1',
        })
        self.assertEqual(code, 7)
        self.assertIn('restart Docker failed (exit 7)', output)
        self.assertIn('current restart failure', output)
        self.assertIn('Result=exit-code', output)
        self.assertIn('ExecMainStatus=1', output)
        self.assertNotIn('old daemon', output)
        self.assertNotIn('restart complete', output)
        self.assertEqual(commands[-1][2], 'show')

    def test_failed_state_query_cannot_report_restart_complete(self):
        code, _, output, _ = self.run_setup('show')
        self.assertEqual(code, 7)
        self.assertIn('current show failure', output)
        self.assertNotIn('restart complete', output)

    def test_successful_command_with_inactive_or_unloaded_units_is_not_success(self):
        for state in ({'ActiveState': 'inactive', 'SubState': 'dead'}, {'NeedDaemonReload': 'yes'}):
            with self.subTest(state=state):
                code, _, output, _ = self.run_setup(state=state)
                self.assertEqual(code, 1)
                self.assertIn('did not reach active/running with reloaded units', output)
                self.assertNotIn('restart complete', output)


if __name__ == '__main__':
    unittest.main()
