"""Exercise setup with disposable vaults and native service configuration."""

import importlib.util
import json
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / 'libexec/setup/setup_obsidian_sync.py'
spec = importlib.util.spec_from_file_location('obsidian_setup', SCRIPT)
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)


class ObsidianSyncTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.home = Path(self.temporary.name)
        self.bin = self.home / 'bin'
        self.bin.mkdir()
        self.vault = self.home / 'notes with spaces $ and %'
        self.config = self.vault / '.obsidian/core-plugins.json'
        self.config.parent.mkdir(parents=True)
        self.config.write_text('["sync", "daily-notes", "templates"]')
        self.record = {'id': 'vault-id', 'path': str(self.vault)}
        self.log = self.home / 'commands.jsonl'
        self.env = {**os.environ, 'HOME': str(self.home),
                    'PATH': str(self.bin) + ':' + os.environ['PATH']}
        self.write_command('mise', '''
import os
import sys
from pathlib import Path
if sys.argv[1] == 'which':
    print(Path.home() / 'bin' / sys.argv[2])
''')
        self.write_command('ob', '''
import json
import os
from pathlib import Path
import sys
home = Path.home()
args = sys.argv[1:]
with (home / 'commands.jsonl').open('a') as file:
    file.write(json.dumps(args) + '\\n')
if (home / 'fail-ob').exists():
    sys.exit(1)
vault = {'id': 'vault-id', 'path': str(home / 'notes with spaces $ and %')}
if args[0] == 'sync-list-local':
    vaults = json.loads((home / 'vaults.json').read_text()) if (home / 'vaults.json').exists() else [vault]
    print(json.dumps({'vaults': [] if (home / 'empty').exists() else vaults}))
elif args[0] == 'login':
    (home / 'gui-running').touch()
elif args[0] == 'sync-setup':
    (home / 'empty').unlink(missing_ok=True)
elif args[0] == 'sync-status' and '--json' in args:
    print(json.dumps({'configDir': '.obsidian', 'configs': ['core-plugin', 'appearance']}))
''')
        self.write_command('pgrep', 'import sys\nsys.exit(1)\n')
        self.write_command('flatpak', 'import sys\nsys.exit(1)\n')
        self.write_command('systemctl', '''
import json
from pathlib import Path
import sys
with (Path.home() / 'commands.jsonl').open('a') as file:
    file.write(json.dumps(['systemctl', *sys.argv[1:]]) + '\\n')
''')

    def write_command(self, name, body):
        path = self.bin / name
        path.write_text('#!' + sys.executable + '\n' + body)
        path.chmod(0o755)

    def run_setup(self):
        return subprocess.run([sys.executable, str(SCRIPT)], env=self.env,
                              text=True, capture_output=True)

    def calls(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()]

    def test_installs_and_reuses_vault_without_login_or_duplicate_sync(self):
        first = self.run_setup()
        second = self.run_setup()
        self.assertEqual(0, first.returncode, first.stderr)
        self.assertEqual(0, second.returncode, second.stderr)
        self.assertEqual(['daily-notes', 'templates'], json.loads(self.config.read_text()))
        units = list((self.home / '.config/systemd/user').glob('obsidian-sync-*.service'))
        self.assertEqual(1, len(units))
        self.assertIn('Restart=on-failure', units[0].read_text())
        self.assertIn('notes with spaces $$ and %%', units[0].read_text())
        calls = self.calls()
        self.assertNotIn('login', [call[0] for call in calls])
        self.assertNotIn('sync', [call[0] for call in calls])
        self.assertIn(['sync-config', '--path', str(self.vault), '--configs', 'appearance'], calls)
        self.assertIn(['systemctl', '--user', 'enable', units[0].name], calls)
        self.assertEqual(2, calls.count(['systemctl', '--user', 'restart', units[0].name]))

    def test_client_failure_does_not_publish_or_activate_service(self):
        (self.home / 'fail-ob').touch()
        result = self.run_setup()
        self.assertNotEqual(0, result.returncode)
        self.assertFalse((self.home / '.config/systemd/user').exists())
        self.assertIn('sync', json.loads(self.config.read_text()))

    def test_install_failure_stops_before_consuming_client_output(self):
        self.write_command('mise', 'import sys\nsys.exit(1)\n')
        result = self.run_setup()
        self.assertNotEqual(0, result.returncode)
        self.assertFalse(self.log.exists())
        self.assertIn('sync', json.loads(self.config.read_text()))

    def test_first_use_uses_notes_in_current_users_documents_without_prompting(self):
        calls = []

        def client(*args, capture=False):
            calls.append(args)
            vaults = [] if len(calls) == 1 else [self.record]
            return subprocess.CompletedProcess(args, 0, json.dumps({'vaults': vaults}), '')

        with patch.object(setup, 'command', side_effect=client), \
                patch.object(setup, 'preflight_gui', return_value=False), \
                patch.object(setup.sys.stdin, 'isatty', return_value=True), \
                patch.object(setup.Path, 'home', return_value=self.home), \
                patch('builtins.input', side_effect=AssertionError('Unexpected setup prompt')):
            self.assertEqual([self.record], setup.configure(['/tools/ob'], setup.GuiLauncher()))
        self.assertIn(('/tools/ob', 'login'), calls)
        self.assertIn(('/tools/ob', 'sync-setup', '--vault', 'notes',
                       '--path', str(self.home / 'Documents/notes')), calls)

    def test_first_use_rejects_disabled_gui_cli_before_login_or_encryption_prompt(self):
        self.write_command('pgrep', '')
        self.write_command('flatpak', '''
import sys
if sys.argv[1] != 'info':
    print('Command line interface is not enabled.')
''')
        (self.home / 'Documents/notes').mkdir(parents=True)
        with patch.dict(os.environ, self.env), \
                patch.object(setup.sys.stdin, 'isatty', return_value=True), \
                patch.object(setup, 'command', return_value=subprocess.CompletedProcess(
                    [], 0, '{"vaults": []}', '')) as client:
            with self.assertRaisesRegex(RuntimeError, 'Settings > General > Advanced'):
                setup.configure([str(self.bin / 'ob')], setup.GuiLauncher())
        self.assertEqual([unittest.mock.call(str(self.bin / 'ob'), 'sync-list-local',
                                            '--json', capture=True)], client.call_args_list)

    def test_unconfigured_noninteractive_setup_explains_login_requirement(self):
        (self.home / 'empty').touch()
        result = self.run_setup()
        self.assertNotEqual(0, result.returncode)
        self.assertIn('interactively', result.stderr)
        self.assertFalse((self.home / '.config/systemd/user').exists())

    def test_closed_gui_supports_old_plugin_map_and_preserves_other_settings(self):
        self.config.write_text('{"sync": true, "templates": false, "daily-notes": true}')
        result = self.run_setup()
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual({'sync': False, 'templates': False, 'daily-notes': True},
                         json.loads(self.config.read_text()))

    def test_closed_gui_never_discovers_a_gui_launcher(self):
        native_which = shutil.which

        def which(name):
            if name in ('obsidian', 'flatpak'):
                self.fail('Closed GUI must not require a GUI launcher')
            return native_which(name)

        with patch.dict(os.environ, self.env), \
                patch.object(setup.shutil, 'which', side_effect=which):
            setup.setup()
        self.assertNotIn('sync', json.loads(self.config.read_text()))

    def test_malformed_gui_config_prevents_service_activation(self):
        self.config.write_text('{broken')
        result = self.run_setup()
        self.assertNotEqual(0, result.returncode)
        self.assertEqual('{broken', self.config.read_text())
        self.assertFalse((self.home / '.config/systemd/user').exists())

    def test_running_gui_uses_cli_for_exact_vault(self):
        self.write_command('pgrep', '')
        self.write_command('obsidian', '''
import json
from pathlib import Path
import sys
if sys.argv[1] == 'vault':
    print(Path.cwd())
elif sys.argv[1] == 'plugins:enabled':
    print('daily-notes\\ntemplates')
elif sys.argv[1:] == ['plugin:disable', 'id=sync', 'filter=core']:
    (Path.cwd() / '.obsidian/core-plugins.json').write_text('["daily-notes", "templates"]')
else:
    sys.exit(1)
''')
        with patch.dict(os.environ, self.env), \
                patch.object(setup.shutil, 'which', wraps=shutil.which) as discover:
            setup.setup()
        self.assertEqual(1, discover.call_args_list.count(unittest.mock.call('obsidian')))
        self.assertNotIn(unittest.mock.call('flatpak'), discover.call_args_list)
        self.assertNotIn('sync', json.loads(self.config.read_text()))

    def test_running_gui_cannot_claim_success_while_sync_remains_enabled(self):
        self.write_command('pgrep', '')
        self.write_command('obsidian', '''
from pathlib import Path
import sys
if sys.argv[1] == 'vault':
    print(Path.cwd())
''')
        result = self.run_setup()
        self.assertNotEqual(0, result.returncode)
        self.assertIn('still enabled', result.stderr)
        self.assertFalse((self.home / '.config/systemd/user').exists())

    def test_running_flatpak_uses_its_launcher_and_vault_directory(self):
        other_vault = self.home / 'second vault'
        other_config = other_vault / '.obsidian/core-plugins.json'
        other_config.parent.mkdir(parents=True)
        other_config.write_text('["sync"]')
        (self.home / 'vaults.json').write_text(json.dumps([
            self.record, {'id': 'other-vault', 'path': str(other_vault)},
        ]))
        self.write_command('pgrep', '')
        self.write_command('flatpak', '''
from pathlib import Path
import sys
args = sys.argv[1:]
with (Path.home() / 'flatpak-calls.jsonl').open('a') as log:
    import json
    log.write(json.dumps({'args': args, 'cwd': str(Path.cwd())}) + '\\n')
if args[0] == 'info':
    sys.exit(0)
assert args[:3] == ['run', '--cwd=' + str(Path.cwd()), 'md.obsidian.Obsidian']
if args[3:] == ['vault', 'info=path']:
    print(Path.cwd())
elif args[3:] == ['plugin:disable', 'id=sync', 'filter=core']:
    (Path.cwd() / '.obsidian/core-plugins.json').write_text('["templates"]')
elif args[3:] == ['plugins:enabled', 'filter=core']:
    print('templates')
else:
    sys.exit(1)
''')
        result = self.run_setup()
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(['templates'], json.loads(self.config.read_text()))
        calls = [json.loads(line) for line in
                 (self.home / 'flatpak-calls.jsonl').read_text().splitlines()]
        self.assertEqual(1, sum(call['args'][0] == 'info' for call in calls))
        self.assertEqual(6, sum(call['args'][0] == 'run' for call in calls))
        self.assertEqual(['templates'], json.loads(other_config.read_text()))
        self.assertEqual({str(self.vault), str(other_vault)},
                         {call['cwd'] for call in calls if call['args'][0] == 'run'})

    def test_running_gui_keeps_bound_launcher_when_another_installation_appears(self):
        self.write_command('pgrep', '')
        self.write_command('flatpak', '''
from pathlib import Path
import sys
args = sys.argv[1:]
if args[0] == 'info':
    conflicting = Path.home() / 'bin/obsidian'
    conflicting.write_text('#!' + sys.executable + '\\nraise SystemExit("wrong launcher")\\n')
    conflicting.chmod(0o755)
    sys.exit(0)
assert args[:3] == ['run', '--cwd=' + str(Path.cwd()), 'md.obsidian.Obsidian']
if args[3:] == ['vault', 'info=path']:
    print(Path.cwd())
elif args[3:] == ['plugin:disable', 'id=sync', 'filter=core']:
    (Path.cwd() / '.obsidian/core-plugins.json').write_text('["templates"]')
elif args[3:] == ['plugins:enabled', 'filter=core']:
    print('templates')
else:
    sys.exit(1)
''')
        (self.home / 'empty').touch()
        (self.home / 'Documents/notes').mkdir(parents=True)
        with patch.dict(os.environ, self.env), \
                patch.object(setup.sys.stdin, 'isatty', return_value=True):
            setup.setup()
        self.assertEqual(['templates'], json.loads(self.config.read_text()))
        # A fresh transaction is allowed to discover the newly preferred CLI.
        second = self.run_setup()
        self.assertNotEqual(0, second.returncode)
        self.assertIn(str(self.bin / 'obsidian'), second.stderr)

    def test_disabled_flatpak_cli_gives_actionable_error_without_activating_sync(self):
        self.write_command('pgrep', '')
        self.write_command('flatpak', '''
import sys
if sys.argv[1] != 'info':
    print('Command line interface is not enabled.')
''')
        result = self.run_setup()
        self.assertNotEqual(0, result.returncode)
        self.assertIn('Settings > General > Advanced', result.stderr)
        self.assertIn('close Obsidian', result.stderr)
        self.assertIn('sync', json.loads(self.config.read_text()))
        self.assertFalse((self.home / '.config/systemd/user').exists())

    def test_running_gui_selecting_another_vault_cannot_activate_sync(self):
        self.write_command('pgrep', '')
        self.write_command('obsidian', 'print("/another/vault")\n')
        result = self.run_setup()
        self.assertNotEqual(0, result.returncode)
        self.assertIn('another vault', result.stderr)
        self.assertFalse((self.home / '.config/systemd/user').exists())

    def test_gui_starting_during_login_is_rechecked_before_mutation(self):
        (self.home / 'empty').touch()
        self.write_command('pgrep', '''
from pathlib import Path
import sys
running = (Path.home() / 'gui-running').exists()
with (Path.home() / 'pgrep-calls').open('a') as log:
    log.write(str(running) + '\\n')
sys.exit(0 if running else 1)
''')
        self.write_command('obsidian', '''
from pathlib import Path
import sys
if sys.argv[1] == 'vault':
    print(Path.cwd())
elif sys.argv[1] == 'plugin:disable':
    (Path.cwd() / '.obsidian/core-plugins.json').write_text('["templates"]')
elif sys.argv[1] == 'plugins:enabled':
    print('templates')
else:
    sys.exit(1)
''')
        native_which = shutil.which

        def which(name):
            if name in ('obsidian', 'flatpak'):
                self.assertTrue((self.home / 'gui-running').exists(),
                                'GUI discovery must wait until the app is running')
            return native_which(name)

        with patch.dict(os.environ, self.env), \
                patch.object(setup.sys.stdin, 'isatty', return_value=True), \
                patch.object(setup.shutil, 'which', side_effect=which):
            setup.setup()
        self.assertEqual(['False', 'True'],
                         (self.home / 'pgrep-calls').read_text().splitlines())
        self.assertEqual(['templates'], json.loads(self.config.read_text()))
        self.assertTrue((self.home / '.config/systemd/user').exists())

    def test_macos_plist_preserves_argument_boundaries(self):
        path, contents = setup.service_file('darwin', self.record, ['/tools/ob'],
                                            self.home, '/node/bin')
        plist = plistlib.loads(contents)
        self.assertEqual(['/tools/ob', 'sync', '--continuous', '--path', str(self.vault)],
                         plist['ProgramArguments'])
        self.assertEqual('/node/bin:/usr/bin:/bin', plist['EnvironmentVariables']['PATH'])
        self.assertEqual(self.home / 'Library/LaunchAgents', path.parent)

    @unittest.skipUnless(shutil.which('systemd-analyze'), 'systemd parser unavailable')
    def test_generated_unit_is_accepted_by_systemd(self):
        path, contents = setup.service_file('linux', self.record, ['/bin/true'],
                                            self.home, '/usr/bin')
        setup.publish(path, contents)
        result = subprocess.run(['systemd-analyze', '--user', 'verify', str(path)],
                                env=self.env, capture_output=True, text=True)
        self.assertEqual(0, result.returncode, result.stderr)


if __name__ == '__main__':
    unittest.main()
