#!/usr/bin/env python3

import os
import subprocess
import tempfile
import time
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

    def test_display_pwd_treats_home_as_literal_text(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "home[1]&"
            cwd = home / "one" / "two"
            cwd.mkdir(parents=True)
            result = subprocess.run(
                [
                    "sh",
                    "-c",
                    f"set --; . {ROOT / 'bin/prompt-command'}; display_pwd",
                ],
                cwd=cwd,
                env=os.environ | {"DOTFILES": str(ROOT), "HOME": str(home.resolve())},
                text=True,
                capture_output=True,
                check=False,
            )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("~/one/two\n", result.stdout)


class PromptJujutsuTests(unittest.TestCase):
    def test_hanging_jj_cannot_block_prompt_rendering(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            nested = root / "nested"
            binaries = root / "bin"
            (root / ".jj").mkdir()
            nested.mkdir()
            binaries.mkdir()

            git = binaries / "git"
            git.write_text(
                "#!/bin/sh\n"
                "case \"$1\" in\n"
                "  rev-parse) printf '.git\\n';;\n"
                "  diff-index) exit 0;;\n"
                "  symbolic-ref) exit 1;;\n"
                "esac\n"
            )
            git.chmod(0o755)
            jj = binaries / "jj"
            jj.write_text("#!/bin/sh\nsleep 10\n")
            jj.chmod(0o755)

            env = os.environ.copy()
            env.update(DOTFILES=str(ROOT), PATH=f"{binaries}:{env['PATH']}")
            started = time.monotonic()
            result = subprocess.run(
                [str(ROOT / "bin/prompt-command"), "fish", "0"],
                cwd=nested,
                env=env,
                text=True,
                capture_output=True,
                check=False,
                timeout=3,
            )
            elapsed = time.monotonic() - started

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertLess(elapsed, 2)


if __name__ == "__main__":
    unittest.main()
