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
setup_sandbox() { record sandbox; }
setup_services() { record services; }
"""
        source = (ROOT / "setup").read_text()
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
            "9": ["global", "local", "basics", "shell", "python", "vim", "sandbox"],
            "10": ["sandbox"],
            "11": ["services"],
            "services": ["services"],
        }

        with tempfile.TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory)
            script = directory / "setup"
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
                    ["./setup", "2"],
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
            source = (ROOT / "setup").read_text()
            marker = "if ! [ $# = 0 ]; then\n"
            source = source.replace(
                marker,
                'exists() { [ "$1" != chsh ] && command -v "$1" >/dev/null 2>&1; }\n'
                + marker,
                1,
            )
            script = directory / "setup"
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
                ["./setup", "2"],
                cwd=ROOT,
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )

        self.assertEqual(23, result.returncode, result.stderr)
        self.assertIn("Changing default shell to fish", result.stdout)

    def test_shell_setup_fails_when_no_supported_shell_exists(self) -> None:
        source = (ROOT / "setup").read_text()
        marker = "if ! [ $# = 0 ]; then\n"
        source = source.replace(marker, "exists() { return 1; }\n" + marker, 1)

        with tempfile.TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory)
            script = directory / "setup"
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
        setup = (ROOT / "setup").read_text()

        self.assertIn("vi*|4) setup_vim", setup)
        self.assertIn("bac*|5) setup_backup", setup)
        self.assertNotIn("vi*|4) setup_basics", setup)
        self.assertNotIn("bac*|5) setup_basics", setup)

    def test_setup_restores_strict_mode_and_cleans_jj_config_override(self) -> None:
        setup = (ROOT / "setup").read_text()

        profile_source = setup.index("\t. config/profile\n")
        self.assertGreater(setup.index("\tset -u\n", profile_source), profile_source)
        self.assertGreaterEqual(setup.count("unset JJ_CONFIG_PATH"), 4)

    def test_menu_has_no_dead_routes_and_reports_full_numbered_range(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run(
                ["./setup"], cwd=ROOT, env=os.environ | {"HOME": directory},
                input="not-a-choice\n0\n", text=True, capture_output=True,
            )
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("[services|11]", result.stdout)
        self.assertIn("Please enter a number 0-11", result.stdout)

    def test_global_setup_runs_main_directly_as_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory)
            (directory / "setup").write_bytes((ROOT / "setup").read_bytes())
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
            package_plan_directory = directory / "dev"
            package_plan_directory.mkdir()
            package_plan = package_plan_directory / "package-plan"
            package_plan.write_text(
                "#!/bin/sh\n"
                'printf "%s\\n" "$*" > "$PACKAGE_PLAN_LOG"\n'
            )
            package_plan.chmod(0o755)
            package_plan_log = directory / "package-plan.log"
            binary_directory = directory / "bin"
            binary_directory.mkdir()
            fake_id = binary_directory / "id"
            fake_id.write_text('#!/bin/sh\nprintf "0\\n"\n')
            fake_id.chmod(0o755)
            env = os.environ.copy()
            env.update(
                HOME=str(directory),
                PATH=f"{binary_directory}:{env['PATH']}",
                PACKAGE_PLAN_LOG=str(package_plan_log),
                SETUP_SUDO_LOG=str(command_log),
            )

            result = subprocess.run(
                ["sh", "setup", "7"],
                cwd=directory,
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )
            setup_sudo_arguments = command_log.read_text()
            package_plan_arguments = package_plan_log.read_text()

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("apply --yes\n", package_plan_arguments)
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
                ["./setup"],
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


class ServicesDispatchTests(unittest.TestCase):
    def run_setup(self, option, system="Linux", fail_step=""):
        """Run real dispatch/functions, replacing effects rather than the services function."""
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            shell_library = directory / "lib/shell"
            shell_library.mkdir(parents=True)
            (shell_library / "lib.sh").write_text('exists() { return 1; }\n')
            (shell_library / "env.sh").write_text("")
            (directory / "config").mkdir()
            (directory / ".config/zsh/antidote").mkdir(parents=True)
            (directory / ".config/fish").mkdir(parents=True)
            (directory / ".config/fish/fish_plugins").touch()
            log = directory / "effects.log"
            record = '''
record() {
    printf '%s\\n' "$1" >> "$SETUP_EFFECT_LOG"
    [ "$FAIL_STEP" != "$1" ] || return 31
}
'''
            overrides = record + '''
setup_dotfiles() { record dotfiles; }
setup_install_global() { record global; }
setup_basics() { record basics; }
setup_shell() { record shell; }
setup_python() { record python; }
setup_vim() { record vim; }
setup_sandbox() { record sandbox; }
install_glide_native() { record glide-install; }
install_dragon_native() { record dragon-install; }
install_mise() { record mise-install; }
install_pi() { record pi-install; }
install_platform_bundles() { record platform-bundles; }
cmd_alias() { return 0; }
'''
            source = (ROOT / "setup").read_text()
            marker = 'if ! [ $# = 0 ]; then\n'
            self.assertEqual(1, source.count(marker))
            script = directory / "setup"
            script.write_text(source.replace(marker, overrides + marker, 1))
            binary = directory / "bin"
            binary.mkdir()
            commands = {
                "uname": 'printf "%s\\n" "$TEST_SYSTEM"\n',
                "id": 'printf "test-user\\n"\n',
                "loginctl": 'record "loginctl $*"\n',
                "systemctl": 'record "systemctl $*"\n',
                "tailscale": 'record forbidden-tailscale; exit 94\n',
                "python3": '''case "$*" in
libexec/setup/glide.py) record glide-policy;;
libexec/setup/setup_obsidian_sync.py) record obsidian;;
libexec/setup/setup_dashboard.py)
    [ "$MISE_GLOBAL_CONFIG_FILE" = "$EXPECTED_MISE_CONFIG" ] || exit 92
    record dashboard-policy;;
*) record "unexpected-python $*"; exit 93;;
esac
''',
            }
            for name, body in commands.items():
                command = binary / name
                command.write_text("#!/bin/sh\n" + record + body)
                command.chmod(0o755)
            env = os.environ | {
                "HOME": str(directory), "PATH": f"{binary}:{os.environ['PATH']}",
                "SETUP_EFFECT_LOG": str(log), "TEST_SYSTEM": system,
                "EXPECTED_MISE_CONFIG": str(directory / "config/mise.toml"),
                "FAIL_STEP": fail_step, "SETUP_NONINTERACTIVE": "1",
            }
            env.pop("IS_MACOS", None)
            result = subprocess.run(
                ["/bin/sh", str(script), option], cwd=directory,
                env=env, text=True, capture_output=True,
            )
            return result, log.read_text().splitlines() if log.exists() else []

    def test_removed_dashboard_route_does_not_dispatch(self):
        result, effects = self.run_setup("dashboard")
        self.assertEqual(126, result.returncode, result.stderr)
        self.assertEqual([], effects)
        self.assertIn("[services|11]", result.stdout)

    def test_services_configures_dashboard_after_existing_services_without_startup(self):
        for option in ("services", "11"):
            for system in ("Linux", "Darwin"):
                with self.subTest(option=option, system=system):
                    result, effects = self.run_setup(option, system)
                    expected = ["dotfiles"]
                    if system == "Linux":
                        expected += ["loginctl enable-linger test-user",
                                     "systemctl --user daemon-reload",
                                     "systemctl --user enable tmux.service"]
                    expected += ["obsidian", "dashboard-policy"]
                    self.assertEqual(0, result.returncode, result.stderr)
                    # Exact effects retain tmux's existing reload/enable and rule
                    # out any additional Dashboard daemon/start/reload commands.
                    self.assertEqual(expected, effects)

    def test_services_preserves_each_failure_and_stops_before_later_effects(self):
        steps = ["dotfiles", "loginctl enable-linger test-user",
                 "systemctl --user daemon-reload", "systemctl --user enable tmux.service",
                 "obsidian", "dashboard-policy"]
        for index, step in enumerate(steps):
            with self.subTest(failure=step):
                result, effects = self.run_setup("services", fail_step=step)
                self.assertEqual(31, result.returncode, result.stderr)
                self.assertEqual(steps[:index + 1], effects)

    def test_local_and_all_install_packages_without_dashboard_or_tailscale_configuration(self):
        local = ["glide-install", "dragon-install", "glide-policy", "mise-install",
                 "pi-install", "platform-bundles"]
        for option, expected in (("local", local + ["python"]),
                                 ("all", ["global"] + local +
                                  ["basics", "shell", "python", "vim", "sandbox"])):
            with self.subTest(option=option):
                result, effects = self.run_setup(option)
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertEqual(expected, effects)


if __name__ == "__main__":
    unittest.main()
