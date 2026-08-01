#!/usr/bin/env python3

import os
import shlex
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class InstallationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.directory = Path(self.tempdir.name)
        self.bin = self.directory / "bin"
        self.bin.mkdir()
        self.log = self.directory / "commands.log"

        recorder = self.bin / "recorder"
        recorder.write_text(
            "#!/bin/sh\n"
            'name=${0##*/}\n'
            'printf "%s" "$name" >> "$INSTALL_COMMAND_LOG"\n'
            'for argument do printf " <%s>" "$argument" >> "$INSTALL_COMMAND_LOG"; done\n'
            'printf "\\n" >> "$INSTALL_COMMAND_LOG"\n'
            'if [ "$name" = rpm ] && [ "${1:-}" = -E ]; then printf "42\\n"; fi\n'
        )
        recorder.chmod(0o755)
        platform = self.platform()
        managers = {
            "alpine": ("apk",),
            "arch": ("pacman",),
            "debian": ("apt",),
            "fedora": ("dnf", "rpm"),
            "macos": (),
            "ubuntu": ("apt",),
        }[platform["ID"]]
        for command in (*managers, "brew", "code", "keymapp", "pwsh"):
            (self.bin / command).symlink_to(recorder)

        apt_cache = self.bin / "apt-cache"
        apt_cache.write_text("#!/bin/sh\nprintf 'l=Ubuntu,c=universe\\n'\n")
        apt_cache.chmod(0o755)
        fake_id = self.bin / "id"
        fake_id.write_text("#!/bin/sh\n[ \"${1:-}\" = -u ] && printf '0\\n'\n")
        fake_id.chmod(0o755)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def run_install(self) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env.update(
            DOAS_USER="",
            INSTALL_COMMAND_LOG=str(self.log),
            PATH=f"{self.bin}:{env['PATH']}",
            SUDO_USER="",
        )
        return subprocess.run(
            [
                "sh",
                "-c",
                f"{env.get('SETUP_COMMAND_PREFIX') or './setup.sh'} install-global",
            ],
            cwd=ROOT,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )

    def commands(self) -> list[list[str]]:
        commands = []
        for line in self.log.read_text().splitlines():
            name, *arguments = line.split(" <")
            commands.append([name, *(argument[:-1] for argument in arguments)])
        return commands

    @staticmethod
    def manifest(name: str) -> list[str]:
        return [
            line
            for line in (ROOT / "install" / name).read_text().splitlines()
            if line and not line.lstrip().startswith("#")
        ]

    @staticmethod
    def platform() -> dict[str, str]:
        if sys.platform == "darwin":
            return {"ID": "macos"}
        platform = {}
        for line in Path("/etc/os-release").read_text().splitlines():
            if "=" in line:
                key, value = line.split("=", 1)
                platform[key] = value.strip('"')
        return platform

    @staticmethod
    def translated(
        packages: list[str], replacements: dict[str, str | None]
    ) -> list[str]:
        translated = []
        for package in packages:
            replacement = replacements.get(package, package)
            if replacement is not None:
                translated.extend(shlex.split(replacement))
        return translated

    def assert_brew_packages(self, commands: list[list[str]]) -> None:
        self.assertIn(
            ["brew", "install", "-q", *self.manifest("brew_packages.txt")],
            commands,
        )

    def test_requests_platform_packages(self) -> None:
        platform = self.platform()

        result = self.run_install()

        self.assertEqual(0, result.returncode, result.stderr)
        commands = self.commands()
        packages = self.manifest("packages.txt")
        self.assert_brew_packages(commands)

        if platform["ID"] == "alpine":
            replacements = {
                "antidote": None,
                "build-essential": None,
                "clangd": None,
                "cowsay": None,
                "fd-find": "fd",
                "fscrypt": None,
                "fzy": None,
                "gh": None,
                "git-delta": "delta",
                "glow": None,
                "kitty": "kitty kitty-kitten",
                "libpam-fscrypt": None,
                "libssl-dev": None,
                "libterm-readline-gnu-perl": "perl-term-readline-gnu",
                "liburi-perl": "perl-uri",
                "libusb-1.0-0-dev": None,
                "lua-language-server": None,
                "manpages": "man-pages",
                "manpages-dev": None,
                "ninja-build": "ninja-build ninja-is-really-ninja",
                "nvim": "neovim",
                "pkg-config": None,
                "python3-pip": None,
                "python3-pylsp": None,
                "signal-desktop": None,
                "xdot": None,
            }
            self.assertIn(
                [
                    "apk",
                    "add",
                    "less",
                    "py3-pip",
                    "zsh",
                    *self.translated(packages, replacements),
                ],
                commands,
            )
        elif platform["ID"] == "fedora":
            replacements = {
                "antidote": None,
                "build-essential": "@development-tools",
                "libpam-fscrypt": None,
                "libssl-dev": "openssl-devel",
                "libterm-readline-gnu-perl": "perl-Term-ReadLine-Gnu",
                "liburi-perl": "perl-URI",
                "libusb-1.0-0-dev": None,
                "lua-language-server": None,
                "manpages": "man-pages",
                "manpages-dev": None,
                "openjdk21": "java-25-openjdk",
                "python3-pylsp": "python3-lsp-server",
            }
            self.assertIn(
                [
                    "dnf",
                    "install",
                    "-y",
                    *self.translated(packages, replacements),
                    "1password",
                ],
                commands,
            )
            self.assertTrue(
                any(
                    "rpmfusion-free-release-42" in " ".join(command)
                    for command in commands
                )
            )
        elif platform["ID"] == "arch":
            replacements = {
                "antidote": None,
                "build-essential": None,
                "clangd": "clang",
                "fd-find": "fd",
                "gh": "github-cli",
                "libpam-fscrypt": None,
                "libssl-dev": "openssl",
                "libterm-readline-gnu-perl": "perl-term-readline-gnu",
                "liburi-perl": "perl-uri",
                "libusb-1.0-0-dev": "libusb",
                "manpages": "man-pages",
                "manpages-dev": None,
                "ninja-build": "ninja",
                "openjdk21": "jdk21-openjdk",
                "python3-pip": "python-pip",
                "python3-pylsp": "python-lsp-server",
            }
            self.assertIn(
                [
                    "pacman",
                    "--sync",
                    "--refresh",
                    "--sysupgrade",
                    "--needed",
                    *self.translated(packages, replacements),
                ],
                commands,
            )
        elif platform["ID"] in ("debian", "ubuntu"):
            self.assertIn(["apt", "update"], commands)
            self.assertIn(["apt", "install", "-y", *packages], commands)
        elif platform["ID"] == "macos":
            replacements = {
                "build-essential": None,
                "clangd": None,
                "fd-find": "fd",
                "fscrypt": None,
                "libpam-fscrypt": None,
                "libssl-dev": None,
                "libterm-readline-gnu-perl": None,
                "liburi-perl": None,
                "libusb-1.0-0-dev": None,
                "manpages": None,
                "manpages-dev": None,
                "ninja-build": "ninja",
                "openjdk21": "openjdk@21",
                "python3-pip": None,
                "python3-pylsp": "python-lsp-server",
                "strace": None,
                "traceroute": None,
                "unzip": None,
                "valgrind": None,
                "xdg-utils": None,
            }
            self.assertIn(
                [
                    "brew",
                    "install",
                    "-q",
                    *self.translated(packages, replacements),
                ],
                commands,
            )
        else:
            self.fail(f"unsupported test platform: {platform['ID']}")


class LocalInstallationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.directory = Path(self.tempdir.name)
        self.home = self.directory / "home"
        self.home.mkdir()
        self.bin = self.directory / "bin"
        self.bin.mkdir()
        self.log = self.directory / "commands.log"

        recorder = self.bin / "recorder"
        recorder.write_text(
            "#!/bin/sh\n"
            'name=${0##*/}\n'
            'printf "%s" "$name" >> "$INSTALL_COMMAND_LOG"\n'
            'for argument do printf " <%s>" "$argument" >> "$INSTALL_COMMAND_LOG"; done\n'
            'printf "\\n" >> "$INSTALL_COMMAND_LOG"\n'
            'case "$name:${FAIL_PYTHON_INSTALL:-}" in python:1|python3:1) exit 1;; esac\n'
        )
        recorder.chmod(0o755)
        for command in (
            "1password",
            "cargo",
            "clojure",
            "glide",
            "nvim",
            "pip3",
            "python3",
        ):
            (self.bin / command).symlink_to(recorder)
        if InstallationTests.platform()["ID"] == "macos":
            (self.bin / "brew").symlink_to(recorder)

        curl = self.bin / "curl"
        curl.write_text("#!/bin/sh\nexit 0\n")
        curl.chmod(0o755)
        fish = self.bin / "fish"
        fish.write_text(
            "#!/bin/sh\n"
            'script=$(printf "%s" "${2:-}" | tr "\\n" " ")\n'
            'printf "fish <%s> <%s>\\n" "${1:-}" "$script" '
            '>> "$INSTALL_COMMAND_LOG"\n'
        )
        fish.chmod(0o755)

        (self.home / ".profile").symlink_to(ROOT / "config/profile")
        for directory in (
            ".config/zsh/antidote",
            ".local/lib/PowerShellEditorServices",
            ".local/lib/cargo/bin",
            ".local/lib/cpptools",
        ):
            (self.home / directory).mkdir(parents=True)
        cargo_binstall = self.home / ".local/lib/cargo/bin/cargo-binstall"
        cargo_binstall.touch()
        cargo_binstall.chmod(0o755)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def run_install(self) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env.update(
            DOAS_USER="",
            HOME=str(self.home),
            INSTALL_COMMAND_LOG=str(self.log),
            PATH=f"{self.bin}:{env['PATH']}",
            SSH_AUTH_SOCK="",
            SUDO_USER="",
        )
        return subprocess.run(
            [
                "sh",
                "-c",
                f"{env.get('SETUP_COMMAND_PREFIX') or './setup.sh'} install-local",
            ],
            cwd=ROOT,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )

    def run_install_with(self, **overrides: str) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env.update(
            DOAS_USER="",
            HOME=str(self.home),
            INSTALL_COMMAND_LOG=str(self.log),
            PATH=f"{self.bin}:{env['PATH']}",
            SSH_AUTH_SOCK="",
            SUDO_USER="",
        )
        env.update(overrides)
        return subprocess.run(
            [
                "sh",
                "-c",
                f"{env.get('SETUP_COMMAND_PREFIX') or './setup.sh'} install-local",
            ],
            cwd=ROOT,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )

    def commands(self) -> list[list[str]]:
        commands = []
        for line in self.log.read_text().splitlines():
            name, *arguments = line.split(" <")
            commands.append([name, *(argument[:-1] for argument in arguments)])
        return commands

    def test_installs_user_tools_and_aliases(self) -> None:
        result = self.run_install()

        self.assertEqual(0, result.returncode, result.stderr)
        commands = self.commands()
        rust_packages = InstallationTests.manifest("rust.txt")
        self.assertIn(["cargo", "binstall", "cargo-binstall"], commands)
        self.assertIn(
            [
                "cargo",
                "binstall",
                "--quiet",
                "--no-confirm",
                "--rate-limit",
                "10/1",
                "--disable-strategies",
                "compile",
                "--continue-on-failure",
                *rust_packages,
            ],
            commands,
        )
        fish_scripts = [command[2] for command in commands if command[0] == "fish"]
        self.assertTrue(
            any("fisher install jorgebucaran/fisher" in script for script in fish_scripts)
        )
        self.assertTrue(
            any("command cat install/fish.txt" in script for script in fish_scripts)
        )
        if InstallationTests.platform()["ID"] != "alpine":
            self.assertTrue(
                any("xargs npm install -g" in script for script in fish_scripts)
            )
        self.assertIn(
            [
                "python",
                "-m",
                "pip",
                "install",
                "--quiet",
                "--user",
                "--break-system-packages",
                "-r",
                "install/python.txt",
            ],
            commands,
        )
        for alias, target in (("python", "python3"), ("py", "python3"), ("pip", "pip3")):
            destination = self.home / ".local/bin" / alias
            self.assertTrue(destination.is_symlink(), destination)
            self.assertEqual((self.bin / target).resolve(), destination.resolve())

        for alias in ("vi", "vim"):
            destination = self.home / ".local/bin" / alias
            self.assertTrue(destination.is_symlink(), destination)
            self.assertEqual((self.bin / "nvim").resolve(), destination.resolve())

    def test_second_local_install_preserves_aliases_and_succeeds(self) -> None:
        first = self.run_install()
        second = self.run_install()

        self.assertEqual(0, first.returncode, first.stderr)
        self.assertEqual(0, second.returncode, second.stderr)
        for alias in ("python", "py", "pip", "vi", "vim"):
            self.assertTrue((self.home / ".local/bin" / alias).is_symlink(), alias)

    def test_python_install_failure_makes_install_local_fail(self) -> None:
        result = self.run_install_with(FAIL_PYTHON_INSTALL="1")

        self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)


class RustBootstrapTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.directory = Path(self.tempdir.name)
        self.home = self.directory / "home"
        self.home.mkdir()
        self.bin = self.directory / "bin"
        self.bin.mkdir()
        self.log = self.directory / "commands.log"

        recorder = self.bin / "recorder"
        recorder.write_text(
            "#!/bin/sh\n"
            'name=${0##*/}\n'
            'printf "%s" "$name" >> "$INSTALL_COMMAND_LOG"\n'
            'for argument do printf " <%s>" "$argument" >> "$INSTALL_COMMAND_LOG"; done\n'
            'printf "\\n" >> "$INSTALL_COMMAND_LOG"\n'
        )
        recorder.chmod(0o755)
        for command in ("1password", "clojure", "glide", "pip3", "python3"):
            (self.bin / command).symlink_to(recorder)

        rustup_init = self.bin / "rustup-init"
        rustup_init.write_text(
            "#!/bin/sh\n"
            'printf "rustup-init" >> "$INSTALL_COMMAND_LOG"\n'
            'for argument do printf " <%s>" "$argument" >> "$INSTALL_COMMAND_LOG"; done\n'
            'printf "\\n" >> "$INSTALL_COMMAND_LOG"\n'
            'mkdir -p "$CARGO_HOME/bin"\n'
            'ln -sf "$RUSTUP_RECORDER" "$CARGO_HOME/bin/cargo"\n'
            'ln -sf "$RUSTUP_RECORDER" "$CARGO_HOME/bin/cargo-binstall"\n'
            'ln -sf "$RUSTUP_RECORDER" "$CARGO_HOME/bin/rustup"\n'
            'printf "PATH=\\\"$CARGO_HOME/bin:$PATH\\\"; export PATH\\n" > "$CARGO_HOME/env"\n'
        )
        rustup_init.chmod(0o755)
        for directory in (
            ".config/fish",
            ".config/zsh/antidote",
            ".local/lib/PowerShellEditorServices",
            ".local/lib/cpptools",
            ".local/share/nvm/v-test",
        ):
            (self.home / directory).mkdir(parents=True)
        (self.home / ".config/fish/fish_plugins").touch()
        (self.home / ".profile").symlink_to(ROOT / "config/profile")

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_fresh_rust_install_selects_components_and_nightly_default(self) -> None:
        env = os.environ.copy()
        env.update(
            CARGO_HOME=str(self.home / ".local/lib/cargo"),
            DOAS_USER="",
            HOME=str(self.home),
            INSTALL_COMMAND_LOG=str(self.log),
            PATH=f"{self.bin}:{env['PATH']}",
            RUSTUP_HOME=str(self.home / ".local/lib/rustup"),
            RUSTUP_RECORDER=str(self.bin / "recorder"),
            SSH_AUTH_SOCK="",
            SUDO_USER="",
        )

        result = subprocess.run(
            ["./setup.sh", "install-local"],
            cwd=ROOT,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(0, result.returncode, result.stderr)
        commands = self.log.read_text().splitlines()
        self.assertIn(
            "rustup-init <-y> <--profile> <minimal> <-c> <rustfmt> <-c> <clippy> <-c> <rust-analyzer>",
            commands,
        )
        self.assertIn(
            "rustup <toolchain> <add> <nightly> <--profile> <minimal> <-c> <clippy> <-c> <miri>",
            commands,
        )
        self.assertIn("rustup <default> <nightly>", commands)


if __name__ == "__main__":
    unittest.main()
