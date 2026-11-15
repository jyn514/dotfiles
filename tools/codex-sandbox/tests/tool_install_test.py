"""A failed tool download must never reach extraction or installation."""

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[3]
INSTALL = ROOT / "tools/codex-sandbox/image/install-tools.sh"


class ToolInstallTest(unittest.TestCase):
    def test_failed_download_is_not_consumed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fake_bin = root / "bin"
            fake_bin.mkdir()
            fixture = Path(__file__).parent / "fixtures/tool-download-failure.py"
            for command in ("curl", "tar", "install", "sha256sum"):
                fake = fake_bin / command
                shutil.copy2(fixture, fake)
                fake.chmod(0o755)
            log = root / "commands"
            environment = os.environ | {"PATH": f"{fake_bin}:{os.environ['PATH']}",
                                        "TOOL_DOWNLOAD_LOG": str(log), "TMPDIR": str(root)}
            for tool in ("bb", "gh", "typst", "docker", "buildx"):
                with self.subTest(tool=tool):
                    result = subprocess.run([str(INSTALL), tool, "fixture-version"],
                                            env=environment, capture_output=True, text=True)
                    self.assertEqual(64, result.returncode, result.stderr)
                    self.assertEqual("curl\n", log.read_text())
                    self.assertEqual([], list(root.glob("tmp.*")))
                    log.unlink()


if __name__ == "__main__":
    unittest.main()
