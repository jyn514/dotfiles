import os
from pathlib import Path
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]
WRAPPER = ROOT / "dev" / "test-environment"


class TestEnvironmentTest(unittest.TestCase):
    def run_environment(self, **values: str) -> dict[str, str]:
        inherited = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith("DOTFILES_TEST_")
        }
        result = subprocess.run(
            [WRAPPER, "env"],
            env=inherited | values,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        return dict(line.split("=", 1) for line in result.stdout.splitlines())

    def test_preserves_real_tools_without_exposing_sandbox_authority(self) -> None:
        environment = self.run_environment(
            BB_REAL="/private/bb",
            BB_SOURCE_ROOT="/private/source",
            JAVA_REAL="/private/java",
            JJ_REAL="/private/jj",
            RG_REAL="/private/rg",
            CLAUDECODE="1",
            CODEX_THREAD_ID="thread",
            JJ_AGENT="pi",
            PI_CODING_AGENT="true",
            CODEX_SIDECAR_KEY="secret",
            CODEX_SIDECAR_URL="http://proxy",
            SANDBOX_PROXY_DIR="/run/proxies",
            SANDBOX_PROXY_DEFAULT_DIR="/run/default-proxies",
        )

        self.assertEqual("/private/bb", environment["DOTFILES_TEST_BB_REAL"])
        self.assertEqual("/private/java", environment["DOTFILES_TEST_JAVA_REAL"])
        self.assertEqual("/private/jj", environment["DOTFILES_TEST_JJ_REAL"])
        self.assertEqual("/private/rg", environment["DOTFILES_TEST_RG_REAL"])
        self.assertEqual(
            "/run/proxies", environment["DOTFILES_TEST_SANDBOX_PROXY_DIR"]
        )
        self.assertEqual("/nonexistent", environment["SANDBOX_PROXY_DEFAULT_DIR"])
        for name in (
            "BB_REAL", "BB_SOURCE_ROOT", "JAVA_REAL", "JJ_REAL", "RG_REAL",
            "CLAUDECODE", "CODEX_THREAD_ID", "JJ_AGENT", "PI_CODING_AGENT",
            "CODEX_SIDECAR_KEY", "CODEX_SIDECAR_URL", "SANDBOX_PROXY_DIR",
        ):
            self.assertNotIn(name, environment)

    def test_nested_use_retains_the_original_real_tool(self) -> None:
        environment = self.run_environment(
            BB_REAL="/replacement/bb",
            DOTFILES_TEST_BB_REAL="/original/bb",
        )

        self.assertEqual("/original/bb", environment["DOTFILES_TEST_BB_REAL"])


if __name__ == "__main__":
    unittest.main()
