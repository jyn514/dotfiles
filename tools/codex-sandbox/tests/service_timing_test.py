"""Opt-in phase evidence without installed services or VM access."""
from concurrent.futures import ThreadPoolExecutor
import importlib.util
import io
import os
from pathlib import Path
import runpy
import subprocess
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest import mock

TOOL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOL))
import trusted_services
from trusted_services import service_timing


def load_proxies():
    spec = importlib.util.spec_from_file_location('timing_proxies', TOOL / 'sandbox-proxies.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ServiceTimingTest(unittest.TestCase):
    def test_default_silence_does_not_read_clock(self):
        with mock.patch.dict(os.environ, {'CODEX_SANDBOX_TIMING': ''}), \
                mock.patch('sys.stderr', new_callable=io.StringIO) as stderr, \
                mock.patch('sys.stdout', new_callable=io.StringIO) as stdout, \
                mock.patch.object(trusted_services.time, 'monotonic') as clock:
            with service_timing('tic', 'bundle'):
                pass
        self.assertEqual('', stderr.getvalue())
        self.assertEqual('', stdout.getvalue())
        clock.assert_not_called()

    def test_opt_in_failure_elapsed_stderr_only_preserves_exception(self):
        failure = KeyboardInterrupt('secret path endpoint token')
        with mock.patch.dict(os.environ, {'CODEX_SANDBOX_TIMING': '1'}), \
                mock.patch('sys.stderr', new_callable=io.StringIO) as stderr, \
                mock.patch('sys.stdout', new_callable=io.StringIO) as stdout, \
                mock.patch.object(trusted_services.time, 'monotonic', side_effect=[10, 10.125]):
            with self.assertRaises(KeyboardInterrupt) as caught:
                with service_timing('tic', 'guest-help-once'):
                    raise failure
        self.assertIs(failure, caught.exception)
        self.assertEqual('Sandbox service: tic/guest-help-once=0.12s failed\n', stderr.getvalue())
        self.assertEqual('', stdout.getvalue())

    def test_unknown_command_role_is_not_logged(self):
        with mock.patch.dict(os.environ, {'CODEX_SANDBOX_TIMING': '1'}), \
                mock.patch('sys.stderr', new_callable=io.StringIO) as stderr:
            with service_timing('secret\nhttps://token.invalid', 'readiness'):
                pass
        self.assertRegex(stderr.getvalue(), r'^Sandbox service: command/readiness=\d+\.\d{2}s\n$')

    def test_diagnostic_sink_failure_does_not_change_outcome(self):
        for failure in (None, ValueError('original operation')):
            with self.subTest(failure=failure), \
                    mock.patch.dict(os.environ, {'CODEX_SANDBOX_TIMING': '1'}), \
                    mock.patch('sys.stderr.write', side_effect=OSError('closed')):
                if failure is None:
                    with service_timing('tic', 'bundle'):
                        pass
                else:
                    with self.assertRaises(ValueError) as caught:
                        with service_timing('tic', 'bundle'):
                            raise failure
                    self.assertIs(failure, caught.exception)

    def test_timed_workers_overlap_and_write_one_atomic_line_each(self):
        barrier = threading.Barrier(4)
        writes = []
        stream = SimpleNamespace(write=lambda line: writes.append(line))
        def work():
            with service_timing('jj', 'readiness'):
                barrier.wait(timeout=3)
        with mock.patch.dict(os.environ, {'CODEX_SANDBOX_TIMING': '1'}), \
                mock.patch('sys.stderr', stream), ThreadPoolExecutor(max_workers=4) as workers:
            list(workers.map(lambda _: work(), range(4)))
        self.assertEqual(4, len(writes))
        for line in writes:
            self.assertRegex(line, r'^Sandbox service: jj/readiness=\d+\.\d{2}s\n$')

    def test_launcher_separates_command_auth_and_publication_in_order(self):
        launcher = runpy.run_path(str(TOOL / 'codex-sandbox'))
        state = SimpleNamespace(repository=Path('/repo'), container_repository=Path('/src/repo'),
                                proxy_prefix='prefix', proxy_lock=SimpleNamespace(shared=False,
                                    release_coordination=lambda: events.append('unlock')),
                                proxy_state=Path('/state'), sidecar_image='', manifest=Path('/manifest'),
                                image='image', uid=1, gid=2, policy_source_present=True,
                                zuliprc=None, prepared_images=None)
        events = []
        patches = {'_secure_codex_auth_directory': lambda _: None,
                   'helper': lambda *args: events.append('commands'),
                   'attach_codex_sidecar': lambda *args: (events.append('auth') or ['auth']),
                   'finalize_proxy_session': lambda *args: (events.append('publication') or ['proxy'])}
        with mock.patch.dict(os.environ, {'CODEX_SANDBOX_TIMING': '1'}), \
                mock.patch('sys.stderr', new_callable=io.StringIO) as stderr, \
                mock.patch.dict(launcher['attach_proxies'].__globals__, patches):
            self.assertEqual(['auth', 'proxy'], launcher['attach_proxies'](state))
        self.assertEqual(['commands', 'auth', 'publication', 'unlock'], events)
        self.assertEqual(['proxies/command-attach', 'auth/attach', 'proxies/publication'],
                         [line.split(': ')[1].split('=')[0] for line in stderr.getvalue().splitlines()])

    def test_command_startup_measures_engine_and_readiness_without_stdout(self):
        module = load_proxies()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            args = SimpleNamespace(prefix='test', state=str(root / 'state'),
                                   network='sandbox', container_repo='/src/repository', zuliprc=None)
            command = {'argv': ['example-proxy', 'serve'], 'network': False,
                       'workdir': '.', 'mounts': []}
            completed = subprocess.CompletedProcess([], 0, stdout='', stderr='')
            with mock.patch.dict(os.environ, {'CODEX_SANDBOX_TIMING': '1'}), \
                    mock.patch('sys.stderr', new_callable=io.StringIO) as stderr, \
                    mock.patch('sys.stdout', new_callable=io.StringIO) as stdout, \
                    mock.patch.object(module, '_docker', return_value=completed) as engine, \
                    mock.patch.object(module.subprocess, 'run', return_value=completed) as ready:
                proxy = module.start_one_proxy(args, root, 'identity', {'example': 'sha256:' + '0' * 64},
                                              {'proxies': []}, threading.Lock(), 'example', command)
            self.assertEqual('ready', proxy['lifecycle-state'])
            self.assertEqual(2, engine.call_count)
            ready.assert_called_once()
            self.assertEqual('', stdout.getvalue())
            self.assertEqual(['command/volume-initialize', 'command/repository-mounts',
                              'command/container-run', 'command/readiness'],
                             [line.split(': ')[1].split('=')[0] for line in stderr.getvalue().splitlines()])

    def test_shared_command_registry_cleanup_keeps_parallel_workers(self):
        module = load_proxies()
        barrier = threading.Barrier(2)
        def registry(*_args):
            def cleanup(_status):
                barrier.wait(timeout=3)
                return SimpleNamespace(remaining=())
            return SimpleNamespace(cleanup=cleanup, adapter_diagnostics=[])
        state = {'proxies': [{'name': 'jj', 'service-owner': 'one'},
                             {'name': 'gh', 'service-owner': 'two'}]}
        with mock.patch.dict(os.environ, {'CODEX_SANDBOX_TIMING': '1'}), \
                mock.patch('sys.stderr', new_callable=io.StringIO) as stderr, \
                mock.patch.object(module, '_managed_proxy_record', return_value=None), \
                mock.patch.object(module, 'state_runtime', return_value=object()) as query, \
                mock.patch.object(module, 'recorded_proxy_volumes', return_value=set()), \
                mock.patch.object(module, 'remove_stopped_sandbox_holders', return_value=[]) as holders, \
                mock.patch.object(module, '_proxy_registry', side_effect=registry):
            module.stop_state(state)
        query.assert_called_once_with(state, recovery=True)
        holders.assert_called_once()
        self.assertCountEqual(['proxies/cleanup-runtime-query', 'proxies/cleanup-stopped-holders',
                               'jj/cleanup-registry', 'gh/cleanup-registry'],
                              [line.split(': ')[1].split('=')[0] for line in stderr.getvalue().splitlines()])


if __name__ == '__main__':
    unittest.main()
