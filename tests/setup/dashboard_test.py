"""Source input selection, patch/build isolation, activation, and runtime policy."""

import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('dashboard_setup', ROOT / 'libexec/setup/setup_dashboard.py')
dashboard = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(dashboard)


class DashboardManifestTests(unittest.TestCase):
    def test_checked_in_source_manifest_and_patch_files_are_valid(self):
        specification, patches = dashboard.source_inputs()
        self.assertEqual(specification['patches'], [name for name, _ in patches])
        self.assertTrue(all(contents for _, contents in patches))


class DashboardFixture:
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.home = self.directory / 'home'
        self.home.mkdir()
        self.checkout = self.directory / 'checkout with spaces'
        self.checkout.mkdir()
        subprocess.run(['git', 'init', '--quiet', self.checkout], check=True)
        self.put(self.checkout / '.gitignore', 'node_modules/\npackages/client/dist/\n')
        self.put(self.checkout / 'package.json', json.dumps({
            'name': '@blackbelt-technology/pi-agent-dashboard', 'version': '0.11.0',
            'packageManager': 'pnpm@11.15.1',
            'pi': {'extensions': ['packages/extension/src/bridge.ts']},
        }))
        self.put(self.checkout / 'pnpm-lock.yaml', 'lockfileVersion: 9.0\n')
        self.put(self.checkout / 'pnpm-workspace.yaml', 'packages: ["packages/*"]\n')
        for component, directory in (('server', 'server'), ('shared', 'shared'),
                                     ('extension', 'extension'), ('web', 'client')):
            self.put(self.checkout / f'packages/{directory}/package.json', json.dumps({
                'name': f'@blackbelt-technology/pi-dashboard-{component}', 'version': '0.11.0',
            }))
        self.put(self.checkout / 'packages/extension/src/bridge.ts', '// bridge\n')
        self.put(self.checkout / 'packages/shared/src/test.ts', 'original\n')
        self.put(self.checkout / 'packages/server/src/cli.ts', '// cli\n')
        self.put(self.checkout / 'packages/server/bin/pi-dashboard.mjs',
                 'console.log(JSON.stringify({root:import.meta.url,args:process.argv.slice(2)}));\n')
        self.patch = self.directory / 'downstream.patch'
        self.original_patch = ('--- a/packages/shared/src/test.ts\n'
                               '+++ b/packages/shared/src/test.ts\n@@ -1 +1 @@\n-original\n+patched\n')
        self.patch.write_text(self.original_patch)
        self.manifest = self.directory / 'source.json'
        self.manifest.write_text(json.dumps({
            'repository': 'https://example.invalid/dashboard.git', 'revision': '1' * 40,
            'patches': [str(self.patch)],
        }))
        mock = patch.object(dashboard, 'SOURCE', self.manifest)
        mock.start()
        self.addCleanup(mock.stop)
        self.commands = []
        self.build_environments = []
        def build_command(args, *, cwd=None, env=None):
            self.commands.append((args, cwd))
            self.build_environments.append(env)
            self.assertNotEqual(self.checkout, cwd)
            if args[:2] == ['pnpm', 'install']:
                modules = cwd / 'node_modules/@blackbelt-technology'
                modules.mkdir(parents=True)
                for component, directory in (('server', 'server'), ('shared', 'shared'),
                                             ('extension', 'extension'), ('web', 'client')):
                    (modules / f'pi-dashboard-{component}').symlink_to(cwd / f'packages/{directory}')
            elif args == ['pnpm', 'run', 'build']:
                self.put(cwd / 'packages/client/dist/index.html', '<html>built</html>\n')
            else:
                self.fail(f'unexpected build command: {args}')
        self.build_command = build_command
        mock = patch.object(dashboard, 'run', side_effect=build_command)
        mock.start()
        self.addCleanup(mock.stop)

    def put(self, path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value)

    def build(self, checkout=True):
        return dashboard.build_source(self.checkout if checkout else None, self.home)


