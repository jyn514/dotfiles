"""Linger failures must expose guest service health without masking the failure."""
import contextlib
import io
from pathlib import Path
import runpy
import subprocess
import unittest
from unittest.mock import patch


GUEST = runpy.run_path(str(Path(__file__).resolve().parents[1] / 'guest-install.py'))


class LingerDiagnosticTest(unittest.TestCase):
    def test_success_does_not_run_diagnostics(self):
        with patch.object(subprocess, 'run', return_value=subprocess.CompletedProcess([], 0)) as run:
            GUEST['enable_linger']()
        self.assertEqual(1, run.call_count)
        self.assertEqual(('loginctl', 'enable-linger', 'agentbuilder'), run.call_args.args[0])

    def test_failure_reports_service_cpu_and_journal_before_stopping_setup(self):
        error = subprocess.CalledProcessError(1, ['loginctl'], stderr='Connection timed out')
        with patch.object(subprocess, 'run', side_effect=[
                error,
                subprocess.CompletedProcess([], 0, 'logind active; dbus active\n'),
                subprocess.CompletedProcess([], 0, '869 99.9 systemd-logind\n'),
                subprocess.CompletedProcess([], 0, 'New session 1\n')]) as run, \
                contextlib.redirect_stderr(io.StringIO()) as output:
            with self.assertRaisesRegex(SystemExit, 'rerun the same host setup command'):
                GUEST['enable_linger']()
        self.assertIn('Connection timed out', output.getvalue())
        for evidence in ('logind active', '99.9', 'New session 1'):
            self.assertIn(evidence, output.getvalue())
        self.assertEqual(['systemctl', 'ps', 'journalctl'],
                         [call.args[0][0] for call in run.call_args_list[1:]])
        for call in run.call_args_list[1:]:
            self.assertLessEqual(call.kwargs['timeout'], 5)

    def test_failed_diagnostics_do_not_hide_original_linger_timeout(self):
        failures = [subprocess.TimeoutExpired(['loginctl'], 240),
                    subprocess.TimeoutExpired(['systemctl'], 5),
                    OSError('ps unavailable'), subprocess.TimeoutExpired(['journalctl'], 5)]
        with patch.object(subprocess, 'run', side_effect=failures), \
                contextlib.redirect_stderr(io.StringIO()) as output:
            with self.assertRaisesRegex(SystemExit, 'could not enable linger'):
                GUEST['enable_linger']()
        self.assertIn('240', output.getvalue())
        self.assertIn('ps unavailable', output.getvalue())
        self.assertEqual(3, output.getvalue().count('diagnostic unavailable'))


if __name__ == '__main__':
    unittest.main()
