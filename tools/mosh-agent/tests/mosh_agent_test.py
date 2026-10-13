"""Exercise the wrapper without network access or real agent state."""

import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[3]
WRAPPER = ROOT / 'bin/mosh-agent'
FIXTURE = Path(__file__).with_name('command_fixture.py')
NATIVE_MOSH = shutil.which('mosh')


class MoshAgentTest(unittest.TestCase):
    def setUp(self):
        self.storage = tempfile.TemporaryDirectory()
        self.addCleanup(self.storage.cleanup)
        self.directory = Path(self.storage.name)
        for name in ('autossh', 'mosh', 'ssh', 'ssh-add', 'native-ssh', 'mosh-server', 'native-client'):
            target = self.directory / name
            shutil.copyfile(FIXTURE, target)
            target.chmod(0o755)
        self.environment = dict(os.environ, FIXTURE_DIR=str(self.directory),
            PATH=str(self.directory) + os.pathsep + os.environ['PATH'],
            SSH_AUTH_SOCK=str(self.directory / 'local agent.sock'))

    def events(self):
        path = self.directory / 'events'
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def run_wrapper(self, *arguments):
        return subprocess.run([str(WRAPPER), *arguments], env=self.environment,
            input='terminal input\n', text=True, capture_output=True, timeout=10)

    def assert_stopped(self):
        events = self.events()
        for name in ('autossh', 'ssh'):
            self.assertTrue(any(event[:2] == [name, 'stopped'] for event in events), events)
        for event in events:
            if event[1] == 'started':
                with self.assertRaises(ProcessLookupError):
                    os.kill(event[2], 0)

    def test_mosh_keeps_stdin_and_status_and_stops_tunnel(self):
        self.environment['MOSH_STATUS'] = '7'
        result = self.run_wrapper('devbox')
        self.assertEqual(result.returncode, 7, result.stderr)
        self.assertEqual(result.stdout, 'terminal input\n')
        arguments = next(event[3] for event in self.events() if event[:2] == ['autossh', 'started'])
        remote_socket, local_socket = arguments[arguments.index('-R') + 1].split(':', 1)
        self.assertEqual(Path(remote_socket).parent, self.directory / 'remote home/.ssh')
        self.assertEqual(local_socket, self.environment['SSH_AUTH_SOCK'])
        self.assertEqual(arguments[-1], 'devbox')
        self.assert_stopped()

    def test_normal_exit_stops_tunnel(self):
        result = self.run_wrapper('devbox')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_stopped()

    def test_termination_stops_both_children(self):
        self.environment['MOSH_WAIT'] = '1'
        process = subprocess.Popen([str(WRAPPER), 'devbox'],
            env=self.environment, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True)
        self.addCleanup(lambda: process.kill() if process.poll() is None else None)
        process.stdin.write('terminal input\n')
        process.stdin.flush()
        deadline = time.monotonic() + 5
        while len([event for event in self.events() if event[1] == 'started']) < 3:
            self.assertLess(time.monotonic(), deadline, self.events())
            time.sleep(0.01)
        process.send_signal(signal.SIGTERM)
        _, stderr = process.communicate(timeout=5)
        self.assertEqual(process.returncode, 143, stderr)
        self.assertTrue(any(event[:2] == ['mosh', 'stopped'] for event in self.events()))
        self.assert_stopped()

    def test_unavailable_or_empty_agent_starts_no_children(self):
        for status in ('1', '2'):
            with self.subTest(status=status):
                self.environment['AGENT_STATUS'] = status
                result = self.run_wrapper('devbox')
                self.assertEqual(result.returncode, 1)
                self.assertIn('available agent with keys', result.stderr)
                self.assertEqual(self.events(), [])

    def test_invalid_arguments_start_no_children(self):
        for arguments in ((), ('-option',)):
            with self.subTest(arguments=arguments):
                result = self.run_wrapper(*arguments)
                self.assertEqual(result.returncode, 2)
                self.assertEqual(self.events(), [])

    def test_help_needs_no_agent(self):
        self.environment.pop('SSH_AUTH_SOCK')
        result = self.run_wrapper('--help')
        self.assertEqual(result.returncode, 0)
        self.assertIn('usage:', result.stdout)
        self.assertEqual(self.events(), [])

    def test_missing_agent_environment_starts_no_children(self):
        self.environment.pop('SSH_AUTH_SOCK')
        result = self.run_wrapper('devbox')
        self.assertEqual(result.returncode, 1)
        self.assertIn('SSH_AUTH_SOCK', result.stderr)
        self.assertEqual(self.events(), [])

    def test_failed_remote_discovery_starts_no_children(self):
        self.environment['SSH_DISCOVERY_STATUS'] = '255'
        result = self.run_wrapper('devbox')
        self.assertEqual(result.returncode, 255)
        self.assertEqual(self.events(), [])

    def test_forwards_original_arguments_without_splitting_or_expansion(self):
        original = ['devbox', 'tmux', 'new-session', 'name with spaces', '', '$HOME', '*', "it's quoted"]
        result = self.run_wrapper(*original)
        self.assertEqual(result.returncode, 0, result.stderr)
        arguments = next(event[3] for event in self.events() if event[:2] == ['mosh', 'started'])
        self.assertEqual(arguments[1:], original)
        self.assert_stopped()

    @unittest.skipUnless(NATIVE_MOSH, 'installed mosh is required for the bootstrap consumer check')
    def test_real_mosh_sets_only_its_remote_session_agent(self):
        self.environment['NATIVE_MOSH'] = NATIVE_MOSH
        command = ['tmux', 'new-session', 'name with spaces', '', '$HOME', '*', "it's quoted"]
        result = self.run_wrapper('localhost', *command)
        self.assertEqual(result.returncode, 0, result.stderr)
        arguments = next(event[3] for event in self.events() if event[:2] == ['autossh', 'started'])
        remote_socket = arguments[arguments.index('-R') + 1].split(':', 1)[0]
        self.assertEqual((self.directory / 'remote-agent').read_text(),
            remote_socket)
        self.assertEqual(self.environment['SSH_AUTH_SOCK'], str(self.directory / 'local agent.sock'))
        self.assertEqual(json.loads((self.directory / 'remote-command').read_text()), command)


if __name__ == '__main__':
    unittest.main()
