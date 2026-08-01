#!/usr/bin/env python3

import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class PromptHostnameTests(unittest.TestCase):
    def prompt_hostname(
        self, *, container: str = "", os_release: str | None = None
    ) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env.update(DOTFILES=str(ROOT), container=container)
        command = 'os_release=$1; set --; . bin/prompt-command; prompt_hostname "$os_release"'
        return subprocess.run(
            ["sh", "-c", command, "sh", os_release or "/missing/os-release"],
            cwd=ROOT,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_uses_runtime_and_os_id_in_a_container(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            os_release = Path(directory) / "os-release"
            os_release.write_text('NAME="Alpine Linux"\nID=alpine\n')

            result = self.prompt_hostname(container="podman", os_release=str(os_release))

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("podman:alpine", result.stdout)

    def test_supports_quoted_os_id(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            os_release = Path(directory) / "os-release"
            os_release.write_text('ID="ubuntu"\n')

            result = self.prompt_hostname(container="docker", os_release=str(os_release))

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("docker:ubuntu", result.stdout)

    def test_uses_runtime_when_os_release_is_unavailable(self) -> None:
        result = self.prompt_hostname(container="podman")

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("podman", result.stdout)

    def test_uses_hostname_outside_a_container(self) -> None:
        result = self.prompt_hostname()

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(os.uname().nodename, result.stdout)


if __name__ == "__main__":
    unittest.main()
