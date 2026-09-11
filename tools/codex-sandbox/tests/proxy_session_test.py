"""Real-process publication, shared joins, cancellation, and lifetime ownership."""
import fcntl
import os
from pathlib import Path
import selectors
import signal
import subprocess
import sys
import tempfile
import unittest

FIXTURE = Path(__file__).with_name('session_lock_fixture.py')


class SessionLockTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name)
        self.processes = []

    def tearDown(self):
        for process in self.processes:
            if process.poll() is None:
                process.terminate()
            process.wait(timeout=3)
            process.stdin.close()
            process.stdout.close()
        self.temporary.cleanup()

    def read(self, process, timeout=2):
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            self.assertTrue(selector.select(timeout), 'lock operation stalled')
        return process.stdout.readline().strip()

    def send(self, process, command):
        process.stdin.write(command + '\n')
        process.stdin.flush()

    def start(self):
        process = subprocess.Popen([sys.executable, str(FIXTURE), str(self.directory)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, bufsize=1)
        self.processes.append(process)
        self.assertEqual(self.read(process), 'waiting')
        self.send(process, 'acquire')
        return process

    def test_publication_serializes_then_joiners_validate_without_serializing(self):
        first = self.start()
        self.assertEqual(self.read(first), 'new')
        second = self.start()
        with selectors.DefaultSelector() as selector:
            selector.register(second.stdout, selectors.EVENT_READ)
            self.assertFalse(selector.select(0.1), 'joiner overtook publication')
        self.send(first, 'publish')
        self.assertEqual(self.read(first), 'published')
        self.assertEqual(self.read(second), 'shared')
        third = self.start()
        self.assertEqual(self.read(third), 'shared')
        for process in (first, second):
            self.send(process, 'close')
            self.assertEqual(process.wait(timeout=2), 0)
        with (self.directory / 'session.lock').open('a+b') as reset:
            with self.assertRaises(BlockingIOError):
                fcntl.flock(reset, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.send(third, 'close')
            self.assertEqual(third.wait(timeout=2), 0)
            fcntl.flock(reset, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def test_contended_acquisition_is_cancelled_without_releasing_other_owner(self):
        first = self.start()
        self.assertEqual(self.read(first), 'new')
        second = self.start()
        second.terminate()
        self.assertEqual(second.wait(timeout=2), 143)
        third = self.start()
        self.send(first, 'close')
        self.assertEqual(first.wait(timeout=2), 0)
        self.assertEqual(self.read(third), 'new')

    def test_abrupt_exit_releases_lock_even_when_exec_child_survives(self):
        first = self.start()
        self.assertEqual(self.read(first), 'new')
        self.send(first, 'child')
        child = int(self.read(first))
        try:
            first.kill()
            first.wait(timeout=2)
            os.kill(child, 0)
            second = self.start()
            self.assertEqual(self.read(second), 'new')
        finally:
            os.kill(child, signal.SIGTERM)


if __name__ == '__main__':
    unittest.main()
