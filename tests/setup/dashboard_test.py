"""Dashboard's native installation hook and narrowly owned runtime state."""

import gzip
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import tomllib
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('dashboard_setup', ROOT / 'libexec/setup/setup_dashboard.py')
dashboard = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(dashboard)


@unittest.skipUnless(shutil.which('node') and shutil.which('patch'), 'requires Node and native patch')
class DashboardTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.home = self.directory / 'home'
        self.home.mkdir()
        self.settings_source = self.directory / 'tracked-settings.json'
        self.settings_source.write_text('{"packages":[{"source":"./pi-dashboard","skills":[]}]}')
        settings = self.home / '.pi/agent/settings.json'
        settings.parent.mkdir(parents=True)
        settings.symlink_to(self.settings_source)
        self.install = self.directory / 'mise install with spaces'
        self.core = self.install / 'native layout/core'
        self.core.mkdir(parents=True)
        self.version = tomllib.loads((ROOT / 'config/mise.toml').read_text())['tools'][dashboard.TOOL]['version']
        self.policy = self.directory / 'policy.json'
        self.policy.write_bytes((ROOT / 'config/pi-dashboard.json').read_bytes())
        policy_mock = patch.object(dashboard, 'POLICY', self.policy)
        policy_mock.start()
        self.addCleanup(policy_mock.stop)
        pin = patch.object(dashboard, 'pin', return_value=self.version)
        pin.start()
        self.addCleanup(pin.stop)
        self.metadata(self.core, dashboard.PACKAGE, pi={'extensions': ['packages/extension/src/bridge.ts']})
        self.components = {}
        for name in ('server', 'shared', 'extension', 'web'):
            root = self.core / 'node_modules/@blackbelt-technology' / f'pi-dashboard-{name}'
            root.mkdir(parents=True)
            metadata = {'pi': {'extensions': ['src/bridge.ts']}} if name == 'extension' else {}
            self.metadata(root, f'@blackbelt-technology/pi-dashboard-{name}', **metadata)
            self.components[name] = [root]
            if name != 'web':
                self.put(self.core / f'packages/{name}/src/test.ts', 'original\n')
                self.put(root / 'src/test.ts', 'original\n')
        self.put(self.core / 'packages/extension/src/bridge.ts', '// bridge\n')
        self.put(self.components['extension'][0] / 'src/bridge.ts', '// bridge\n')
        self.put(self.components['web'][0] / 'dist/index.html', '<html></html>\n')
        self.put(self.components['web'][0] / 'dist/assets/app.js', 'original\n')
        self.gzip = self.components['web'][0] / 'dist/assets/app.js.gz'
        self.gzip.write_bytes(gzip.compress(b'original\n', mtime=0))
        self.patch = self.directory / 'reviewed.patch'
        self.write_patch('patched')
        self.env = patch.dict(os.environ, {
            'MISE_TOOL_VERSION': self.version, 'MISE_TOOL_INSTALL_PATH': str(self.install),
        })
        self.env.start()
        self.addCleanup(self.env.stop)
        for name, replacement in (('installed_core', lambda install: self.core),
                                  ('patch_file', lambda version: self.patch)):
            mock = patch.object(dashboard, name, replacement)
            mock.start()
            self.addCleanup(mock.stop)
        address = patch.object(dashboard, 'tailscale_address', return_value='100.101.102.103')
        address.start()
        self.addCleanup(address.stop)
        tmux = patch.object(dashboard.shutil, 'which', return_value='/bin/tmux')
        tmux.start()
        self.addCleanup(tmux.stop)

    def metadata(self, root, name, **extra):
        self.put(root / 'package.json', json.dumps({'name': name, 'version': self.version, **extra}))

    def put(self, path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value)

    def write_patch(self, replacement, *, web=True):
        paths = ['packages/shared/src/test.ts']
        if web:
            paths.append('packages/client/dist/assets/app.js')
        self.patch.write_text(''.join(
            f'--- a/{path}\n+++ b/{path}\n@@ -1 +1 @@\n-original\n+{replacement}\n'
            for path in paths))

    def configure(self):
        dashboard.configure(self.core, self.install, self.home)

    def test_node_resolves_actual_split_roots_not_a_guessed_store_layout(self):
        self.assertEqual(self.components, dashboard.component_roots(self.core))
        extension = dashboard.command('node', str(ROOT / 'libexec/setup/setup_dashboard_roots.mjs'),
                                      str(self.core), '--extension')
        self.assertEqual(str(self.components['extension'][0]), extension)

    def test_runtime_extension_public_manifest_is_required_before_publication(self):
        extension = self.components['extension'][0]
        self.metadata(extension, '@blackbelt-technology/pi-dashboard-extension')
        with self.assertRaisesRegex(ValueError, 'runtime extension'):
            dashboard.postinstall()
        self.assertFalse((self.install / dashboard.STAMP).exists())
        self.assertFalse((self.home / '.pi/agent/pi-dashboard').exists())

    def test_patch_updates_core_split_and_precompressed_web_without_store_mutation(self):
        original = self.directory / 'pnpm-store-original'
        original.write_text('original\n')
        target = self.components['shared'][0] / 'src/test.ts'
        target.unlink()
        os.link(original, target)
        dashboard.postinstall()
        self.assertEqual('patched\n', (self.core / 'packages/shared/src/test.ts').read_text())
        self.assertEqual('patched\n', target.read_text())
        self.assertEqual('original\n', original.read_text())
        self.assertEqual(b'patched\n', gzip.decompress(self.gzip.read_bytes()))
        alias = self.install / dashboard.EXTENSION_ALIAS
        self.assertTrue(alias.is_symlink())
        self.assertEqual(self.components['extension'][0], alias.resolve())
        before = target.stat().st_mtime_ns
        alias.unlink()
        dashboard.postinstall()
        self.assertEqual(before, target.stat().st_mtime_ns)
        self.assertEqual(self.components['extension'][0], alias.resolve())

    def test_changed_patch_reverses_previous_patch_and_restores_removed_hunks(self):
        dashboard.postinstall()
        self.write_patch('second', web=False)
        dashboard.postinstall()
        self.assertEqual('second\n', (self.core / 'packages/shared/src/test.ts').read_text())
        self.assertEqual('original\n', (self.components['web'][0] / 'dist/assets/app.js').read_text())
        self.assertEqual(b'original\n', gzip.decompress(self.gzip.read_bytes()))
        dashboard.postinstall()

    def test_receipt_records_exact_applied_patch_snapshot_if_source_changes_during_hook(self):
        selected = self.patch.read_bytes()
        resolver = dashboard.component_roots

        def regenerate_patch(core):
            self.write_patch('regenerated')
            return resolver(core)

        with patch.object(dashboard, 'component_roots', side_effect=regenerate_patch):
            dashboard.postinstall()
        receipt = json.loads((self.install / dashboard.STAMP).read_text())
        self.assertEqual(dashboard.digest(selected), receipt['patch_sha256'])
        self.assertEqual('patched\n', (self.core / 'packages/shared/src/test.ts').read_text())
        with self.assertRaisesRegex(ValueError, 'reinstall'):
            self.configure()
        dashboard.postinstall()
        self.assertEqual('regenerated\n', (self.core / 'packages/shared/src/test.ts').read_text())

    def test_new_native_build_assets_get_gzip_and_are_removed_when_patch_no_longer_adds_them(self):
        content = 'a' * 1100 + '\n'
        self.patch.write_text(self.patch.read_text() +
            '--- /dev/null\n+++ b/packages/client/dist/assets/new.js\n@@ -0,0 +1 @@\n+' + content)
        dashboard.postinstall()
        asset = self.components['web'][0] / 'dist/assets/new.js'
        compressed = Path(str(asset) + '.gz')
        self.assertEqual(content.encode(), gzip.decompress(compressed.read_bytes()))
        self.write_patch('second')
        dashboard.postinstall()
        self.assertFalse(asset.exists())
        self.assertFalse(compressed.exists())

    def test_wrong_version_missing_patch_and_failed_hunk_do_not_change_install(self):
        source = self.core / 'packages/shared/src/test.ts'
        with patch.dict(os.environ, MISE_TOOL_VERSION='99.0.0'):
            with self.assertRaises(ValueError):
                dashboard.postinstall()
        self.patch.unlink()
        with self.assertRaises(FileNotFoundError):
            dashboard.postinstall()
        self.write_patch('patched')
        self.patch.write_text(self.patch.read_text().replace('-original', '-nonmatching'))
        with self.assertRaises(subprocess.CalledProcessError):
            dashboard.postinstall()
        self.assertEqual('original\n', source.read_text())
        self.assertFalse((self.install / dashboard.STAMP).exists())
        self.assertFalse((self.home / '.pi/dashboard').exists())
        self.assertFalse((self.home / '.pi/agent/pi-dashboard').exists())

    def test_split_version_mismatch_and_source_mismatch_fail_before_any_publication(self):
        split = self.components['shared'][0]
        self.put(split / 'package.json', json.dumps({'name': '@blackbelt-technology/pi-dashboard-shared', 'version': '99'}))
        with self.assertRaises(ValueError):
            dashboard.postinstall()
        self.metadata(split, '@blackbelt-technology/pi-dashboard-shared')
        self.put(split / 'src/test.ts', 'different\n')
        with self.assertRaises(ValueError):
            dashboard.postinstall()
        self.assertEqual('original\n', (self.core / 'packages/shared/src/test.ts').read_text())

    def test_installed_source_drift_is_not_silently_overwritten(self):
        dashboard.postinstall()
        self.put(self.core / 'packages/shared/src/test.ts', 'user change\n')
        with self.assertRaisesRegex(ValueError, 'drifted'):
            dashboard.postinstall()
        with self.assertRaisesRegex(ValueError, 'not intact'):
            self.configure()

    def test_tracked_policy_changes_are_authoritative_and_preserve_local_state_on_repeat(self):
        dashboard.postinstall()
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
        dashboard.postinstall()
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
        dashboard.postinstall()
        (self.install / dashboard.EXTENSION_ALIAS).unlink()
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
        self.assertEqual(self.install / dashboard.EXTENSION_ALIAS,
                         (agent / 'pi-dashboard').readlink())
        self.assertEqual(self.components['extension'][0], (agent / 'pi-dashboard').resolve())
        self.assertTrue((agent / 'settings.json').is_symlink())
        self.assertEqual('{"packages":["other", {"source":"./pi-dashboard","skills":[]}]}\n', settings.read_text())
        self.assertEqual(0o600, (runtime / 'config.json').stat().st_mode & 0o777)

    def test_machine_tailnet_choice_replaces_old_bind_preserving_existing_pairing_and_networks(self):
        dashboard.postinstall()
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
                dashboard.configure(self.core, self.install, self.home, invalid)
            self.assertEqual(before, config.read_bytes())
        with patch.object(dashboard, 'tailscale_address', side_effect=RuntimeError('offline')):
            with self.assertRaisesRegex(RuntimeError, 'offline'):
                self.configure()
        self.assertEqual(before, config.read_bytes())

    def test_malformed_json_wrong_shapes_and_symlinked_runtime_files_leave_state_intact(self):
        dashboard.postinstall()
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
        dashboard.postinstall()
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
        dashboard.postinstall()
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
        dashboard.postinstall()
        self.write_patch('new patch')
        with self.assertRaisesRegex(ValueError, 'reinstall'):
            self.configure()
        self.write_patch('patched')
        with patch.object(dashboard.shutil, 'which', return_value=None):
            with self.assertRaisesRegex(ValueError, 'requires tmux'):
                self.configure()
        self.assertFalse((self.home / '.pi/agent/pi-dashboard').exists())

    def test_existing_real_package_directory_is_not_replaced(self):
        dashboard.postinstall()
        (self.home / '.pi/agent/pi-dashboard').mkdir(parents=True)
        with self.assertRaisesRegex(ValueError, 'Refusing to replace'):
            self.configure()
        self.assertFalse((self.home / '.pi/dashboard/config.json').exists())

    def test_setup_resolves_node_and_pnpm_through_mise_without_requiring_shell_activation(self):
        with patch.object(dashboard, 'command', side_effect=['', str(self.install), '/native/node/bin/node',
                                                           '/native/pnpm/pnpm']) as command, \
                patch.object(dashboard, 'configure') as configure:
            dashboard.setup()
        self.assertEqual(str(ROOT), command.call_args_list[0].kwargs['env']['DOTFILES_DASHBOARD_ROOT'])
        self.assertEqual(['/native/node/bin', '/native/pnpm'], os.environ['PATH'].split(os.pathsep)[:2])
        self.assertEqual(('mise', 'which', 'node'), command.call_args_list[2].args)
        self.assertEqual(('mise', 'which', 'pnpm'), command.call_args_list[3].args)
        configure.assert_called_once_with(self.core, self.install, Path.home())

    def test_setup_never_mutates_package_source_outside_mise_install_hook(self):
        with patch.object(dashboard, 'command', side_effect=subprocess.CalledProcessError(1, 'mise')) as command:
            with self.assertRaises(subprocess.CalledProcessError):
                dashboard.setup()
        command.assert_called_once()
        self.assertEqual(('mise', 'install', '--yes', dashboard.TOOL), command.call_args.args)
        self.assertEqual(str(ROOT), command.call_args.kwargs['env']['DOTFILES_DASHBOARD_ROOT'])
        self.assertFalse((self.home / '.pi/dashboard').exists())
        self.assertFalse((self.home / '.pi/agent/pi-dashboard').exists())