class DashboardSourceTests(DashboardFixture, unittest.TestCase):
    def test_install_prepare_and_explicit_build_receive_the_heap_limit(self):
        with patch.dict(os.environ, {'NODE_OPTIONS': '--no-warnings'}):
            self.build()
        self.assertEqual(2, len(self.build_environments))
        for environment in self.build_environments:
            self.assertIn('--max-old-space-size=4096', environment['NODE_OPTIONS'])
            self.assertIn('--no-warnings', environment['NODE_OPTIONS'])

    def test_setup_reports_disconnected_tailscale_without_a_traceback(self):
        from contextlib import redirect_stderr
        from io import StringIO
        diagnostics = StringIO()
        with patch.object(dashboard, 'setup', side_effect=RuntimeError('Connect Tailscale')), \
                patch.object(sys, 'argv', ['setup_dashboard.py']), redirect_stderr(diagnostics):
            self.assertEqual(1, dashboard.main())
        self.assertIn('Dashboard setup failed: Connect Tailscale', diagnostics.getvalue())
        self.assertNotIn('Traceback', diagnostics.getvalue())

    def test_checkout_dirty_and_untracked_source_is_copied_then_patched_before_build(self):
        subprocess.run(['git', '-C', self.checkout, 'add', 'packages/server/src/cli.ts'], check=True)
        self.put(self.checkout / 'packages/server/src/cli.ts', '// dirty tracked input\n')
        self.put(self.checkout / 'untracked source.txt', 'dirty input\n')
        self.put(self.checkout / 'node_modules/ignore', 'dependency cache')
        self.put(self.checkout / 'packages/client/dist/index.html', 'stale browser build')
        self.put(self.checkout / '.git/metadata', 'not source')
        self.put(self.checkout / 'out/source.ts', '// source, not a build output\n')
        source = self.build()
        self.assertNotEqual(source, self.checkout)
        self.assertEqual('// dirty tracked input\n', (source / 'packages/server/src/cli.ts').read_text())
        self.assertEqual('patched\n', (source / 'packages/shared/src/test.ts').read_text())
        self.assertEqual('original\n', (self.checkout / 'packages/shared/src/test.ts').read_text())
        self.assertEqual('dirty input\n', (source / 'untracked source.txt').read_text())
        self.assertFalse((source / 'node_modules/ignore').exists())
        self.assertFalse((source / '.git').exists())
        self.assertEqual('// source, not a build output\n', (source / 'out/source.ts').read_text())
        self.assertEqual('stale browser build', (self.checkout / 'packages/client/dist/index.html').read_text())
        self.assertEqual('<html>built</html>\n', (source / 'packages/client/dist/index.html').read_text())
        self.assertEqual([['pnpm', 'install', '--frozen-lockfile'], ['pnpm', 'run', 'build']],
                         [args for args, _ in self.commands])
        self.assertFalse((self.home / '.local/share/pi-dashboard/current').exists())
        receipt = json.loads((source / dashboard.STAMP).read_text())
        self.assertEqual(str(self.checkout), receipt['source']['checkout'])
        self.assertEqual(dashboard.digest(self.original_patch.encode()), receipt['patches'][0]['sha256'])

    def test_managed_pin_and_checkout_use_the_same_patches_and_build(self):
        def clone(entry, destination):
            self.assertEqual('1' * 40, entry['revision'])
            self.assertEqual('https://example.invalid/dashboard.git', entry['url'])
            shutil.copytree(self.checkout, destination)
        with patch.object(dashboard, 'clone', side_effect=clone) as acquire:
            source = self.build(checkout=False)
        acquire.assert_called_once()
        self.assertEqual('patched\n', (source / 'packages/shared/src/test.ts').read_text())
        self.assertEqual('1' * 40, json.loads((source / dashboard.STAMP).read_text())['source']['revision'])

    def test_source_patch_already_applied_or_conflicting_never_builds_or_activates(self):
        for contents in ('patched\n', 'conflict\n'):
            with self.subTest(contents=contents):
                self.put(self.checkout / 'packages/shared/src/test.ts', contents)
                with self.assertRaises(subprocess.CalledProcessError):
                    self.build()
                self.assertEqual(contents, (self.checkout / 'packages/shared/src/test.ts').read_text())
                self.assertEqual([], self.commands)
                self.assertFalse((self.home / '.local/share/pi-dashboard/current').exists())

    def test_changed_patches_rebuild_from_pristine_input_not_previous_patched_build(self):
        first = self.build()
        self.patch.write_text(self.original_patch.replace('+patched', '+second'))
        second = self.build()
        self.assertNotEqual(first, second)
        self.assertEqual('patched\n', (first / 'packages/shared/src/test.ts').read_text())
        self.assertEqual('second\n', (second / 'packages/shared/src/test.ts').read_text())

    def test_failed_build_preserves_active_source_and_real_state(self):
        active = self.home / '.local/share/pi-dashboard/current'
        active.parent.mkdir(parents=True)
        active.symlink_to(self.checkout)
        config = self.home / '.pi/dashboard/config.json'
        self.put(config, '{"pairedDevices":["mine"]}')
        with patch.object(dashboard, 'run', side_effect=subprocess.CalledProcessError(23, 'pnpm')):
            with self.assertRaises(subprocess.CalledProcessError):
                self.build()
        self.assertEqual(self.checkout, active.resolve())
        self.assertEqual('{"pairedDevices":["mine"]}', config.read_text())

    def test_missing_wrong_or_incomplete_checkout_is_not_replaced_with_upstream(self):
        for change in ('missing', 'identity', 'lockfile'):
            with self.subTest(change=change):
                if change == 'missing':
                    checkout = self.directory / 'missing'
                else:
                    checkout = self.checkout
                    if change == 'identity':
                        metadata = json.loads((checkout / 'package.json').read_text())
                        metadata['name'] = 'unrelated'
                        (checkout / 'package.json').write_text(json.dumps(metadata))
                    else:
                        metadata['name'] = '@blackbelt-technology/pi-agent-dashboard'
                        (checkout / 'package.json').write_text(json.dumps(metadata))
                        (checkout / 'pnpm-lock.yaml').unlink()
                with patch.object(dashboard, 'clone') as acquire:
                    with self.assertRaises((OSError, ValueError)):
                        dashboard.build_source(checkout, self.home)
                acquire.assert_not_called()
        self.assertEqual([], self.commands)

    def test_workspace_must_resolve_local_components_not_registry_copies(self):
        def registry(args, *, cwd=None, env=None):
            self.build_command(args, cwd=cwd, env=env)
            if args[:2] == ['pnpm', 'install']:
                link = cwd / 'node_modules/@blackbelt-technology/pi-dashboard-shared'
                link.unlink()
                link.mkdir()
                (link / 'package.json').write_text(json.dumps({'name':'@blackbelt-technology/pi-dashboard-shared'}))
        with patch.object(dashboard, 'run', side_effect=registry):
            with self.assertRaisesRegex(ValueError, 'workspace'):
                self.build()

    def test_multiple_patches_apply_in_manifest_order_and_missing_patch_fails(self):
        second = self.directory / 'second.patch'
        second.write_text(self.original_patch.replace('-original', '-patched').replace('+patched', '+last'))
        manifest = json.loads(self.manifest.read_text())
        manifest['patches'].append(str(second))
        self.manifest.write_text(json.dumps(manifest))
        source = self.build()
        self.assertEqual('last\n', (source / 'packages/shared/src/test.ts').read_text())
        second.unlink()
        with self.assertRaises(FileNotFoundError):
            self.build()

    def test_input_symlinks_cannot_make_patching_write_back_to_checkout(self):
        external = self.directory / 'outside-source.ts'
        external.write_text('original\n')
        source = self.checkout / 'packages/shared/src/test.ts'
        source.unlink()
        source.symlink_to(external)
        built = self.build()
        self.assertFalse((built / 'packages/shared/src/test.ts').is_symlink())
        self.assertEqual('patched\n', (built / 'packages/shared/src/test.ts').read_text())
        self.assertEqual('original\n', external.read_text())
        self.assertEqual(external, source.resolve())

    def test_managed_build_reuses_matching_pin_but_switches_back_from_checkout(self):
        def clone(entry, destination):
            shutil.copytree(self.checkout, destination)
        with patch.object(dashboard, 'clone', side_effect=clone) as acquire:
            first = self.build(checkout=False)
            dashboard.activate(first, self.home)
            self.assertEqual(first, self.build(checkout=False))
            self.assertEqual(1, acquire.call_count)
            checkout = self.build()
            dashboard.activate(checkout, self.home)
            restored = self.build(checkout=False)
            self.assertNotEqual(checkout, restored)
            self.assertEqual(2, acquire.call_count)
        self.assertEqual('patched\n', (restored / 'packages/shared/src/test.ts').read_text())
        # Merely building does not select it.
        self.assertEqual(checkout, (self.home / '.local/share/pi-dashboard/current').resolve())

    def test_advancing_pin_and_removing_merged_patch_needs_no_rebase_or_reverse_patch(self):
        first = self.build()
        dashboard.activate(first, self.home)
        manifest = json.loads(self.manifest.read_text())
        manifest.update(revision='2' * 40, patches=[])
        self.manifest.write_text(json.dumps(manifest))
        def clone(entry, destination):
            self.assertEqual('2' * 40, entry['revision'])
            shutil.copytree(self.checkout, destination)
            (destination / 'packages/shared/src/test.ts').write_text('merged upstream\n')
        with patch.object(dashboard, 'clone', side_effect=clone):
            built = self.build(checkout=False)
        self.assertEqual('merged upstream\n', (built / 'packages/shared/src/test.ts').read_text())
        self.assertEqual('patched\n', (first / 'packages/shared/src/test.ts').read_text())

    def test_damaged_active_build_is_replaced_without_editing_the_old_tree(self):
        def clone(entry, destination):
            shutil.copytree(self.checkout, destination)
        with patch.object(dashboard, 'clone', side_effect=clone):
            for damage in ('modified', 'missing-receipt', 'malformed-receipt', 'wrong-shape'):
                with self.subTest(damage=damage):
                    original = self.build(checkout=False)
                    dashboard.activate(original, self.home)
                    receipt = original / dashboard.STAMP
                    if damage == 'modified':
                        (original / 'packages/shared/src/test.ts').write_text('modified\n')
                    elif damage == 'missing-receipt':
                        receipt.unlink()
                    elif damage == 'malformed-receipt':
                        receipt.write_text('{broken')
                    else:
                        receipt.write_text('[]')
                    replacement = self.build(checkout=False)
                    self.assertNotEqual(original, replacement)
                    dashboard.validate_build(replacement)
                    self.assertEqual(original, (self.home / '.local/share/pi-dashboard/current').resolve())
                    if damage == 'modified':
                        self.assertEqual('modified\n', (original / 'packages/shared/src/test.ts').read_text())
                    dashboard.activate(replacement, self.home)

    def test_install_only_entrypoint_migrates_existing_bridge_but_does_not_enable_a_new_one(self):
        from contextlib import redirect_stdout
        from io import StringIO
        native_command = dashboard.command
        tools = {'node': shutil.which('node'), 'pnpm': '/unused-pnpm/bin/pnpm'}
        def command(*args, **kwargs):
            if args[:2] == ('mise', 'which'):
                return tools[args[2]]
            return native_command(*args, **kwargs)
        with patch.object(dashboard, 'command', side_effect=command), \
                patch.object(dashboard.Path, 'home', return_value=self.home), \
                patch.object(dashboard, 'tailscale_address', side_effect=AssertionError('must not configure')), \
                patch.dict(os.environ), \
                patch.object(sys, 'argv', ['setup_dashboard.py', '--checkout', str(self.checkout), '--install-only']):
            output = StringIO()
            with redirect_stdout(output):
                self.assertEqual(0, dashboard.main())
            self.assertIn('Stop Dashboard, start it again', output.getvalue())
            current = self.home / '.local/share/pi-dashboard/current'
            self.assertTrue(current.is_symlink())
            self.assertFalse((self.home / '.pi/agent/pi-dashboard').exists())
            self.assertFalse((self.home / '.pi/dashboard/config.json').exists())
            legacy = self.directory / 'old mise extension'
            self.put(legacy / 'src/bridge.ts', '// old bridge\n')
            bridge = self.home / '.pi/agent/pi-dashboard'
            bridge.parent.mkdir(parents=True)
            bridge.symlink_to(legacy)
            self.assertEqual(0, dashboard.main())
            self.assertEqual(current, bridge.readlink())
            self.assertEqual(current.resolve(), bridge.resolve())
            self.assertEqual('// old bridge\n', (legacy / 'src/bridge.ts').read_text())
            self.assertFalse((self.home / '.pi/dashboard/config.json').exists())


