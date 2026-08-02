#!/usr/bin/env python3

import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class InteractiveMenuTests(unittest.TestCase):
    def test_every_numbered_option_dispatches_to_the_expected_setup(self) -> None:
        overrides = """
record() { printf '%s\\n' "$1" >> "$SETUP_OPTION_LOG"; }
setup_dotfiles() { record dotfiles; }
setup_shell() { record shell; }
setup_python() { record python; }
setup_basics() { record basics; }
setup_vim() { record vim; }
setup_backup() { record backup; }
setup_install_local() { record local; }
setup_install_global() { record global; }
setup_kde() { record kde; }
"""
        source = (ROOT / "setup.sh").read_text()
        marker = 'if ! [ $# = 0 ]; then\n'
        instrumented = source.replace(marker, overrides + marker, 1)
        expected = {
            "0": [],
            "1": ["dotfiles"],
            "2": ["shell"],
            "3": ["python"],
            "4": ["vim"],
            "5": ["backup"],
            "6": ["local", "python"],
            "7": ["global"],
            "8": ["kde"],
            "9": ["global", "local", "basics", "shell", "python", "vim"],
        }

        with tempfile.TemporaryDirectory(dir=ROOT) as temporary_directory:
            directory = Path(temporary_directory)
            script = directory / "setup.sh"
            script.write_text(instrumented)
            (directory / "lib").symlink_to(ROOT / "lib", target_is_directory=True)
            (directory / "libexec").symlink_to(
                ROOT / "libexec", target_is_directory=True
            )
            (directory / "config").symlink_to(ROOT / "config", target_is_directory=True)
            for option, calls in expected.items():
                log = directory / f"option-{option}.log"
                env = os.environ.copy()
                env.update(HOME=str(directory), SETUP_OPTION_LOG=str(log))
                for run in range(2):
                    result = subprocess.run(
                        ["sh", str(script), option],
                        cwd=ROOT,
                        env=env,
                        text=True,
                        capture_output=True,
                        check=False,
                    )
                    self.assertEqual(
                        0, result.returncode, (option, run, result.stderr)
                    )
                actual = log.read_text().splitlines() if log.exists() else []
                self.assertEqual(calls * 2, actual, option)

    def test_shell_setup_handles_an_unset_shell(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory)
            binary_directory = directory / "bin"
            binary_directory.mkdir()
            chsh_log = directory / "chsh.log"
            chsh = binary_directory / "chsh"
            chsh.write_text(
                "#!/bin/sh\n"
                'printf "%s\\n" "$*" > "$CHSH_LOG"\n'
            )
            chsh.chmod(0o755)
            env = os.environ.copy()
            env.update(
                CHSH_LOG=str(chsh_log),
                HOME=str(directory),
                PATH=f"{binary_directory}:{env['PATH']}",
                SHELL="",
            )

            results = [
                subprocess.run(
                    ["./setup.sh", "2"],
                    cwd=ROOT,
                    env=env,
                    text=True,
                    capture_output=True,
                    check=False,
                )
                for _ in range(2)
            ]

        for result in results:
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertNotIn("parameter not set", result.stderr)

    def test_shell_setup_explains_when_chsh_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory)
            binary_directory = directory / "bin"
            binary_directory.mkdir()
            (binary_directory / "fish").symlink_to("/bin/true")
            source = (ROOT / "setup.sh").read_text()
            marker = "if ! [ $# = 0 ]; then\n"
            source = source.replace(
                marker,
                'exists() { [ "$1" != chsh ] && command -v "$1" >/dev/null 2>&1; }\n'
                + marker,
                1,
            )
            script = directory / "setup.sh"
            script.write_text(source)
            (directory / "lib").symlink_to(ROOT / "lib", target_is_directory=True)
            (directory / "libexec").symlink_to(
                ROOT / "libexec", target_is_directory=True
            )
            (directory / "config").symlink_to(ROOT / "config", target_is_directory=True)
            env = os.environ.copy()
            env.update(
                HOME=str(directory),
                PATH=f"{binary_directory}:{env['PATH']}",
                SHELL="",
            )

            result = subprocess.run(
                ["/bin/sh", str(script), "2"],
                cwd=directory,
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )

        self.assertNotEqual(0, result.returncode)
        self.assertIn("chsh is required", result.stderr)

    def test_shell_setup_rejects_substring_match_and_propagates_chsh_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory)
            binary_directory = directory / "bin"
            binary_directory.mkdir()
            fish = binary_directory / "fish"
            fish.write_text("#!/bin/sh\nexit 0\n")
            fish.chmod(0o755)
            chsh = binary_directory / "chsh"
            chsh.write_text("#!/bin/sh\nexit 23\n")
            chsh.chmod(0o755)
            env = os.environ.copy()
            env.update(
                HOME=str(directory),
                PATH=f"{binary_directory}:{env['PATH']}",
                SHELL="/bin/fishery",
            )

            result = subprocess.run(
                ["./setup.sh", "2"],
                cwd=ROOT,
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )

        self.assertEqual(23, result.returncode, result.stderr)
        self.assertIn("Changing default shell to fish", result.stdout)

    def test_shell_setup_fails_when_no_supported_shell_exists(self) -> None:
        source = (ROOT / "setup.sh").read_text()
        marker = "if ! [ $# = 0 ]; then\n"
        source = source.replace(marker, "exists() { return 1; }\n" + marker, 1)

        with tempfile.TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory)
            script = directory / "setup.sh"
            script.write_text(source)
            (directory / "lib").symlink_to(ROOT / "lib", target_is_directory=True)
            (directory / "libexec").symlink_to(
                ROOT / "libexec", target_is_directory=True
            )
            (directory / "config").symlink_to(ROOT / "config", target_is_directory=True)
            result = subprocess.run(
                ["/bin/sh", str(script), "2"],
                cwd=directory,
                env=os.environ | {"HOME": str(directory), "SHELL": ""},
                text=True,
                capture_output=True,
                check=False,
            )

        self.assertNotEqual(0, result.returncode)
        self.assertIn("no supported shell found", result.stderr)

    def test_vim_and_backup_options_are_decoupled_from_basics(self) -> None:
        setup = (ROOT / "setup.sh").read_text()

        self.assertIn("vi*|4) setup_vim", setup)
        self.assertIn("bac*|5) setup_backup", setup)
        self.assertNotIn("vi*|4) setup_basics", setup)
        self.assertNotIn("bac*|5) setup_basics", setup)

    def test_setup_restores_strict_mode_and_checks_cron_writes(self) -> None:
        setup = (ROOT / "setup.sh").read_text()

        profile_source = setup.index("\t. config/profile\n")
        self.assertGreater(setup.index("\tset -u\n", profile_source), profile_source)
        self.assertIn("printf '%s\\n' \"$cron_entry\" >> \"$TMP_FILE\" || {", setup)
        self.assertGreaterEqual(setup.count("unset JJ_CONFIG_PATH"), 4)

    def test_menu_has_no_dead_routes_and_reports_full_numbered_range(self) -> None:
        setup = (ROOT / "setup.sh").read_text()

        self.assertNotIn("setup_macos", setup)
        self.assertNotIn("macos|10", setup)
        self.assertIn("Please enter a number 0-9", setup)

    def test_global_setup_runs_main_directly_as_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory)
            (directory / "setup.sh").write_bytes((ROOT / "setup.sh").read_bytes())
            shell_library = directory / "lib" / "shell"
            shell_library.mkdir(parents=True)
            (shell_library / "lib.sh").write_text(
                'exists() { command -v "$1" >/dev/null 2>&1; }\n'
            )
            (shell_library / "env.sh").write_text("")
            setup_directory = directory / "libexec" / "setup"
            setup_directory.mkdir(parents=True)
            setup_sudo = setup_directory / "setup_sudo.sh"
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
