"""Direct tests of command-proxy authority, publication and attachment lifetime."""
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import command_proxy_session as owner
from sandbox_runtime import ContainerRuntime


class CommandProxySessionTest(unittest.TestCase):
    def session(self, root, runtime=None, **options):
        return owner.CommandProxySession(runtime or ContainerRuntime(), root,
            container_repository=Path('/home/codex/src/repo'), uid=501, gid=20, scratch=root, **options)

    def repository(self, directory):
        root = Path(directory) / 'repo'
        subprocess.run(['jj', 'git', 'init', str(root)], cwd=directory,
                       check=True, stdout=subprocess.DEVNULL)
        return root

    def test_policy_opt_out_drops_credentials_and_records_source_presence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            credentials = root / '.zuliprc'
            credentials.write_text('unused')
            source = root / '.agents/sandbox/proxy-commands.json'
            source.parent.mkdir(parents=True)
            source.write_text('{}')
            session = self.session(root)
            policy = {'capabilities': {'zulip': False}, 'commands': {}}
            with mock.patch.object(session._backend, 'snapshot_policy', return_value=policy), \
                    mock.patch.object(session._backend, 'bind_manifest'):
                self.assertIs(policy, session.snapshot(jj_image_command=Path('/jj'),
                    zulip_image_command=Path('/zulip'), zuliprc=credentials))
            self.assertIsNone(session.zuliprc)
            self.assertEqual(frozenset(), session.capabilities)
            self.assertTrue(session._source_present)

    def test_join_accepts_policy_images_without_current_policy_discovery(self):
        with tempfile.TemporaryDirectory() as directory:
            session = self.session(Path(directory))
            session._lock = mock.Mock(shared=True)
            session._journal = Path(directory) / 'recovery'
            policy = {'commands': {'jj': {}}, 'capabilities': {'tic': True}}
            accepted = {'manifest': policy, 'source-present': True,
                        'images': {'agent': 'agent', 'helper': 'helper', 'proxies': {'jj': 'jj'}}}
            state = {'proxies': []}
            module = session._backend
            with mock.patch.object(module, 'join_session', return_value=(state, accepted)), \
                    mock.patch.object(module, 'snapshot_policy', side_effect=AssertionError('current policy')):
                self.assertIs(accepted, session.join())
            self.assertIs(policy, session.policy)
            self.assertEqual(frozenset({'tic'}), session.capabilities)
            with mock.patch.object(module, 'attach_session', return_value=(state, policy, False)) as attach:
                session.attach(prefix='prefix', network='network', agent_image='agent', helper_image='helper')
            request, selected, images = attach.call_args.args
            self.assertEqual({'jj': 'jj'}, images)
            self.assertIs(policy, selected)
            self.assertTrue(request.shared)
            self.assertEqual(session._journal, request.state)
            self.assertEqual('agent', request.agent_image)

    def test_join_and_attach_keep_workspace_authority_without_transport_files(self):
        from workspace_layout import discover_workspace
        with tempfile.TemporaryDirectory() as directory:
            root = self.repository(directory)
            layout = discover_workspace(root, Path('/home/codex/src/repo'), Path(directory))
            session = owner.CommandProxySession(ContainerRuntime(), root,
                container_repository=layout.guest_root, uid=501, gid=20,
                workspaces=[layout], metadata=(layout.git_dir, layout.common_dir))
            session._lock = mock.Mock(shared=True)
            session._journal = root / 'recovery.json'
            policy = {'commands': {}}
            seen = []
            def join(request):
                seen.append(request.workspaces)
                return {}, {'manifest': policy, 'source-present': False,
                            'images': {'agent': 'agent', 'helper': None, 'proxies': {}}}
            def attach(request, manifest, images):
                seen.append(request.workspaces)
                self.assertIs(policy, manifest)
                self.assertEqual({}, images)
                return {}, manifest, False
            module = session._backend
            with mock.patch.object(module, 'join_session', side_effect=join), \
                    mock.patch.object(module, 'attach_session', side_effect=attach), \
                    mock.patch.object(owner.tempfile, 'mkstemp', side_effect=AssertionError('transport file')):
                session.join()
                session.attach(prefix='fixture', network='network', agent_image='agent', helper_image='')
            self.assertEqual([[layout.to_dict()]] * 2, seen)
            self.assertEqual((layout.git_dir, layout.common_dir), module.git_metadata_paths(root))

    def test_cancelled_lock_acquisition_keeps_journal_available_for_cleanup(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self.repository(directory)
            session = self.session(root)
            with mock.patch.object(owner, 'SessionLock', side_effect=KeyboardInterrupt):
                with self.assertRaises(KeyboardInterrupt):
                    session.acquire()
            self.assertTrue(session.recovery_path.exists())
            with mock.patch.object(session._backend, 'reset_session') as remove:
                session.finish(completed_successfully=False)
            remove.assert_not_called()
            session.discard_staging()
            self.assertFalse(session.recovery_path.exists())

    def test_only_first_session_publishes_and_arguments_remain_a_list(self):
        with tempfile.TemporaryDirectory() as directory:
            for shared, reused in ((True, False), (False, True), (False, False)):
                with self.subTest(shared=shared, reused=reused):
                    session = self.session(Path(directory))
                    session._lock = mock.Mock(shared=shared)
                    module = session._backend
                    policy, state = {'commands': {}}, {'proxies': []}
                    session._policy = policy
                    calls = []
                    with mock.patch.object(module, 'attach_session', return_value=(state, policy, reused)), \
                            mock.patch.object(module, 'publish_session', side_effect=lambda *args: calls.append('publish')) as publish, \
                            mock.patch.object(module, 'agent_arguments', side_effect=lambda *args: calls.append('args') or ['--read-only']):
                        session.attach(prefix='prefix', network='network', agent_image='agent', helper_image='helper')
                        session.publish()
                        self.assertEqual(['--read-only'], session.agent_arguments())
                    self.assertEqual(['args'] if shared or reused else ['publish', 'args'], calls)
                    if not shared and not reused:
                        publish.assert_called_once_with(session.repository, '/home/codex/src/repo', state, policy)
                    session._lock.release_coordination.assert_not_called()

    def test_policy_binding_and_legacy_builder_errors_still_use_the_admitted_owner(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            session = self.session(root)
            session._policy = {'commands': {}}
            bake = root / '.agents/sandbox/bake'
            bake.parent.mkdir(parents=True)
            bake.touch()
            with self.assertRaisesRegex(owner.SessionError, 'CODEX_SANDBOX_RUNTIME=lima-docker'):
                session.bind_policy()
            bake.unlink()
            session._policy = {'commands': {'broken': {'image-command': ['/bin/false']}}}
            with mock.patch.object(session._backend, 'main', side_effect=AssertionError('CLI dispatch')):
                with self.assertRaisesRegex(owner.SessionError, 'image-command for broken'):
                    session.resolve_images()

    def test_reset_uses_private_runtime_and_never_dispatches_cli(self):
        session = self.session(Path('/example'))
        module = session._backend
        with mock.patch.object(module, 'reset_repository') as recover, \
                mock.patch.object(module, 'main', side_effect=AssertionError('CLI dispatch')), \
                mock.patch('subprocess.run', side_effect=AssertionError('unexpected process')):
            session.reset(wait=True)
            recover.assert_called_once_with(Path('/example'), wait=True)
            recover.side_effect = module.ConfigError('recovery failed')
            with self.assertRaisesRegex(owner.SessionError, 'recovery failed'):
                session.reset(wait=True)

    def test_private_bindings_survive_concurrent_consumption_and_new_attachment(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            sessions = []
            for name in ('first', 'second'):
                runtime = mock.Mock(provider=name)
                runtime.verify_builder_image.side_effect = lambda image, name=name: SimpleNamespace(reference=name + ':' + image)
                paths = (repo / name / 'git', repo / name / 'common')
                for path in paths:
                    path.mkdir(parents=True)
                session = self.session(repo, runtime, metadata=paths)
                sessions.append((session, paths))
            barrier = threading.Barrier(2)
            def consume(value):
                session, paths = value
                barrier.wait(timeout=3)
                module = session._backend
                self.assertIs(module.OUTER_RUNTIME, session.runtime)
                self.assertEqual(paths, module.git_metadata_paths(repo))
                self.assertEqual({'one': session.runtime.provider + ':image'}, module.resolve_images(
                    repo, {'commands': {'one': {}}}, {'one': 'image'}))
            with mock.patch('subprocess.run', side_effect=AssertionError('unexpected discovery or CLI')), \
                    ThreadPoolExecutor(max_workers=2) as workers:
                list(workers.map(consume, sessions))
            replacement = self.session(repo)
            self.assertIsNone(replacement._backend.REPOSITORY_METADATA)
            self.assertIsNot(sessions[0][0]._backend, sessions[1][0]._backend)
            self.assertIsNot(replacement._backend, sessions[0][0]._backend)

    def test_last_attachment_removes_services_and_finish_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory, mock.patch.dict(os.environ, HOME=directory):
            root = self.repository(directory)
            first = self.session(root)
            first.acquire()
            recovery = {'runtime': {'provider': 'container'}, 'proxies': []}
            metadata = first.directory / 'session.json'
            metadata.write_text(json.dumps({'version': 2, 'state': recovery}))
            first.release_coordination()
            second = self.session(root)
            second.acquire()
            with mock.patch.object(first._backend, 'stop_state') as first_stop, \
                    mock.patch.object(second._backend, 'stop_state') as stop:
                first.finish(completed_successfully=False)
                first_stop.assert_not_called()
                self.assertTrue(metadata.exists())
                second.finish(completed_successfully=False)
                stop.assert_called_once_with(recovery)
                self.assertFalse(metadata.exists())
                second.finish(completed_successfully=False)
                self.assertEqual(1, stop.call_count)
            first.discard_staging()
            second.discard_staging()

    def test_successful_final_attachment_retains_services_and_detaches_janitor(self):
        with tempfile.TemporaryDirectory() as directory, mock.patch.dict(os.environ, HOME=directory):
            root = self.repository(directory)
            session = self.session(root)
            session.acquire()
            metadata = session.directory / 'session.json'
            metadata.write_text(json.dumps({'version': 2, 'state': {
                'runtime': {'provider': 'container'}, 'proxies': []}}))
            session.release_coordination()
            with mock.patch.object(session._backend, 'stop_state') as stop, \
                    mock.patch.object(owner.secrets, 'token_hex', return_value='lease'), \
                    mock.patch.object(owner.subprocess, 'Popen') as start:
                session.finish(completed_successfully=True)
            stop.assert_not_called()
            self.assertTrue(metadata.exists())
            command = start.call_args.args[0]
            self.assertEqual(['idle-cleanup', '--repo', str(root), '--delay', '300.0', '--lease', 'lease'], command[1:])
            self.assertTrue(start.call_args.kwargs['start_new_session'])
            self.assertEqual('lease', (session.directory / 'idle-cleanup.lease').read_text())
            session.discard_staging()

    def test_janitor_spawn_failure_clears_lease_and_removes_published_state(self):
        with tempfile.TemporaryDirectory() as directory, mock.patch.dict(os.environ, HOME=directory):
            root = self.repository(directory)
            session = self.session(root)
            session.acquire()
            metadata = session.directory / 'session.json'
            recovery = {'runtime': {'provider': 'container'}, 'proxies': []}
            metadata.write_text(json.dumps({'version': 2, 'state': recovery}))
            session.release_coordination()
            with mock.patch.object(session._backend, 'stop_state') as stop, \
                    mock.patch.object(owner.subprocess, 'Popen', side_effect=OSError('spawn failed')):
                session.finish(completed_successfully=True)
            stop.assert_called_once_with(recovery)
            self.assertFalse(metadata.exists())
            self.assertFalse((session.directory / 'idle-cleanup.lease').exists())
            session.discard_staging()

    def test_failed_unpublished_removal_keeps_journal_and_publishes_recovery(self):
        with tempfile.TemporaryDirectory() as directory, mock.patch.dict(os.environ, HOME=directory):
            root = self.repository(directory)
            session = self.session(root)
            session.acquire()
            recovery = {'runtime': {'provider': 'container'}, 'proxies': []}
            session.recovery_path.write_text(json.dumps(recovery))
            with mock.patch.object(session._backend, 'stop_state', side_effect=session._backend.ConfigError('busy')):
                with self.assertRaisesRegex(owner.SessionError, 'busy'):
                    session.finish(completed_successfully=False)
            metadata = session.directory / 'session.json'
            self.assertEqual(recovery, session._backend.session_state(json.loads(metadata.read_text())))
            self.assertTrue(session.recovery_path.exists())
            with mock.patch.object(session._backend, 'stop_state') as stop:
                session.reset()
            stop.assert_called_once_with(recovery)
            self.assertFalse(metadata.exists())
            session.discard_staging()


if __name__ == '__main__':
    unittest.main()
