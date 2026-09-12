"""Protect against overlapping reclaim and misreported partial results."""

import errno
import importlib.util
import multiprocessing
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lima.docker_host import DockerHost

SOURCE = Path(__file__).resolve().parents[1] / 'lima/docker/reclaim.py'
spec = importlib.util.spec_from_file_location('reclaim', SOURCE)
reclaim = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reclaim)


def hold_lock(runtime, ready, release):
    with reclaim.exclusive(runtime):
        ready.set()
        release.wait(10)


class ReclaimTest(unittest.TestCase):
    def test_old_vm_reports_missing_reclamation_without_guest_commands(self):
        host = object.__new__(DockerHost)
        host.guest = Mock()
        self.assertEqual(host.reclaim_status({'files': {}}), {'state': 'not-installed'})
        host.guest.assert_not_called()

    def test_disable_still_works_with_unready_docker_and_detects_busy_worker(self):
        host = object.__new__(DockerHost)
        record = {'files': {'docker-reclaim.py': 'digest'}}
        host.record = Mock(return_value=record)
        host.machine = Mock()
        host.doctor = Mock(side_effect=AssertionError('disable must not require healthy Docker'))
        calls = []

        def guest(record, *argv, **kwargs):
            calls.append(argv)
            if '--check-idle' in argv:
                raise subprocess.CalledProcessError(75, argv)
            return subprocess.CompletedProcess(argv, 0, 'digest  helper\n')

        host.guest = guest
        with self.assertRaises(subprocess.CalledProcessError):
            host.reclaim('disable')
        self.assertEqual(calls[0][2:], ('disable', '--now', 'sandbox-reclaim.timer'))
        self.assertEqual(calls[1][2:], ('stop', 'sandbox-reclaim.service'))
        self.assertIn('--check-idle', calls[-1])

    def test_status_keeps_disabled_timer_separate_from_last_job_failure(self):
        host = object.__new__(DockerHost)
        host.guest = Mock(return_value=subprocess.CompletedProcess([], 0,
            'Id=sandbox-reclaim.timer\nUnitFileState=disabled\nActiveState=inactive\n\n'
            'Id=sandbox-reclaim.service\nResult=timeout\nExecMainStatus=15\n'))
        result = host.reclaim_status({'files': {'docker-reclaim.py': 'digest'}})
        self.assertEqual(result['sandbox-reclaim.timer']['UnitFileState'], 'disabled')
        self.assertEqual(result['sandbox-reclaim.service']['Result'], 'timeout')

    def test_surviving_worker_blocks_new_write_until_it_exits(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / 'memory.reclaim'
            target.write_text('untouched')
            context = multiprocessing.get_context('spawn')
            ready, release = context.Event(), context.Event()
            worker = context.Process(target=hold_lock, args=(root, ready, release))
            worker.start()
            try:
                self.assertTrue(ready.wait(5))
                with self.assertRaises(BlockingIOError):
                    reclaim.reclaim(root, root, 1024)
                self.assertEqual(target.read_text(), 'untouched')
            finally:
                release.set()
                worker.join(5)
                if worker.is_alive():
                    worker.kill()
                    worker.join()
            self.assertEqual(worker.exitcode, 0)
            inode = (root / 'sandbox-reclaim.lock').stat().st_ino
            self.assertEqual(reclaim.reclaim(root, root, 1024)['result'], 'completed')
            self.assertEqual(target.read_text(), '1024')
            self.assertEqual((root / 'sandbox-reclaim.lock').stat().st_ino, inode)

    def test_partial_reclaim_is_distinct_from_io_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(Path, 'open', side_effect=OSError(errno.EAGAIN, 'partial')) as opening:
                self.assertEqual(reclaim.reclaim(root, root, 1024),
                                 {'result': 'partial', 'requested_bytes': 1024})
                self.assertEqual(opening.call_count, 1)
            with patch.object(Path, 'open', side_effect=OSError(errno.EIO, 'failed')):
                with self.assertRaises(OSError) as error:
                    reclaim.reclaim(root, root, 1024)
                self.assertEqual(error.exception.errno, errno.EIO)

    def test_invalid_batch_never_opens_the_target(self):
        with patch.object(Path, 'open') as opening:
            for amount in (0, -1, 1024 ** 3 + 1):
                with self.assertRaises(ValueError):
                    reclaim.reclaim(Path('/absent'), Path('/absent'), amount)
            opening.assert_not_called()


if __name__ == '__main__':
    unittest.main()
