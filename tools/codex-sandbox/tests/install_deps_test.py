"""Exercise shared dependency installation without touching real package state."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[3]
INSTALL = ROOT / "tools/codex-sandbox/image/install-deps.sh"
FIXTURE = Path(__file__).parent / "fixtures/dependency-command.py"


class InstallDependenciesTest(unittest.TestCase):
    def test_runtime_packages_and_patch_check_for_each_package_manager(self):
        for manager in ("apt-get", "apk", "microdnf"):
            for check_status in (0, 17):
                with self.subTest(manager=manager, patch_check_status=check_status):
                    with tempfile.TemporaryDirectory() as directory:
                        root = Path(directory)
                        fake_bin = root / "bin"
                        fake_bin.mkdir()
                        for command in (manager, "fd", "jq", "patch", "shellcheck", "socat", "rm"):
                            fake = fake_bin / command
                            shutil.copy2(FIXTURE, fake)
                            fake.chmod(0o755)
                        (fake_bin / "python3").symlink_to(sys.executable)
                        log = root / "commands.jsonl"
                        environment = os.environ | {
                            "PATH": str(fake_bin), "DEPENDENCY_COMMAND_LOG": str(log),
                            "PATCH_CHECK_STATUS": str(check_status), "KEEP_PACKAGE_CACHE": "",
                        }
                        result = subprocess.run(["/bin/sh", str(INSTALL)], env=environment,
                                                capture_output=True, text=True, timeout=10)
                        self.assertEqual(check_status, result.returncode, result.stderr)
                        calls = [json.loads(line) for line in log.read_text().splitlines()]
                        installs = [call for call in calls if call[0] == manager
                                    and call[1] in {"install", "add"}]
                        self.assertEqual(1, len(installs), calls)
                        self.assertIn("patch", installs[0])
                        self.assertIn("git", installs[0])
                        self.assertIn("curl", installs[0])
                        self.assertEqual(1, calls.count(["patch", "--version"]))
                        if check_status:
                            self.assertEqual(["patch", "--version"], calls[-1])
                        else:
                            self.assertEqual(["socat", "-V"], calls[-1])


if __name__ == "__main__":
    unittest.main()
