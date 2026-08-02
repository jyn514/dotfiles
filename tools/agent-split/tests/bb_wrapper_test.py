import os
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
WRAPPERS = ROOT / "libexec" / "agent-wrappers"


class BbWrapperTest(unittest.TestCase):
    def run_bb(self, *args: str) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env["PATH"] = f"{WRAPPERS}:{env['PATH']}"
        return subprocess.run(
            ["bb", *args],
            cwd=ROOT,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_dispatches_agent_split(self) -> None:
        result = self.run_bb("agent-split", "--help")

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertTrue(result.stdout.startswith("Usage: bb agent-split "))

    def test_forwards_other_commands(self) -> None:
        result = self.run_bb("--version")

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertTrue(result.stdout.startswith("babashka v"))


if __name__ == "__main__":
    unittest.main()
