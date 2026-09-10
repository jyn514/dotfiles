import contextlib
import os
from pathlib import Path
import runpy
import sys
import tempfile
import threading
import unittest


ROOT = Path(__file__).resolve().parent


class TerminalCleanupTest(unittest.TestCase):
    def test_failed_barrier_drains_output_until_launcher_cleanup_finishes(self):
        terminal_run = runpy.run_path(str(ROOT / 'lima_launcher_integration.py'))['terminal_run']
        barrier = threading.Barrier(2)
        barrier.abort()
        with tempfile.TemporaryDirectory() as directory, open(os.devnull, 'w') as output:
            marker = Path(directory) / 'cleaned'
            with contextlib.redirect_stdout(output), self.assertRaises(threading.BrokenBarrierError):
                terminal_run([sys.executable, str(ROOT / 'pty_cleanup_fixture.py'), str(marker)],
                             os.environ.copy(), directory, interactive=True, ready_barrier=barrier)
            self.assertTrue(marker.exists(), 'launcher was killed before completing cleanup')


if __name__ == '__main__':
    unittest.main()
