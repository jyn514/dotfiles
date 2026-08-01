#!/usr/bin/env python3

import os
import shlex
import subprocess
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
            "ubuntu": ("apt",),
        }[platform["ID"]]
        for command in (*managers, "brew", "code", "keymapp", "pwsh"):
            (self.bin / command).symlink_to(recorder)

        apt_cache = self.bin / "apt-cache"
        apt_cache.write_text("#!/bin/sh\nprintf 'l=Ubuntu,c=universe\\n'\n")
        apt_cache.chmod(0o755)

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
            ["./lib/setup_sudo.sh", "install_features"],
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
        else:
            self.fail(f"unsupported test platform: {platform['ID']}")


if __name__ == "__main__":
    unittest.main()
