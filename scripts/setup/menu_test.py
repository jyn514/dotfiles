#!/usr/bin/env python3

import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class InteractiveMenuTests(unittest.TestCase):
    def test_global_setup_runs_main_directly_as_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory)
            (directory / "setup.sh").write_bytes((ROOT / "setup.sh").read_bytes())
            library = directory / "lib"
            library.mkdir()
            (library / "lib.sh").write_text(
                'exists() { command -v "$1" >/dev/null 2>&1; }\n'
            )
            (library / "env.sh").write_text("")
            setup_sudo = library / "setup_sudo.sh"
            setup_sudo.write_text(
                "#!/bin/sh\n"
                'printf "%s\\n" "$*" > "$SETUP_SUDO_LOG"\n'
            )
            setup_sudo.chmod(0o755)
            command_log = directory / "setup-sudo.log"
            binary_directory = directory / "bin"
            binary_directory.mkdir()
            fake_id = binary_directory / "id"
            fake_id.write_text('#!/bin/sh\nprintf "0\\n"\n')
            fake_id.chmod(0o755)
            env = os.environ.copy()
            env.update(
                HOME=str(directory),
                PATH=f"{binary_directory}:{env['PATH']}",
                SETUP_SUDO_LOG=str(command_log),
            )

            result = subprocess.run(
                ["sh", "setup.sh", "7"],
                cwd=directory,
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )
            setup_sudo_arguments = command_log.read_text()

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("main\n", setup_sudo_arguments)

    def test_mise_command_does_not_consume_later_menu_choices(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory)
            home = directory / "home"
            binary_directory = directory / "bin"
            home.mkdir()
            binary_directory.mkdir()

            mise = binary_directory / "mise"
            mise.write_text("#!/bin/sh\ncat >/dev/null\n")
            mise.chmod(0o755)

            env = os.environ.copy()
            env.update(
                HOME=str(home),
                PATH=f"{binary_directory}:{env['PATH']}",
            )
            result = subprocess.run(
                ["./setup.sh"],
                cwd=ROOT,
                env=env,
                input="3\nnot-a-choice\n0\n",
                text=True,
                capture_output=True,
                check=False,
            )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("Please enter a number", result.stdout)
        self.assertEqual(3, result.stdout.count("Choose setup to run:"))


if __name__ == "__main__":
    unittest.main()
