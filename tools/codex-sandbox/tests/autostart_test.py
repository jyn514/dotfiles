import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch


SOURCE = Path(__file__).resolve().parents[1] / "lima/install-autostart.py"
spec = importlib.util.spec_from_file_location("sandbox_autostart", SOURCE)
autostart = importlib.util.module_from_spec(spec)
spec.loader.exec_module(autostart)


class AutostartTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.home = Path(self.temporary.name)
        self.configuration = self.home / "configuration"
        environment = patch.dict(os.environ, HOME=str(self.home), XDG_CONFIG_HOME=str(self.configuration))
        environment.start()
        self.addCleanup(environment.stop)

    def provision(self, record):
        path = self.home / record
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('{}\n')

    def test_unprovisioned_home_needs_no_lima_or_service_manager(self):
        with patch.object(autostart.shutil, "which", return_value=None), \
                patch.object(autostart.subprocess, "run") as run:
            autostart.main()
        run.assert_not_called()
        self.assertFalse(self.configuration.exists())

    def test_only_provisioned_vms_are_enabled_and_started(self):
        for build_vm in (False, True):
            with self.subTest(build_vm=build_vm):
                self.provision(".local/state/codex-sandbox-docker/host.json")
                if build_vm:
                    self.provision(".local/state/agent-docker/vm.json")
                with patch.object(autostart.shutil, "which", return_value="/usr/bin/limactl"), \
                        patch.object(autostart.subprocess, "run",
                                     return_value=subprocess.CompletedProcess([], 0, stdout="Lima\n")) as run:
                    autostart.main()
                expected = ["sandbox-host-docker.service"]
                if build_vm:
                    expected.append("agent-build-docker.service")
                self.assertEqual(["systemctl", "--user", "enable", "--now", *expected],
                                 run.call_args.args[0])
                self.assertEqual(set(expected), {path.name for path in
                                 (self.configuration / "systemd/user").iterdir()})

    def test_failed_unit_validation_does_not_publish_or_enable_services(self):
        self.provision(".local/state/agent-docker/vm.json")
        with patch.object(autostart.shutil, "which", return_value="/usr/bin/limactl"), \
                patch.object(autostart.subprocess, "run", side_effect=[
                    subprocess.CompletedProcess([], 0, stdout="Lima\n"),
                    subprocess.CalledProcessError(1, "systemd-analyze"),
                ]) as run:
            with self.assertRaises(subprocess.CalledProcessError):
                autostart.main()
        self.assertEqual(2, run.call_count)
        self.assertEqual([], list((self.configuration / "systemd/user").iterdir()))
