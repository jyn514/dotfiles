import os
from pathlib import Path
import subprocess
import tempfile
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[3]
WRAPPER = ROOT / "tools" / "codex-sandbox" / "image" / "codex"


def write_executable(path: Path, contents: str) -> None:
    path.write_text(textwrap.dedent(contents).lstrip(), encoding="utf-8")
    path.chmod(0o755)


class CodexWrapperTest(unittest.TestCase):
    def run_wrapper(self, path: str, **environment: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(WRAPPER), "exec", "repair the ship"],
            env={**os.environ, "PATH": path, **environment},
            text=True,
            capture_output=True,
        )

    def test_configures_the_base_image_codex_for_the_auth_proxy(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fake_bin = Path(directory)
            write_executable(fake_bin / "codex", """
                #!/bin/sh
                printf 'key=%s\n' "$CODEX_SIDECAR_KEY"
                for argument do printf 'arg=%s\n' "$argument"; done
            """)

            result = self.run_wrapper(
                str(fake_bin),
                CODEX_SIDECAR_URL="http://codex-auth:8787/",
                CODEX_SIDECAR_KEY="session-secret",
            )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("", result.stderr)
        self.assertIn("key=session-secret\n", result.stdout)
        self.assertIn('arg=model_provider="codex-sandbox"\n', result.stdout)
        self.assertIn(
            'arg=model_providers.codex-sandbox.base_url="http://codex-auth:8787/codex"\n',
            result.stdout,
        )
        self.assertIn('arg=model_providers.codex-sandbox.env_key="CODEX_SIDECAR_KEY"\n', result.stdout)
        self.assertIn('arg=model_providers.codex-sandbox.wire_api="responses"\n', result.stdout)
        self.assertTrue(result.stdout.endswith("arg=exec\narg=repair the ship\n"))

    def test_reports_when_the_base_image_does_not_install_codex(self) -> None:
        result = self.run_wrapper(
            "/nonexistent",
            CODEX_SIDECAR_URL="http://codex-auth:8787",
            CODEX_SIDECAR_KEY="session-secret",
        )

        self.assertEqual(127, result.returncode)
        self.assertIn("Codex CLI is not installed by the sandbox base image", result.stderr)
        self.assertIn("install an executable named 'codex' on PATH", result.stderr)

    def test_reports_missing_proxy_configuration_before_running_codex(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fake_bin = Path(directory)
            write_executable(fake_bin / "codex", "#!/bin/sh\nexit 99\n")

            missing_url = self.run_wrapper(str(fake_bin), CODEX_SIDECAR_KEY="session-secret")
            missing_key = self.run_wrapper(str(fake_bin), CODEX_SIDECAR_URL="http://codex-auth:8787")

        self.assertEqual(78, missing_url.returncode)
        self.assertIn("authentication proxy is unavailable: CODEX_SIDECAR_URL is unset", missing_url.stderr)
        self.assertEqual(78, missing_key.returncode)
        self.assertIn("authentication proxy is unavailable: CODEX_SIDECAR_KEY is unset", missing_key.stderr)


if __name__ == "__main__":
    unittest.main()
