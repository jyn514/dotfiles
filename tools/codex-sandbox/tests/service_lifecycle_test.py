"""Controlled lifecycle concurrency; no installed state, VM, or service access."""
from concurrent.futures import ThreadPoolExecutor
import io
from pathlib import Path
import runpy
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest import mock

TOOL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOL))
import sandbox_runtime as runtime
from trusted_services import (CleanupFailure, CleanupResult, OwnedResource,
                              ResourcePresence, ResourceRegistry)
from docker_runtime import Docker


def load_launcher():
    return runpy.run_path(str(TOOL / 'codex-sandbox'))


def startup_state(root):
    manifest = root / 'manifest.json'
    manifest.write_text('{"commands": {}}')
    return SimpleNamespace(repository=root, uid=501, gid=20, manifest=manifest,
                           capabilities={'tic'}, sidecar_image='', deferred_signal=None,
                           proxy_lock=SimpleNamespace(shared=False), agent_docker=None)


def startup_replacements(launcher, state):
    empty = ('validate_repository', 'acquire_lock', 'load_repository_policy',
             'bind_repository_policy', 'recover_relays', 'stage_skills',
             'register_tmux_pane', 'ensure_network', 'prepare_gateway', 'attach_proxies')
    replacements = {name: mock.Mock(return_value=[]) for name in empty}
    replacements.update(OUTER_RUNTIME=runtime.ContainerRuntime(),
                        _secure_codex_auth_directory=lambda _: None,
                        prepare_declared_images=lambda *args: None,
                        resolve_model_image=lambda *args: 'agent@immutable',
                        run_agent=mock.Mock(return_value=17))
    return replacements


def cleanup_state(root):
    return SimpleNamespace(cleaned=False, cleanup_succeeded=False,
                           codex_container_created=False, gateway_handle=None,
                           tic_handle=None, tic_environment={'SANDBOX_TIC_TOKEN': 'old'},
                           tic_resources=None, proxy_lock=None, proxy_state=None,
                           proxy_args=None, manifest=None, prepared_images=None,
                           skills_tmp=None, pi_agent_tmp=None, repository=root,
                           resource_owner='owner')


class StartupOverlapTest(unittest.TestCase):
    def test_tic_and_proxies_overlap_with_settled_image_inputs_and_gate_agent(self):
        launcher = load_launcher()
        with tempfile.TemporaryDirectory() as directory:
            state = startup_state(Path(directory))
            proxy_started, tic_started, release = (threading.Event() for _ in range(3))
            replacements = startup_replacements(launcher, state)

            def proxies(_state):
                proxy_started.set()
                self.assertTrue(tic_started.wait(3), 'Tic still serialized after proxy publication')
                self.assertTrue(release.wait(3))
                return ['--proxy-ready']

            def tic(_state):
                self.assertEqual('agent@immutable', state.image)
                self.assertEqual('', state.sidecar_image)
                tic_started.set()
                self.assertTrue(proxy_started.wait(3))
                self.assertTrue(release.wait(3))
                return ['--tic-ready']

            replacements.update(attach_proxies=proxies, start_tic=tic)
            with mock.patch.dict(launcher['execute'].__globals__, replacements), ThreadPoolExecutor(1) as worker:
                future = worker.submit(launcher['execute'], state)
                try:
                    self.assertTrue(tic_started.wait(3))
                    self.assertTrue(proxy_started.wait(3))
                    replacements['run_agent'].assert_not_called()
                finally:
                    release.set()
                self.assertEqual(17, future.result(5))
            arguments = replacements['run_agent'].call_args.args[1]
            self.assertIn('--proxy-ready', arguments)
            self.assertIn('--tic-ready', arguments)

    def test_proxy_failure_closes_tic_gate_and_joins_worker_before_unwinding(self):
        launcher = load_launcher()
        with tempfile.TemporaryDirectory() as directory:
            state = startup_state(Path(directory))
            tic_started, finished = threading.Event(), threading.Event()
            replacements = startup_replacements(launcher, state)

            def tic(_state):
                tic_started.set()
                self.assertTrue(state.tic_cancelled.wait(3))
                finished.set()
                return []

            def proxies(_state):
                self.assertTrue(tic_started.wait(3))
                raise ValueError('injected proxy failure')

            replacements.update(attach_proxies=proxies, start_tic=tic)
            with mock.patch.dict(launcher['execute'].__globals__, replacements):
                with self.assertRaisesRegex(ValueError, 'injected proxy failure'):
                    launcher['execute'](state)
            self.assertTrue(finished.is_set())
            replacements['run_agent'].assert_not_called()

    def test_deferred_signal_closes_tic_gate_before_worker_join(self):
        launcher = load_launcher()
        state = SimpleNamespace(deferred_signal=15, joining_workers=False)
        finished = threading.Event()
        def worker():
            self.assertTrue(state.tic_cancelled.wait(3))
            finished.set()
        with self.assertRaises(launcher['SignalExit']):
            with launcher['startup_workers'](state, 1) as executor:
                executor.submit(worker)
        self.assertTrue(finished.is_set())
        self.assertFalse(state.joining_workers)


