"""SSH setup validates effective policy before reloading the listener."""

import importlib.util
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

source = Path(__file__).resolve().parents[1] / "lima/configure-ssh.py"
spec = importlib.util.spec_from_file_location("configure_ssh", source)
ssh = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ssh)


class SshSetupTest(unittest.TestCase):
    def test_reload_follows_effective_limit_validation(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "sandbox.conf"
            with patch.object(ssh.subprocess, "run", return_value=SimpleNamespace(stdout="maxsessions 20\n")) as run:
                ssh.configure(path)
            self.assertIn("MaxSessions 20", path.read_text())
            self.assertEqual(["systemctl", "reload", "ssh"], run.call_args_list[-1].args[0])

    def test_invalid_or_overridden_policy_restores_previous_config_without_reload(self):
        for previous in (None, b"MaxSessions 10\n"):
            for failure in (subprocess.CalledProcessError(1, ["sshd", "-t"]), None):
                with self.subTest(previous=previous, failure=failure), tempfile.TemporaryDirectory() as temporary:
                    path = Path(temporary) / "sandbox.conf"
                    if previous is not None:
                        path.write_bytes(previous)
                    with patch.object(ssh.subprocess, "run", side_effect=failure,
                                      return_value=SimpleNamespace(stdout="maxsessions 10\n")) as run:
                        with self.assertRaises((ValueError, subprocess.CalledProcessError)):
                            ssh.configure(path)
                    self.assertEqual(previous, path.read_bytes() if path.exists() else None)
                    self.assertFalse(any(call.args[0][:1] == ["systemctl"] for call in run.call_args_list))


if __name__ == "__main__":
    unittest.main()