class DashboardPolicyTests(DashboardFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.core = self.build()
        self.settings_source = self.directory / 'tracked-settings.json'
        self.settings_source.write_text('{"packages":[{"source":"./pi-dashboard","skills":[]}]}')
        self.put(self.home / '.pi/agent/placeholder', '')
        (self.home / '.pi/agent/settings.json').symlink_to(self.settings_source)
        self.policy = self.directory / 'policy.json'
        self.policy.write_bytes((ROOT / 'config/pi-dashboard.json').read_bytes())
        for name, value in (('POLICY', self.policy), ('tailscale_address', lambda:'100.101.102.103')):
            mock = patch.object(dashboard, name, value)
            mock.start()
            self.addCleanup(mock.stop)
        mock = patch.object(dashboard.shutil, 'which', return_value='/bin/tmux')
        mock.start()
        self.addCleanup(mock.stop)

    def configure(self):
        dashboard.configure(self.core, self.home)

    def test_launcher_and_bridge_select_one_build_and_forward_literal_arguments(self):
        self.configure()
        current = self.home / '.local/share/pi-dashboard/current'
        bridge = self.home / '.pi/agent/pi-dashboard'
        launcher = self.home / '.local/bin/pi-dashboard'
        self.assertEqual(self.core, current.resolve())
        self.assertEqual(current, bridge.readlink())
        self.assertEqual(self.core, bridge.resolve())
        self.assertEqual(ROOT / 'bin/pi-dashboard', launcher.resolve())
        result = subprocess.run([str(launcher), '--literal', 'an argument with spaces', '$(not-shell)'],
                                env=os.environ | {'HOME': str(self.home)},
                                capture_output=True, text=True)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        value = json.loads(result.stdout)
        self.assertIn(str(self.core), value['root'])
        self.assertEqual(['--literal', 'an argument with spaces', '$(not-shell)'], value['args'])
        second = self.build()
        dashboard.configure(second, self.home)
        self.assertEqual(second, bridge.resolve())
        result = subprocess.run([str(launcher)], env=os.environ | {'HOME': str(self.home)},
                                capture_output=True, text=True, check=True)
        self.assertIn(str(second), json.loads(result.stdout)['root'])
        self.assertTrue(self.core.exists(), 'retain the old build for already-running processes')

    def test_changed_or_added_runtime_files_fail_integrity_without_repointing_active_build(self):
        self.configure()
        current = self.home / '.local/share/pi-dashboard/current'
        before = current.readlink()
        for filename in ('packages/shared/src/test.ts', 'packages/shared/src/new.ts'):
            with self.subTest(filename=filename):
                target = self.core / filename
                previous = target.read_bytes() if target.exists() else None
                target.write_text('modified\n')
                with self.assertRaisesRegex(ValueError, 'not intact'):
                    self.configure()
                self.assertEqual(before, current.readlink())
                if previous is None:
                    target.unlink()
                else:
                    target.write_bytes(previous)

    def test_non_symlink_launcher_or_active_directory_is_not_overwritten(self):
        for relative in ('.local/bin/pi-dashboard', '.local/share/pi-dashboard/current'):
            with self.subTest(relative=relative):
                target = self.home / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text('user owned')
                with self.assertRaisesRegex(ValueError, 'Refusing to replace'):
                    self.configure()
                self.assertEqual('user owned', target.read_text())
                self.assertFalse((self.home / '.pi/dashboard/config.json').exists())
                target.unlink()

    def test_tracked_policy_changes_are_authoritative_and_preserve_local_state_on_repeat(self):
        path = self.home / '.pi/dashboard/config.json'
        self.put(path, json.dumps({
            'hmacSecret': 'local-only-fixture', 'pairedDevices': ['fixture-device'],
            'allowedHosts': ['local.fixture.invalid'], 'trustedNetworks': ['192.0.2.0/24'],
            'theme': 'mine', 'agentPathGate': {'enabled': True, 'timeoutSeconds': 99},
            'network': {'localPreference': 'keep'},
        }))
        policy = json.loads(self.policy.read_text())
        policy.update(autoShutdown=True, listenOnLoopback=False)
        policy['allowedHosts'] = ['tracked.fixture.invalid']
        policy['trustedNetworks'].append('198.51.100.0/24')
        source = json.dumps(policy)
        self.policy.write_text(source)
        settings_before = self.settings_source.read_bytes()
        self.configure()
        self.configure()
        value = json.loads(path.read_text())
        self.assertTrue(value['autoShutdown'])
        self.assertFalse(value['listenOnLoopback'])
        self.assertEqual(['local.fixture.invalid', 'tracked.fixture.invalid'], value['allowedHosts'])
        self.assertEqual(['192.0.2.0/24', *policy['trustedNetworks']], value['trustedNetworks'])
        self.assertEqual('local-only-fixture', value['hmacSecret'])
        self.assertEqual(['fixture-device'], value['pairedDevices'])
        self.assertEqual('mine', value['theme'])
        self.assertEqual(99, value['agentPathGate']['timeoutSeconds'])
        self.assertEqual('keep', value['network']['localPreference'])
        for field, expected in policy.items():
            if isinstance(expected, dict):
                self.assertEqual(expected, {key: value[field][key] for key in expected})
            elif not isinstance(expected, list):
                self.assertEqual(expected, value[field])
        self.assertEqual(source, self.policy.read_text())
        self.assertEqual(settings_before, self.settings_source.read_bytes())
        self.assertFalse(path.is_symlink())

    def test_invalid_or_missing_source_policy_cannot_publish_runtime_state(self):
        self.configure()
        path = self.home / '.pi/dashboard/config.json'
        before = path.read_bytes()
        cases = [[], {'hmacSecret': 'must-remain-local'}, {'bindHost': '127.0.0.1'},
                 {'agentPathGate': {'enabled': 0}}, {'network': {'unmanaged': False}},
                 {'allowedHosts': 'not-a-list'}, {'maxConcurrentSubagents': True},
                 {'maxConcurrentSubagents': -1}, {'spawnRegisterTimeoutMs': True},
                 {'spawnRegisterTimeoutMs': 4999}, {'spawnRegisterTimeoutMs': 120001}]
        for policy in cases:
            with self.subTest(policy=policy):
                self.policy.write_text(json.dumps(policy))
                with self.assertRaises(ValueError):
                    self.configure()
                self.assertEqual(before, path.read_bytes())
        self.policy.write_text('{broken')
        with self.assertRaises(ValueError):
            self.configure()
        self.assertEqual(before, path.read_bytes())
        self.policy.unlink()
        with self.assertRaises(FileNotFoundError):
            self.configure()
        self.assertEqual(before, path.read_bytes())

    def test_configuration_preserves_pairing_other_overrides_and_settings_symlink(self):
        settings = self.directory / 'tracked-settings.json'
        settings.write_text('{"packages":["other", {"source":"./pi-dashboard","skills":[]}]}\n')
        agent = self.home / '.pi/agent'
        agent.mkdir(parents=True, exist_ok=True)
        (agent / 'settings.json').unlink()
        (agent / 'settings.json').symlink_to(settings)
        runtime = self.home / '.pi/dashboard'
        self.put(runtime / 'config.json', json.dumps({
            'pairedDevices': ['device'], 'hmacSecret': 'local-only', 'autoStart': True,
            'theme': 'mine', 'tunnel': {'provider': 'existing', 'enabled': True},
        }))
        self.put(runtime / 'tool-overrides.json', json.dumps({
            'version': 1, 'overrides': {'git': {'path': '/native/git'}, 'pi': {'extra': True}},
        }))
        # Migrate an existing core link left by the original setup, without
        # changing the declarative settings source or its symlink.
        (agent / 'pi-dashboard').symlink_to(self.core, target_is_directory=True)
        self.configure()
        self.configure()
        config = json.loads((runtime / 'config.json').read_text())
        self.assertEqual(['device'], config['pairedDevices'])
        self.assertEqual('local-only', config['hmacSecret'])
        self.assertEqual('mine', config['theme'])
        self.assertTrue(config['autoStart'])
        self.assertEqual('tmux', config['spawnStrategy'])
        self.assertFalse(config['autoShutdown'])
        self.assertFalse(config['registerAskUserTool'])
        self.assertFalse(config['agentPathGate']['enabled'])
        self.assertFalse(config['tunnel']['enabled'])
        self.assertEqual('existing', config['tunnel']['provider'])
        self.assertEqual('pair', config['network']['trustMode'])
        self.assertEqual('100.101.102.103', config['bindHost'])
        self.assertTrue(config['pairing']['acceptLanRequests'])
        self.assertEqual(['100.64.0.0/10'], config['trustedNetworks'])
        overrides = json.loads((runtime / 'tool-overrides.json').read_text())
        self.assertEqual({'path': '/native/git'}, overrides['overrides']['git'])
        self.assertEqual(str(ROOT / 'bin/pi'), overrides['overrides']['pi']['path'])
        self.assertTrue(overrides['overrides']['pi']['extra'])
        self.assertEqual(self.home / '.local/share/pi-dashboard/current',
                         (agent / 'pi-dashboard').readlink())
        self.assertEqual(self.core, (agent / 'pi-dashboard').resolve())
        self.assertTrue((agent / 'settings.json').is_symlink())
        self.assertEqual('{"packages":["other", {"source":"./pi-dashboard","skills":[]}]}\n', settings.read_text())
        self.assertEqual(0o600, (runtime / 'config.json').stat().st_mode & 0o777)

    def test_machine_tailnet_choice_replaces_old_bind_preserving_existing_pairing_and_networks(self):
        config = self.home / '.pi/dashboard/config.json'
        self.put(config, json.dumps({'bindHost': '0.0.0.0', 'pairing': {'identity': 'preserved'},
                                     'trustedNetworks': ['existing.example']}))
        self.configure()
        self.configure()
        value = json.loads(config.read_text())
        self.assertEqual('100.101.102.103', value['bindHost'])
        self.assertEqual('preserved', value['pairing']['identity'])
        self.assertEqual(['existing.example', '100.64.0.0/10'], value['trustedNetworks'])
        before = config.read_bytes()
        for invalid in ('not-an-address', '127.0.0.1', '0.0.0.0', '192.168.1.1', '::1'):
            with self.subTest(address=invalid), self.assertRaises(ValueError):
                dashboard.configure(self.core, self.home, invalid)
            self.assertEqual(before, config.read_bytes())
        with patch.object(dashboard, 'tailscale_address', side_effect=RuntimeError('offline')):
            with self.assertRaisesRegex(RuntimeError, 'offline'):
                self.configure()
        self.assertEqual(before, config.read_bytes())

    def test_malformed_json_wrong_shapes_and_symlinked_runtime_files_leave_state_intact(self):
        runtime = self.home / '.pi/dashboard'
        for name, bad in [('config.json', '{malformed'), ('config.json', '[]'),
                          ('config.json', '{"tunnel":false}'),
                          ('tool-overrides.json', '{bad'),
                          ('tool-overrides.json', '{"version":2}'),
                          ('tool-overrides.json', '{"overrides":[]}')]:
            with self.subTest(name=name, bad=bad):
                shutil.rmtree(runtime, ignore_errors=True)
                self.put(runtime / name, bad)
                with self.assertRaises(ValueError):
                    self.configure()
                self.assertEqual(bad, (runtime / name).read_text())
                self.assertFalse((self.home / '.pi/agent/pi-dashboard').exists())
        shutil.rmtree(runtime)
        runtime.mkdir()
        original = self.directory / 'symlink-target'
        original.write_text('{}')
        (runtime / 'config.json').symlink_to(original)
        with self.assertRaises(ValueError):
            self.configure()
        self.assertEqual('{}', original.read_text())

    def test_malformed_symlinked_pi_settings_fail_without_replacing_the_symlink(self):
        settings = self.directory / 'tracked-settings.json'
        settings.write_text('{malformed')
        link = self.home / '.pi/agent/settings.json'
        link.parent.mkdir(parents=True, exist_ok=True)
        link.unlink()
        link.symlink_to(settings)
        with self.assertRaises(ValueError):
            self.configure()
        self.assertTrue(link.is_symlink())
        self.assertEqual('{malformed', settings.read_text())
        self.assertFalse((self.home / '.pi/dashboard/config.json').exists())
        self.assertFalse((self.home / '.pi/agent/pi-dashboard').exists())

    def test_old_symlinked_settings_without_registration_fail_before_any_publication(self):
        original = '{"packages":["other"],"theme":"unchanged"}\n'
        self.settings_source.write_text(original)
        link = self.home / '.pi/agent/settings.json'
        with self.assertRaisesRegex(ValueError, 'setup dotfiles'):
            self.configure()
        self.assertTrue(link.is_symlink())
        self.assertEqual(self.settings_source, link.resolve())
        self.assertEqual(original, self.settings_source.read_text())
        self.assertFalse((self.home / '.pi/dashboard/config.json').exists())
        self.assertFalse((self.home / '.pi/agent/pi-dashboard').exists())
        for declaration in ({'source': './pi-dashboard', 'autoload': False},
                            {'source': './pi-dashboard', 'extensions': []}):
            self.settings_source.write_text(json.dumps({'packages': [declaration]}))
            with self.subTest(declaration=declaration), self.assertRaisesRegex(ValueError, 'setup dotfiles'):
                self.configure()
            self.assertTrue(link.is_symlink())
            self.assertFalse((self.home / '.pi/dashboard/config.json').exists())
        link.unlink()
        with self.assertRaisesRegex(ValueError, 'setup dotfiles'):
            self.configure()
        self.assertFalse(link.exists())
        self.assertFalse((self.home / '.pi/dashboard/config.json').exists())

    def test_stale_patch_and_missing_tmux_do_not_enable_bridge(self):
        self.patch.write_text(self.patch.read_text() + '\n# changed\n')
        with self.assertRaisesRegex(ValueError, 'rebuild'):
            self.configure()
        self.patch.write_text(self.original_patch)
        with patch.object(dashboard.shutil, 'which', return_value=None):
            with self.assertRaisesRegex(ValueError, 'requires tmux'):
                self.configure()
        self.assertFalse((self.home / '.pi/agent/pi-dashboard').exists())

    def test_existing_real_package_directory_is_not_replaced(self):
        (self.home / '.pi/agent/pi-dashboard').mkdir(parents=True)
        with self.assertRaisesRegex(ValueError, 'Refusing to replace'):
            self.configure()
        self.assertFalse((self.home / '.pi/dashboard/config.json').exists())


class DashboardDiscoveryTests(unittest.TestCase):
    def test_native_tailscale_running_online_state_and_actual_ipv4_are_required(self):
        online = json.dumps({'BackendState': 'Running', 'Self': {'Online': True}})
        with patch.object(dashboard, 'command', side_effect=[online, '100.101.102.103\n']) as command:
            self.assertEqual('100.101.102.103', dashboard.tailscale_address())
        self.assertEqual([('tailscale', 'status', '--json'), ('tailscale', 'ip', '-4')],
                         [call.args for call in command.call_args_list])
        for response in [json.dumps({'BackendState': 'Stopped'}),
                         json.dumps({'BackendState': 'Running', 'Self': {'Online': False}}), '{broken']:
            with self.subTest(response=response), patch.object(dashboard, 'command', return_value=response):
                with self.assertRaisesRegex(RuntimeError, 'will not fall back'):
                    dashboard.tailscale_address()
        for invalid in ('127.0.0.1', '0.0.0.0', '100.101.102.103\n100.101.102.104', '::1'):
            with self.subTest(address=invalid), patch.object(dashboard, 'command', side_effect=[online, invalid]):
                with self.assertRaisesRegex(RuntimeError, 'native Tailscale'):
                    dashboard.tailscale_address()
        with patch.object(dashboard, 'command', side_effect=FileNotFoundError('tailscale')):
            with self.assertRaisesRegex(RuntimeError, 'native Tailscale') as failure:
                dashboard.tailscale_address()
            self.assertIn('rerun ./setup services', str(failure.exception))



if __name__ == '__main__':
    unittest.main()
