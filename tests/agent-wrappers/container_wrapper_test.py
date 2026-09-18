#!/usr/bin/env python3

from pathlib import Path
import os
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
WRAPPERS = ROOT / "libexec" / "sandbox-wrappers"


class ContainerWrapperTests(unittest.TestCase):
    def test_container_wrappers_are_guest_only(self) -> None:
        for name in ("docker", "podman"):
            with self.subTest(name=name):
                result = subprocess.run(
                    [str(WRAPPERS / name), "--version"],
                    env={key: value for key, value in os.environ.items()
                         if key != "DOTFILES_SANDBOX"},
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    check=False,
                )
                self.assertEqual(125, result.returncode)
                self.assertIn("only available inside an agent sandbox", result.stderr)

    def test_host_path_does_not_select_guest_wrappers(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            native = Path(directory)
            for name in ("docker", "podman"):
                client = native / name
                client.write_text("#!/bin/sh\n")
                client.chmod(0o700)
            environment = os.environ | {
                "PATH": f"{ROOT / 'libexec/agent-wrappers'}:{native}:/usr/bin:/bin",
            }
            for name in ("docker", "podman"):
                with self.subTest(name=name):
                    result = subprocess.run(
                        ["sh", "-c", f"command -v {name}"],
                        env=environment,
                        text=True,
                        stdout=subprocess.PIPE,
                        check=True,
                    )
                    self.assertEqual(f"{native / name}\n", result.stdout)


if __name__ == "__main__":
    unittest.main()
