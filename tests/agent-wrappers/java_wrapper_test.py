#!/usr/bin/env python3

import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WRAPPER = ROOT / "libexec" / "agent-wrappers" / "java"


class JavaWrapperTest(unittest.TestCase):
    def run_wrapper(
        self, *arguments: str, tmpdir: str | None
    ) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory() as temporary:
            temp_dir = Path(temporary)
            real_java = temp_dir / "java"
            # One line per argument, so a bare invocation prints nothing at all.
            real_java.write_text(
                '#!/bin/sh\nfor argument in "$@"; do printf "%s\\n" "$argument"; done\n'
            )
            real_java.chmod(0o755)
            environment = {
                key: value for key, value in os.environ.items() if key != "TMPDIR"
            }
            environment["PATH"] = os.pathsep.join(
                (str(WRAPPER.parent), str(temp_dir), os.defpath)
            )
            if tmpdir is not None:
                environment["TMPDIR"] = tmpdir
            return subprocess.run(
                [WRAPPER, *arguments],
                env=environment,
                text=True,
                capture_output=True,
                check=False,
                timeout=5,
            )

    def test_forces_writable_tmpdir_ahead_of_caller_arguments(self) -> None:
        result = self.run_wrapper("-jar", "app.jar", tmpdir="/sandbox/tmp")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout.splitlines(),
            ["-Djava.io.tmpdir=/sandbox/tmp", "-jar", "app.jar"],
        )

    def test_caller_override_wins_because_it_comes_later(self) -> None:
        result = self.run_wrapper(
            "-Djava.io.tmpdir=/caller/choice", "Main", tmpdir="/sandbox/tmp"
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout.splitlines(),
            ["-Djava.io.tmpdir=/sandbox/tmp", "-Djava.io.tmpdir=/caller/choice", "Main"],
        )

    def test_forwards_unchanged_without_tmpdir(self) -> None:
        result = self.run_wrapper("-version", tmpdir=None)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["-version"])

    def test_bare_invocation_stays_bare(self) -> None:
        result = self.run_wrapper(tmpdir="/sandbox/tmp")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")


if __name__ == "__main__":
    unittest.main()
