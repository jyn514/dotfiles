"""Owned artifact/compiler and provider fakes; no operational broker, guest or Pi."""
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import runpy
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

TOOL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOL))
sys.path.insert(0, str(TOOL.parent / 'tic-proxy'))
import bundle
import tic_artifact
from workspace_layout import WorkspaceLayout


class TicCdPreflightTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.addCleanup(self.make_writable)
        self.home = self.root / 'home'
        self.repository = self.home / 'src/target'
        self.repository.mkdir(parents=True)
        (self.repository / '.git').mkdir()
        (self.repository / '.jj').mkdir()
        (self.home / '.agents/skills').mkdir(parents=True)
        self.workspace = WorkspaceLayout(
            self.repository, Path('/src/target'), self.repository / '.git',
            self.repository / '.git', self.repository / '.jj', self.home / 'request.lock')
        self.launcher = runpy.run_path(str(TOOL / 'codex-sandbox'))
        self.launch = self.launcher['launch']
        self.state = SimpleNamespace(home=self.home, repository=self.repository,
                                     host_working_directory=self.repository, manifest=None,
                                     capabilities=frozenset(), uid=os.getuid(), gid=os.getgid(),
                                     skills_source=None, pi_agent_tmp=None, workspaces=[])
        self.events = []
        self.runtime = mock.Mock(provider='container')
        self.runtime.build_platform.return_value = 'linux/amd64'
        self.runtime.verify_builder_image.side_effect = lambda image: image
        self.compiler = mock.Mock(side_effect=self.compile_bundle)
        self.selected = True
        self.broker_status = 0
        self.inspect = self.launcher['inspect_tic_context']
        self.forbidden = {name: mock.Mock(side_effect=AssertionError(name + ' during preflight'))
                          for name in ('acquire_lock', 'cleanup', 'unregister_tmux_pane',
                                       'register_tmux_pane', 'run_agent', 'ensure_network',
                                       'attach_proxies', 'TicBrokerLaunch', 'ensure_request_lock',
                                       'initialize_dotfiles', 'start_tic')}
        self.replacements = {
            **self.forbidden,
            'new_state': lambda _: self.state,
            'validate_repository': mock.Mock(),
            'image_runtime': lambda: self.runtime,
            'load_repository_policy': self.load_policy,
            'discover_launch_workspaces': mock.Mock(return_value=[self.workspace]),
            'prepare_declared_images': lambda *_: SimpleNamespace(base='target-base'),
            'resolve_agent': lambda *_: 'target-image',
            'resolve_sidecar_image': lambda: self.events.append('transport image') or 'transport-image',
            'inspect_tic_context': self.inspect_context,
        }

    def make_writable(self):
        for directory, _, _ in os.walk(self.root, followlinks=False):
            if not Path(directory).is_symlink():
                Path(directory).chmod(0o700)

    def load_policy(self, state):
        state.manifest = self.root / 'policy.json'
        state.manifest.write_text(json.dumps({'commands': {}}))
        state.capabilities = frozenset({'tic'} if self.selected else ())

    def compile_bundle(self, source, expected):
        self.events.append('compile')
        build_root = self.root / ('build-' + str(self.compiler.call_count))
        build_root.mkdir()
        native = build_root / 'ti'
        native.write_bytes(b'owned non-operational native fixture')
        native.with_name('ti.tic-proxy.json').write_text(json.dumps({
            'native_revision': bundle.PIN, 'policy_version': 1,
            'sha256': hashlib.sha256(native.read_bytes()).hexdigest()}))
        broker = build_root / 'tic-broker'
        # Only the trusted metadata command is executable; operational broker
        # startup is forbidden above and cannot pass this fixture's assertion.
        broker.write_text('#!' + sys.executable + '\nimport sys,json\n'
                          'assert sys.argv[1] == "inspect-context"\n'
                          + f'if {self.broker_status}: sys.exit({self.broker_status})\n'
                          + 'print(json.dumps(' + repr({
                              'version': 1, 'policy_version': 1, 'native_revision': bundle.PIN,
                              'workspace': str(self.repository), 'common_dir': str(self.workspace.common_dir),
                              'invocation_git_dir': str(self.workspace.git_dir)}) + '))\n')
        client = build_root / 'ti-proxy'
        elf = bytearray(120)
        elf[:8] = b'\x7fELF\x02\x01\x01\x00'
        elf[18:20] = (62).to_bytes(2, 'little')
        elf[32:40] = (64).to_bytes(8, 'little')
        elf[54:56] = (56).to_bytes(2, 'little')
        elf[56:58] = (1).to_bytes(2, 'little')
        client.write_bytes(elf)
        stage = runpy.run_path(str(TOOL.parent / 'tic-proxy/build-local'))['stage_bundle']
        result = stage(build_root, bundle.PIN, native, broker, client, 'linux/amd64', expected)
        self.events.append('compiled')
        return result

    def inspect_context(self, build, workspace):
        self.events.append('inspect context')
        return self.inspect(build, workspace)

    @contextlib.contextmanager
    def patched(self):
        with mock.patch.dict(self.launch.__globals__, self.replacements), mock.patch.object(
                tic_artifact, 'native_source', return_value=self.root / 'owned-source'), mock.patch.object(
                tic_artifact, 'build_bundle', self.compiler):
            yield

    def prepare(self):
        output, errors = io.StringIO(), io.StringIO()
        cwd = Path.cwd()
        try:
            with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
                code = self.launch(['prepare-cd', str(self.repository)])
        finally:
            os.chdir(cwd)
        self.assertFalse((self.root / 'policy.json').exists())
        for forbidden in self.forbidden.values():
            forbidden.assert_not_called()
        return code, output.getvalue(), errors.getvalue()

    def test_build_and_context_finish_before_success_record_and_startup_reuses_same_cache(self):
        with self.patched():
            code, output, errors = self.prepare()
            self.assertEqual((code, errors), (0, ''))
            self.assertEqual(json.loads(output), {'destination': str(self.repository),
                                                  'repository': str(self.repository)})
            self.events.append('handoff permitted')
            self.assertEqual(self.events, ['compile', 'compiled', 'inspect context',
                                           'transport image', 'handoff permitted'])
            # Resume the real target startup path, stopping immediately before
            # broker construction. It must resolve the exact already-built key.
            before = self.compiler.call_count
            startup_boundary = RuntimeError('owned stop before operational broker')
            self.state.sidecar_image = 'transport-image'
            with mock.patch.dict(self.launch.__globals__, {
                    'TicBrokerLaunch': mock.Mock(side_effect=startup_boundary)}):
                with self.assertRaisesRegex(RuntimeError, 'owned stop'):
                    self.launcher['_start_tic'](self.state)
            self.assertEqual(self.compiler.call_count, before)
            self.assertEqual(before, 1)
            self.assertEqual(len(list((self.home / '.cache/codex-sandbox/tic').glob('*/bundle-*/manifest.json'))), 1)

    def test_failed_compile_has_no_success_record_and_does_not_disable_tic(self):
        self.compiler.side_effect = subprocess.CalledProcessError(1, ['owned-compiler'])
        with self.patched():
            code, output, errors = self.prepare()
        self.assertEqual(code, 1)
        self.assertEqual(output, '')
        self.assertIn('TicGit bundle resolution failed', errors)
        self.assertIn('tic', self.state.capabilities)
        self.assertNotIn('transport image', self.events)

    def test_keyboard_interrupt_has_no_success_record_and_cleans_snapshot(self):
        self.compiler.side_effect = KeyboardInterrupt
        with self.patched(), self.assertRaises(KeyboardInterrupt):
            self.prepare()
        self.assertFalse((self.root / 'policy.json').exists())
        for forbidden in self.forbidden.values():
            forbidden.assert_not_called()

    def test_explicit_false_skips_all_tic_discovery_resolution_context_and_transport(self):
        self.selected = False
        with self.patched():
            code, output, errors = self.prepare()
        self.assertEqual((code, errors), (0, ''))
        self.assertTrue(output)
        self.compiler.assert_not_called()
        self.replacements['discover_launch_workspaces'].assert_not_called()
        self.assertEqual(self.events, [])

    def test_unsupported_context_allows_handoff_after_build_and_matches_fresh_startup(self):
        self.broker_status = 23
        with self.patched():
            code, output, errors = self.prepare()
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(output), {'destination': str(self.repository),
                                                  'repository': str(self.repository)})
            self.assertIn('warning: TicGit unavailable for this session; continuing without it:', errors)
            self.assertIn('trusted context inspection failed', errors)
            self.assertEqual(self.events, ['compile', 'compiled', 'inspect context', 'transport image'])
            # The real fresh-start owner uses the same built cache, reports the
            # same context failure, and disables TicGit without starting a broker.
            self.state.image = 'target-image'
            self.state.sidecar_image = 'transport-image'
            startup_errors = io.StringIO()
            with contextlib.redirect_stderr(startup_errors):
                self.assertEqual(self.launcher['start_tic'](self.state), [])
            self.assertEqual(startup_errors.getvalue(), errors)
            self.assertEqual(self.state.tic_environment, {})
            self.compiler.assert_called_once()
            for forbidden in self.forbidden.values():
                forbidden.assert_not_called()

    def test_workspace_authority_failure_remains_fatal_before_build(self):
        from workspace_layout import WorkspaceError
        self.replacements['discover_launch_workspaces'].side_effect = WorkspaceError('invalid workspace authority')
        with self.patched():
            code, output, errors = self.prepare()
        self.assertEqual(code, 1)
        self.assertEqual(output, '')
        self.assertIn('invalid workspace authority', errors)
        self.assertNotIn('warning: TicGit unavailable', errors)
        self.compiler.assert_not_called()

    def test_transport_image_authority_failure_remains_fatal_after_context_warning(self):
        self.broker_status = 23
        self.runtime.verify_builder_image.side_effect = ValueError('transport image platform mismatch')
        with self.patched():
            code, output, errors = self.prepare()
        self.assertEqual(code, 1)
        self.assertEqual(output, '')
        self.assertIn('trusted context inspection failed', errors)
        self.assertIn('transport image platform mismatch', errors)
        self.compiler.assert_called_once()

    def test_changed_source_requires_new_build_and_failure_cannot_handoff(self):
        with self.patched():
            self.assertEqual(self.prepare()[0], 0)
            changed = bundle.build_identity(bundle.host_platform(), 'linux/amd64')
            changed['proxy_source'] = 'f' * 64
            self.compiler.side_effect = subprocess.CalledProcessError(2, ['changed-source-compiler'])
            with mock.patch.object(tic_artifact, 'build_identity', return_value=changed):
                code, output, errors = self.prepare()
        self.assertEqual(code, 1)
        self.assertEqual(output, '')
        self.assertIn('TicGit bundle resolution failed', errors)
        self.assertEqual(self.compiler.call_count, 2)

    def test_malformed_current_cache_is_reported_without_repair_or_handoff(self):
        with self.patched():
            self.assertEqual(self.prepare()[0], 0)
            manifest = next((self.home / '.cache/codex-sandbox/tic').glob('*/bundle-*/manifest.json'))
            manifest.chmod(0o600)
            manifest.write_text('{}')
            manifest.chmod(0o444)
            code, output, errors = self.prepare()
        self.assertEqual(code, 1)
        self.assertEqual(output, '')
        self.assertIn('TicGit bundle resolution failed', errors)
        self.assertEqual(self.compiler.call_count, 1)

    def test_transport_image_build_failure_blocks_success(self):
        self.replacements['resolve_sidecar_image'] = mock.Mock(side_effect=ValueError('transport image build failed'))
        with self.patched():
            code, output, errors = self.prepare()
        self.assertEqual(code, 1)
        self.assertEqual(output, '')
        self.assertIn('transport image build failed', errors)

    def test_cache_cannot_overlap_secondary_guest_writable_workspace(self):
        cache = self.home / '.cache/codex-sandbox/tic'
        cache.mkdir(parents=True)
        (cache / '.git').mkdir()
        (cache / '.jj').mkdir()
        self.replacements['discover_launch_workspaces'].return_value.append(WorkspaceLayout(
            cache, Path('/src/dotfiles'), cache / '.git', cache / '.git',
            cache / '.jj', self.home / 'second-request.lock'))
        with self.patched():
            code, output, errors = self.prepare()
        self.assertEqual(code, 1)
        self.assertEqual(output, '')
        self.assertIn('cache overlaps a guest-writable mount', errors)
        self.compiler.assert_not_called()

    def test_cache_cannot_overlap_guest_writable_skills(self):
        cache = self.home / '.cache/codex-sandbox/tic'
        cache.mkdir(parents=True)
        skills = self.home / '.agents/skills'
        skills.rmdir()
        skills.symlink_to(cache, target_is_directory=True)
        with self.patched():
            code, output, errors = self.prepare()
        self.assertEqual(code, 1)
        self.assertEqual(output, '')
        self.assertIn('cache overlaps a guest-writable mount', errors)
        self.compiler.assert_not_called()

    def test_real_workspace_discovery_does_not_create_locks_or_initialize_dotfiles(self):
        dotfiles = self.home / 'src/dotfiles'
        (self.repository / '.git').rmdir()
        (self.repository / '.jj').rmdir()
        for repository in (self.repository, dotfiles):
            subprocess.run([os.environ.get('DOTFILES_TEST_JJ_REAL', 'jj'), 'git', 'init',
                            '--colocate', str(repository)], cwd=self.home, check=True, capture_output=True)
        self.replacements.update({
            'DOTFILES': dotfiles,
            'discover_launch_workspaces': self.launcher['discover_launch_workspaces'],
        })
        with self.patched():
            code, output, errors = self.prepare()
        self.assertEqual((code, errors), (0, ''))
        self.assertTrue(output)
        self.assertEqual([workspace.host_root for workspace in self.state.workspaces],
                         [self.repository, dotfiles])
        for workspace in self.state.workspaces:
            self.assertFalse(workspace.lock_file.exists())
        self.assertFalse((self.home / '.cache/codex-sandbox-proxies').exists())


if __name__ == '__main__':
    unittest.main()
