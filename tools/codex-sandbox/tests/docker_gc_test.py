"""GC provisioning must not re-enable disabled timers or precede verification."""

import importlib.util
from contextlib import redirect_stderr
import io
import json
from pathlib import Path
import runpy
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'lima'))
from lima.docker_host import DockerHost
from lima.host import Host

SOURCE = ROOT / 'lima/docker'
spec = importlib.util.spec_from_file_location('gc_policy', SOURCE / 'policy.py')
policy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(policy)


class DockerGCTest(unittest.TestCase):
    def test_upgrade_enables_first_installation_only_after_success(self):
        host = object.__new__(DockerHost)
        host.record = Mock(return_value={'files': {}})
        host.guest = Mock()
        installed = {'files': {'sandbox-image-gc.timer': 'digest'}}
        events = []
        host.guest.side_effect = lambda *args, **kwargs: events.append('enable')

        def upgraded():
            events.append('verified and published')
            return installed

        with patch.object(Host, 'upgrade', side_effect=upgraded):
            self.assertIs(host.upgrade(), installed)
        self.assertEqual(events, ['verified and published', 'enable'])
        host.guest.assert_called_once_with(installed, 'systemctl', '--user', 'enable', '--now',
                                          'sandbox-image-gc.timer', timeout=30)

        host.guest.reset_mock()
        host.record.return_value = installed
        with patch.object(Host, 'upgrade', return_value=installed):
            host.upgrade()
        host.guest.assert_not_called()

    def test_failed_upgrade_does_not_start_image_cleanup(self):
        host = object.__new__(DockerHost)
        host.record = Mock(return_value={'files': {}})
        host.guest = Mock()
        with patch.object(Host, 'upgrade', side_effect=ValueError('verification failed')):
            with self.assertRaisesRegex(ValueError, 'verification failed'):
                host.upgrade()
        host.guest.assert_not_called()

    def test_guest_installer_copies_audited_units_without_enabling_them(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary) / 'home'
            staged = Path(temporary) / 'source'
            staged.mkdir()
            host = object.__new__(DockerHost)
            for name, source in host.source_files().items():
                shutil.copyfile(source, staged / name)
            real_path = Path

            def guest_path(value):
                return staged if value == '/usr/local/share/codex-sandbox' else real_path(value)

            with patch('pathlib.Path', side_effect=guest_path) as paths, \
                    patch('subprocess.run', return_value=subprocess.CompletedProcess([], 0,
                          'ActiveState=active\nSubState=running\nNeedDaemonReload=no\n', '')) as run, \
                    redirect_stderr(io.StringIO()):
                paths.home.return_value = home
                self.assertEqual(0, runpy.run_path(str(SOURCE / 'configure-user.py'))['main']())
            with patch.object(Path, 'home', return_value=home), patch.object(policy, 'BASE', staged):
                for name in ('sandbox-image-gc.service', 'sandbox-image-gc.timer'):
                    properties = f'FragmentPath={home / ".config/systemd/user" / name}\nDropInPaths=\n'
                    with patch.object(policy, 'run', return_value=properties):
                        policy.verify_units((name,), 'image GC')
            self.assertFalse(any('enable' in call.args[0] for call in run.call_args_list))

    def test_policy_rejects_changed_or_overridden_user_units(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            units = home / '.config/systemd/user'
            units.mkdir(parents=True)
            name = 'sandbox-image-gc.service'
            shutil.copyfile(SOURCE / name, units / name)
            properties = f'FragmentPath={units / name}\nDropInPaths=\n'
            with patch.object(Path, 'home', return_value=home), \
                    patch.object(policy, 'BASE', SOURCE), \
                    patch.object(policy, 'run', return_value=properties) as run:
                policy.verify_units((name,), 'image GC')
                run.return_value = properties.replace('DropInPaths=', 'DropInPaths=/override.conf')
                with self.assertRaisesRegex(ValueError, 'overridden'):
                    policy.verify_units((name,), 'image GC')
                run.return_value = properties
                (units / name).write_text('[Service]\nExecStart=/bin/true\n')
                with self.assertRaisesRegex(ValueError, 'unit changed'):
                    policy.verify_units((name,), 'image GC')

    @unittest.skipUnless(shutil.which('systemd-analyze') and Path('/usr/bin/docker').exists(),
                         'systemd-analyze and /usr/bin/docker required')
    def test_systemd_accepts_provisioned_units(self):
        with tempfile.TemporaryDirectory() as temporary:
            units = Path(temporary)
            (units / 'docker.service').write_text('[Service]\nExecStart=/bin/true\n')
            host = object.__new__(DockerHost)
            for name, source in host.source_files().items():
                if name.endswith(('.service', '.timer', '.slice')):
                    shutil.copyfile(source, units / name)
            result = subprocess.run(['systemd-analyze', '--user', 'verify',
                                     str(units / 'sandbox-image-gc.service'),
                                     str(units / 'sandbox-image-gc.timer')],
                                    capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    @unittest.skipUnless(shutil.which('dockerd'), 'dockerd required')
    def test_dockerd_accepts_cache_budget_and_a_changed_budget(self):
        with tempfile.TemporaryDirectory() as temporary:
            config = json.loads((SOURCE / 'daemon.json').read_text())
            for budget in (config['builder']['gc']['defaultKeepStorage'], '5GB'):
                config['builder']['gc']['defaultKeepStorage'] = budget
                path = Path(temporary) / 'daemon.json'
                path.write_text(json.dumps(config))
                result = subprocess.run(['dockerd', '--validate', '--config-file', str(path)],
                                        capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
