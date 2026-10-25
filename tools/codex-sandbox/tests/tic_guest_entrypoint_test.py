"""Owned local filesystem simulation, not guest-image/provider acceptance."""
import json
import os
import io
import runpy
import stat
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

TOOL = Path(__file__).resolve().parents[1]
WRAPPER = TOOL / 'image/ti'


class TicGuestEntrypointTest(unittest.TestCase):
    def test_accepted_old_image_gets_runtime_guard_for_opt_out_and_failed_startup(self):
        launcher = runpy.run_path(str(TOOL / 'codex-sandbox'))
        globals_ = launcher['build_agent_command'].__globals__
        for enabled in (False, True):
            with self.subTest(enabled=enabled), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                workspace = root / 'workspace'
                workspace.mkdir()
                guard_path = root / 'old-image/libexec/sandbox-wrappers/ti'
                guard_path.parent.mkdir(parents=True)
                self.assertFalse(guard_path.exists())  # Accepted image predates image/ti.
                native = root / 'old-image/bin/ti'
                native.parent.mkdir()
                marker = root / 'native-called'
                native.write_text(f'#!{sys.executable}\nfrom pathlib import Path\nPath({str(marker)!r}).touch()\n')
                native.chmod(0o700)
                state = SimpleNamespace(
                    image='accepted-old-image', sidecar_image='accepted-helper',
                    capabilities={'tic'} if enabled else set(), tic_environment={},
                    repository=workspace, container_repository=Path('/src/workspace'),
                    workspaces=[SimpleNamespace(host_root=workspace, guest_root=Path('/src/workspace'))],
                    skills_tmp=root / 'scratch', skills_source=root / 'skills',
                    pi_agent_tmp=root / 'private-agent', home=root / 'home', host_pi_package=root / 'pi',
                    codex_container='worker', github_credential=None, term='xterm', pi_model_session_id='fixture',
                )
                for path in (state.skills_tmp, state.skills_source, state.pi_agent_tmp):
                    path.mkdir(mode=0o700)
                runtime = mock.Mock()
                revision = 'a' * 40
                runtime.run.return_value = SimpleNamespace(stdout=revision + '\n')
                check = launcher['check_agent_pi_revision']
                with mock.patch.dict(check.__globals__, installed_pi_revision=lambda: revision):
                    check(runtime, state.image)  # The real compatibility check accepts this old image.
                resolve = mock.Mock(side_effect=launcher['LauncherError']('owned cold build failed'))
                replacements = {
                    'OUTER_RUNTIME': runtime, 'resolved_tic_build': resolve, 'proxy_flags': lambda: [],
                    'installed_config_source': lambda target: root / 'installed-config',
                    'agent_repository_mounts': lambda value: [
                        '--mount', f'type=bind,src={workspace},dst=/src/workspace'],
                }
                with mock.patch.dict(globals_, replacements), mock.patch('sys.stderr', new_callable=io.StringIO) as warning:
                    self.assertEqual([], launcher['start_tic'](state))
                    paths = launcher['host_pi_resource_paths'](state)
                    command = launcher['build_agent_command'](
                        state, [state.image, 'node', 'worker'], timing=False, resource_paths=paths,
                        guest_working_directory=state.container_repository, pi_extensions=root / 'extensions')
                self.assertEqual(enabled, 'continuing without it' in warning.getvalue())
                self.assertEqual(int(enabled), resolve.call_count)
                self.assertIn(state.image, command)  # Never rebuild/reselect the accepted image.
                mounts = [command[index + 1] for index, value in enumerate(command[:-1]) if value == '--mount']
                guard_mount = next(value for value in mounts if 'dst=/libexec/sandbox-wrappers/ti,' in value)
                self.assertTrue(guard_mount.endswith(',readonly'))
                staged = Path(guard_mount.split('src=', 1)[1].split(',', 1)[0])
                self.assertEqual(state.skills_tmp / 'tic-guard', staged)
                self.assertEqual(WRAPPER.read_bytes(), staged.read_bytes())
                self.assertFalse(os.path.samefile(WRAPPER, staged))
                self.assertEqual(0o555, stat.S_IMODE(staged.stat().st_mode))
                self.assertLess(command.index(guard_mount), command.index(state.image))
                self.assertNotIn('dst=/opt/agent-tools/bin/ti,', ' '.join(command))
                self.assertNotIn('codex-tic-link', ' '.join(command))
                # Simulate only the runtime read-only file bind in an owned old
                # filesystem. Its normal PATH initially resolves native Ti.
                path = str(guard_path.parent) + os.pathsep + str(native.parent) + os.pathsep + os.defpath
                before = subprocess.run(['ti'], env={'PATH': path}, capture_output=True, timeout=5)
                self.assertEqual(0, before.returncode)
                self.assertTrue(marker.exists())
                marker.unlink()
                guard_path.symlink_to(staged)
                environment = {'PATH': path, 'SANDBOX_TIC_ENDPOINT': 'stale-image-endpoint',
                               'SANDBOX_TIC_TOKEN': 'stale-image-token'}
                for index, value in enumerate(command[:-1]):
                    if value == '--env' and command[index + 1].startswith('SANDBOX_TIC_'):
                        name, value = command[index + 1].split('=', 1)
                        environment[name] = value
                result = subprocess.run(['ti', 'list'], env=environment, capture_output=True, text=True, timeout=5)
                self.assertEqual(125, result.returncode)
                self.assertIn('no fallback', result.stderr)
                self.assertFalse(marker.exists())
                self.assertEqual({}, state.tic_environment)
                state.__dict__.update(cleaned=False, cleanup_succeeded=False,
                                      codex_container_created=False, gateway_handle=None, proxy_lock=None,
                                      proxy_state=None, proxy_args=None, manifest=None, prepared_images=None)
                with mock.patch.dict(globals_, OUTER_RUNTIME=runtime):
                    self.assertTrue(launcher['cleanup'](state))
                self.assertFalse(staged.exists())
                self.assertFalse(state.skills_tmp.exists())

    def test_guard_staging_rejects_guest_writable_scratch_and_resolved_aliases(self):
        launcher = runpy.run_path(str(TOOL / 'codex-sandbox'))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            staged = root / 'scratch'
            staged.mkdir(mode=0o700)
            alias = root / 'scratch-alias'
            alias.symlink_to(root, target_is_directory=True)
            for source in (root, alias):
                with self.subTest(source=source), self.assertRaisesRegex(
                        launcher['LauncherError'], 'guest-writable mount'):
                    launcher['tic_guard_arguments'](SimpleNamespace(skills_tmp=staged), [
                        '--mount', f'type=bind,src={source},dst=/workspace'])
            self.assertFalse((staged / 'tic-guard').exists())

    def test_unavailable_entrypoint_never_searches_path_for_native_ti(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            marker = root / 'native-called'
            native = root / 'ti'
            native.write_text('#!/bin/sh\ntouch ' + shlex.quote(str(marker)) + '\n')
            native.chmod(0o700)
            for values in ({}, {'SANDBOX_TIC_ENDPOINT': 'fixture'}, {'SANDBOX_TIC_TOKEN': 'fixture'}):
                with self.subTest(values=values):
                    result = subprocess.run(['/bin/sh', str(WRAPPER), 'list'],
                                            env={'PATH': str(root) + os.pathsep + os.defpath, **values},
                                            capture_output=True, text=True, timeout=5)
                    self.assertEqual(125, result.returncode)
                    self.assertIn('unavailable for this session; no fallback', result.stderr)
                    self.assertFalse(marker.exists())
            self.assertIn('exec /opt/agent-tools/bin/ti "$@"', WRAPPER.read_text())

    def test_only_fixed_projected_client_is_executed_and_argv_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            client = root / 'projected-client'
            client.write_text(f'#!{sys.executable}\nimport json,sys\nprint(json.dumps(sys.argv[1:]))\n')
            client.chmod(0o700)
            launcher = runpy.run_path(str(TOOL / 'codex-sandbox'))
            state = SimpleNamespace(skills_tmp=root, tic_environment={
                'SANDBOX_TIC_ENDPOINT': 'fixture', 'SANDBOX_TIC_TOKEN': 'fixture'})
            mount = launcher['tic_guard_arguments'](state, [])
            self.assertEqual(['--mount', f'type=bind,src={root / "tic-guard"},'
                              'dst=/libexec/sandbox-wrappers/ti,readonly'], mount)
            wrapper = root / 'wrapper'
            # Translate only the fixed mount location into this test-owned tree;
            # the production entrypoint has no alternate-client setting.
            wrapper.write_text((root / 'tic-guard').read_text().replace(
                '/opt/agent-tools/bin/ti', shlex.quote(str(client))))
            arguments = ['show', 'two words', '--body', 'literal $HOME; *']
            environment = {'PATH': os.defpath, 'SANDBOX_TIC_ENDPOINT': 'fixture', 'SANDBOX_TIC_TOKEN': 'fixture'}
            result = subprocess.run(['/bin/sh', str(wrapper), *arguments], env=environment,
                                    capture_output=True, text=True, timeout=5)
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual(arguments, json.loads(result.stdout))
            client.unlink()
            result = subprocess.run(['/bin/sh', str(wrapper), 'list'], env=environment,
                                    capture_output=True, text=True, timeout=5)
            self.assertEqual(125, result.returncode)
            self.assertIn('no fallback', result.stderr)


if __name__ == '__main__':
    unittest.main()
