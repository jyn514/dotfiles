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
from lima.docker_host import DockerHost, PRESSURE_BATCH_BYTES
from lima import docker_host

SOURCE = Path(__file__).resolve().parents[1] / 'lima/docker/reclaim.py'
spec = importlib.util.spec_from_file_location('reclaim', SOURCE)
reclaim = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reclaim)


def hold_lock(runtime, ready, release):
    with reclaim.exclusive(runtime):
        ready.set()
        release.wait(10)


class ReclaimTest(unittest.TestCase):
    def test_pressure_reclaim_stays_idle_below_high_threshold(self):
        host = object.__new__(DockerHost)
        host.virtiofs_pressure = Mock(return_value={'pid': 7, 'count': 79, 'limit': 100})
        host.reclaim_batch = Mock()
        self.assertEqual(host.reclaim_pressure({}), {
            'pid': 7, 'count': 79, 'limit': 100, 'state': 'below-threshold',
            'batches': 0, 'high': 80, 'low': 60})
        host.reclaim_batch.assert_not_called()

    def test_pressure_reclaim_stops_at_low_threshold(self):
        host = object.__new__(DockerHost)
        host.virtiofs_pressure = Mock(side_effect=[
            {'pid': 7, 'count': 90, 'limit': 100},
            {'pid': 7, 'count': 70, 'limit': 100},
            {'pid': 7, 'count': 55, 'limit': 100},
        ])
        host.reclaim_batch = Mock()
        result = host.reclaim_pressure({})
        self.assertEqual((result['state'], result['count'], result['batches']),
                         ('recovered', 55, 2))
        self.assertEqual(host.reclaim_batch.call_count, 2)

    def test_pressure_reclaim_stops_when_a_batch_makes_no_progress(self):
        host = object.__new__(DockerHost)
        host.virtiofs_pressure = Mock(side_effect=[
            {'pid': 7, 'count': 90, 'limit': 100},
            {'pid': 7, 'count': 90, 'limit': 100},
        ])
        host.reclaim_batch = Mock()
        result = host.reclaim_pressure({})
        self.assertEqual((result['state'], result['batches']), ('no-progress', 1))

    def test_pressure_reclaim_stops_after_three_improving_batches(self):
        host = object.__new__(DockerHost)
        host.virtiofs_pressure = Mock(side_effect=[
            {'pid': 7, 'count': count, 'limit': 100}
            for count in (99, 90, 80, 70)
        ])
        host.reclaim_batch = Mock()
        result = host.reclaim_pressure({})
        self.assertEqual((result['state'], result['count'], result['batches']),
                         ('batch-limit', 70, 3))
        self.assertEqual(host.reclaim_batch.call_count, 3)

    def test_pressure_batch_uses_a_bounded_transient_guest_unit(self):
        host = object.__new__(DockerHost)
        host.guest = Mock()
        host.reclaim_batch({})
        arguments = host.guest.call_args.args[1:]
        self.assertEqual(arguments[:5], ('systemd-run', '--user', '--wait', '--collect', '--quiet'))
        self.assertEqual(arguments[-2:], ('--bytes', str(PRESSURE_BATCH_BYTES)))
        self.assertEqual(host.guest.call_args.kwargs['timeout'], 15)

    def test_adaptive_enable_starts_host_timer_then_disables_blind_timer(self):
        host = object.__new__(DockerHost)
        host.doctor = Mock()
        host.install_pressure_units = Mock()
        host.pressure_unit_names = Mock(return_value=('pressure.service', 'pressure.timer'))
        host.guest = Mock()
        host.reclaim_status = Mock(return_value={})
        with patch.object(docker_host, 'command') as command:
            result = host.adaptive_reclaim({}, 'adaptive-enable')
        self.assertEqual(command.call_args_list, [
            unittest.mock.call('systemctl', '--user', 'disable', '--now',
                               'pressure.timer', timeout=30),
            unittest.mock.call('systemctl', '--user', 'enable', '--now',
                               'pressure.timer', timeout=30),
        ])
        self.assertEqual(host.guest.call_args.args[1:],
                         ('systemctl', '--user', 'disable', '--now', 'sandbox-reclaim.timer'))
        self.assertEqual(result['adaptive_reclamation']['operation'], 'adaptive-enable')

    def test_adaptive_enable_restores_guest_timer_when_host_enable_fails(self):
        host = object.__new__(DockerHost)
        host.doctor = Mock()
        host.install_pressure_units = Mock()
        host.pressure_unit_names = Mock(return_value=('pressure.service', 'pressure.timer'))
        host.guest = Mock()
        with patch.object(docker_host, 'command', side_effect=[None, subprocess.CalledProcessError(1, [])]):
            with self.assertRaises(subprocess.CalledProcessError):
                host.adaptive_reclaim({}, 'adaptive-enable')
        self.assertEqual(host.guest.call_args_list[-1].args[1:],
                         ('systemctl', '--user', 'enable', '--now', 'sandbox-reclaim.timer'))

    def test_adaptive_disable_restores_host_timer_when_guest_enable_fails(self):
        host = object.__new__(DockerHost)
        host.pressure_unit_names = Mock(return_value=('pressure.service', 'pressure.timer'))
        host.guest = Mock(side_effect=subprocess.CalledProcessError(1, []))
        with patch.object(docker_host, 'command') as command:
            with self.assertRaises(subprocess.CalledProcessError):
                host.adaptive_reclaim({}, 'adaptive-disable')
        self.assertEqual(command.call_args_list[-1],
                         unittest.mock.call('systemctl', '--user', 'enable', '--now',
                                            'pressure.timer', timeout=30))

    def test_pressure_units_bind_one_timer_to_the_owned_state(self):
        host = object.__new__(DockerHost)
        host.state = Path('/owned/state')
        units = host.pressure_unit_content({'instance': 'sandbox-host-docker-fixture'})
        service = units['codex-sandbox-pressure-fixture.service']
        timer = units['codex-sandbox-pressure-fixture.timer']
        self.assertIn('"--state" "/owned/state" "reclaim" "pressure"', service)
        self.assertIn('TimeoutStartSec=50s', service)
        self.assertIn('OnUnitInactiveSec=30s', timer)
        self.assertIn('Unit=codex-sandbox-pressure-fixture.service', timer)

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
