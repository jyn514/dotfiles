import os
import subprocess
import tempfile
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
            timeout=5,
        )

    def test_dispatches_agent_split(self) -> None:
        result = self.run_bb("agent-split", "--help")

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertTrue(result.stdout.startswith("Usage: bb agent-split "))

    def test_forwards_other_commands(self) -> None:
        result = self.run_bb("--version")

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertTrue(result.stdout.startswith("babashka v"))

    def test_agent_split_preserves_wrapped_jj_on_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary = Path(temporary_directory)
            wrappers = temporary / "wrappers"
            real = temporary / "real"
            wrappers.mkdir()
            real.mkdir()
            fake_jj = wrappers / "jj"
            fake_jj.write_text("#!/bin/sh\nexit 0\n")
            fake_jj.chmod(0o755)
            fake_bb = real / "bb"
            fake_bb.write_text("#!/bin/sh\ncommand -v jj\n")
            fake_bb.chmod(0o755)

            result = subprocess.run(
                [str(ROOT / "tools" / "agent-split" / "bb"), "agent-split", "--help"],
                cwd=ROOT,
                env=os.environ | {"PATH": f"{wrappers}:{real}:{os.defpath}"},
                text=True,
                capture_output=True,
                check=False,
                timeout=5,
            )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(f"{fake_jj}\n", result.stdout)

    def test_resolution_skips_duplicate_wrapper_copies(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary = Path(temporary_directory)
            first = temporary / "first"
            second = temporary / "second"
            real = temporary / "real"
            for directory in (first, second, real):
                directory.mkdir()

            wrapper = (
                "#!/bin/sh\n"
                "set -eu\n"
                f'. "{ROOT}/lib/shell/lib.sh"\n'
                'shim_resolve "$0" sample\n'
                'exec "$REAL" "$@"\n'
            )
            for directory in (first, second):
                command = directory / "sample"
                command.write_text(wrapper)
                command.chmod(0o755)
            command = real / "sample"
            command.write_text("#!/bin/sh\nprintf 'real\\n'\n")
            command.chmod(0o755)

            result = subprocess.run(
                [str(first / "sample")],
                env=os.environ | {"PATH": f"{first}:{second}:{real}:{os.defpath}"},
                text=True,
                capture_output=True,
                check=False,
                timeout=5,
            )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("real\n", result.stdout)


if __name__ == "__main__":
    unittest.main()