class DashboardDiscoveryTests(unittest.TestCase):
    def test_pin_uses_native_mise_parser_without_requiring_global_python_tomllib(self):
        with patch.object(dashboard, 'command', return_value='0.11.0') as command:
            self.assertEqual('0.11.0', dashboard.pin())
        command.assert_called_once_with('mise', 'config', 'get', '--file',
                                        str(ROOT / 'config/mise.toml'),
                                        'tools.npm:@blackbelt-technology/pi-agent-dashboard.version')

    def test_pin_rejects_nonexact_or_invalid_release_values(self):
        for value in ('', 'latest', '^0.11.0', '0.11', 'false', '../0.11.0',
                      '["0.11.0"]', 'version = "0.11.0"'):
            with self.subTest(value=value), patch.object(dashboard, 'command', return_value=value):
                with self.assertRaisesRegex(ValueError, 'exact X.Y.Z release'):
                    dashboard.pin()

    @unittest.skipUnless(shutil.which('mise'), 'requires native mise')
    def test_native_mise_reads_current_authoritative_pin_and_rejects_invalid_or_missing_pins(self):
        expected = tomllib.loads((ROOT / 'config/mise.toml').read_text())['tools'][dashboard.TOOL]['version']
        self.assertEqual(expected, dashboard.pin())
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = root / 'config/mise.toml'
            config.parent.mkdir()
            cases = [
                ('version = "latest"', ValueError),
                ('version = "^0.11.0"', ValueError),
                ('version = "../0.11.0"', ValueError),
                ('version = 0.11', ValueError),
                ('version = ["0.11.0"]', ValueError),
                ('depends = ["node"]', subprocess.CalledProcessError),
            ]
            with patch.object(dashboard, 'ROOT', root):
                for fields, error in cases:
                    with self.subTest(fields=fields):
                        config.write_text(f'[tools]\n"{dashboard.TOOL}" = {{ {fields} }}\n')
                        with self.assertRaises(error):
                            dashboard.pin()
                config.write_text('[tools]\nnode = "lts"\n')
                with self.assertRaises(subprocess.CalledProcessError):
                    dashboard.pin()
                config.write_text('[tools\n')
                with self.assertRaises(subprocess.CalledProcessError):
                    dashboard.pin()

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

    def test_pnpm_layout_is_native_and_cannot_escape_owning_installation(self):
        with tempfile.TemporaryDirectory() as temporary:
            install = Path(temporary)
            core = install / 'arbitrary/native-layout/core'
            core.mkdir(parents=True)
            data = [{'dependencies': {dashboard.PACKAGE: {'path': str(core)}}}]
            with patch.object(dashboard, 'command', return_value=json.dumps(data)) as command:
                self.assertEqual(core, dashboard.installed_core(install))
            self.assertEqual(('pnpm', 'list', '--global', '--depth=0', '--json'), command.call_args.args)
            self.assertEqual(str(install), command.call_args.kwargs['env']['PNPM_CONFIG_GLOBAL_DIR'])
            data[0]['dependencies'][dashboard.PACKAGE]['path'] = str(install.parent)
            with patch.object(dashboard, 'command', return_value=json.dumps(data)):
                with self.assertRaisesRegex(ValueError, 'outside'):
                    dashboard.installed_core(install)


if __name__ == '__main__':
    unittest.main()