class CleanupOverlapTest(unittest.TestCase):
    def test_revoke_precedes_blocking_shared_cleanup_and_scratch_waits_for_both(self):
        launcher = load_launcher()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = cleanup_state(root)
            scratch = root / 'scratch'
            scratch.mkdir()
            state.skills_tmp = scratch
            revoked, tic_started, shared_started, release = (threading.Event() for _ in range(4))

            def stop(_status):
                self.assertTrue(revoked.is_set())
                tic_started.set()
                self.assertTrue(shared_started.wait(3), 'shared cleanup serialized after Tic')
                self.assertTrue(release.wait(3))
                self.assertTrue(scratch.exists())
                return CleanupResult(0, (), ())

            def shared(action):
                self.assertTrue(revoked.is_set())
                self.assertEqual({}, state.tic_environment)
                shared_started.set()
                self.assertTrue(tic_started.wait(3))
                self.assertTrue(release.wait(3))
                self.assertTrue(scratch.exists())
                action()

            state.tic_handle = SimpleNamespace(revoke=revoked.set, stop=stop)
            state.proxy_lock = SimpleNamespace(coordination=None, finish=shared)
            module = SimpleNamespace(reset_session=mock.Mock(), runtime_directory=lambda _: root,
                                     ConfigError=type('ConfigError', (ValueError,), {}))
            with mock.patch.dict(launcher['cleanup'].__globals__, OUTER_RUNTIME=runtime.ContainerRuntime(),
                                 proxy_module=lambda: module), ThreadPoolExecutor(1) as worker:
                future = worker.submit(launcher['cleanup'], state)
                try:
                    self.assertTrue(shared_started.wait(3))
                    self.assertTrue(tic_started.wait(3))
                    self.assertTrue(scratch.exists())
                    self.assertFalse(future.done())
                finally:
                    release.set()
                self.assertTrue(future.result(5))
            self.assertFalse(scratch.exists())
            module.reset_session.assert_called_once()

    def test_failures_from_both_branches_retain_recovery_and_return_false(self):
        launcher = load_launcher()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = cleanup_state(root)
            revoked, stopped = threading.Event(), threading.Event()
            failure = CleanupFailure('container:owned-tic', 'removal-failed:OSError')
            def stop(_status):
                self.assertTrue(revoked.is_set())
                stopped.set()
                return CleanupResult(0, (failure,), ('container:owned-tic',))
            def shared(_action):
                self.assertTrue(revoked.is_set())
                raise ValueError('injected shared failure')
            state.tic_handle = SimpleNamespace(revoke=revoked.set, stop=stop, owner='tic-owner')
            state.tic_resources = object()
            state.proxy_lock = SimpleNamespace(coordination=None, finish=shared)
            module = SimpleNamespace(ConfigError=ValueError)
            persist = mock.Mock()
            with mock.patch.dict(launcher['cleanup'].__globals__, OUTER_RUNTIME=runtime.ContainerRuntime(),
                                 proxy_module=lambda: module, persist_relay_recovery=persist,
                                 temporary_file=lambda: root / 'recovery.json',
                                 runtime_identity=lambda _: {'provider': 'fake'}), mock.patch('sys.stderr', new_callable=io.StringIO) as stderr:
                self.assertFalse(launcher['cleanup'](state))
            self.assertTrue(stopped.is_set())
            self.assertTrue(state.recovery_record.exists())
            persist.assert_called_once_with(state, state.tic_resources, 'tic-owner', ('container:owned-tic',))
            self.assertIn('Shared proxy cleanup failed', stderr.getvalue())
            self.assertIn('container:owned-tic', stderr.getvalue())


class ResourceQueryTest(unittest.TestCase):
    def test_inspect_failure_requires_successful_absence_listing(self):
        for listing_status, listing, expected in ((0, '', ResourcePresence.ABSENT),
                                                  (0, 'name\n', None), (1, '', None)):
            with self.subTest(status=listing_status, listing=listing):
                backend = runtime.ContainerRuntime()
                backend.run = mock.Mock(side_effect=[
                    SimpleNamespace(returncode=1, stdout=''),
                    SimpleNamespace(returncode=listing_status, stdout=listing)])
                if expected is None:
                    with self.assertRaises(ValueError):
                        runtime.resource_presence(backend, runtime.ResourceKind.VOLUME, 'name', 'owner')
                else:
                    self.assertIs(expected, runtime.resource_presence(
                        backend, runtime.ResourceKind.VOLUME, 'name', 'owner'))
                self.assertEqual(['volume', 'ls', '--format', '{{.Name}}'], backend.run.call_args.args[0])

    def test_replacement_between_registry_inspection_and_remove_preserves_foreign_owner(self):
        backend = runtime.ContainerRuntime()
        calls = []
        def run(args, **kwargs):
            calls.append(args)
            self.assertEqual(['volume', 'inspect'], args[:2], 'foreign resource mutated')
            return SimpleNamespace(returncode=0, stdout='owner' if len(calls) == 1 else 'foreign')
        backend.run = run
        registry = ResourceRegistry('owner')
        registry.RETRY_DELAYS = ()
        registry.register(OwnedResource('volume:name', 'owner',
            lambda: runtime.resource_presence(backend, runtime.ResourceKind.VOLUME, 'name', 'owner'),
            lambda: runtime.remove_owned_resource(backend, runtime.ResourceKind.VOLUME, 'name', 'owner')))
        result = registry.cleanup(0)
        self.assertEqual(('volume:name',), result.remaining)
        self.assertEqual('resource-owner-mismatch', result.failures[0].code)
        self.assertEqual(3, len(calls))

    def test_recovery_checks_engine_identity_on_each_inspect_and_mutation(self):
        backend = object.__new__(Docker)
        backend.recovery = True
        checks = []
        commands = []
        backend.verify_identity = lambda: checks.append('verified')
        backend.client_argv = lambda args: ['fake-docker', *args]
        def run(args, **kwargs):
            argv = backend.argv(args)
            commands.append(argv)
            return SimpleNamespace(returncode=0, stdout='owner')
        backend.run = run
        runtime.remove_owned_resource(backend, runtime.ResourceKind.CONTAINER, 'name', 'owner')
        self.assertEqual(3, len(checks))
        self.assertEqual(['inspect', 'kill', 'rm'], [c[2] if c[1] == 'container' else c[1] for c in commands])
        backend.verify_identity = mock.Mock(side_effect=ValueError('engine replaced'))
        with self.assertRaisesRegex(ValueError, 'engine replaced'):
            runtime.remove_owned_resource(backend, runtime.ResourceKind.CONTAINER, 'name', 'owner')
        self.assertEqual(3, len(commands))


if __name__ == '__main__':
    unittest.main()
