#!/usr/bin/env python3

import json
import os
import shlex
import subprocess
import sys
import tempfile
import tomllib
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
            'if [ "$name" = mise ] && [ "${1:-}" = install ]; then\n'
            '  lock_dir=${MISE_GLOBAL_CONFIG_FILE%/*}\n'
            '  [ -f "$lock_dir/mise.lock" ] || exit 88\n'
            'fi\n'
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
        for command in (*managers, "brew", "code", "curl", "keymapp", "pwsh"):
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
            PATH=f"{self.bin}:/usr/bin:/bin:/usr/sbin:/sbin",
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

    def test_requests_platform_packages(self) -> None:
        platform = self.platform()

        results = [self.run_install(), self.run_install()]

        for result in results:
            self.assertEqual(0, result.returncode, result.stderr)
        commands = self.commands()
        packages = self.manifest("packages.txt")
        if platform["ID"] == "alpine":
            replacements = {
                "build-essential": "build-base",
                "clangd": None,
                "cowsay": None,
                "fd-find": "fd",
                "fscrypt": None,
                "fzy": None,
                "git-delta": "delta",
                "glow": None,
                "ipp-usb": None,
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
                "skanpage": None,
                "xdot": None,
            }
            self.assertIn(
                [
                    "apk",
                    "add",
                    "bash",
                    "less",
                    "libgcc",
                    "py3-pip",
                    "shadow",
                    "zsh",
                    *self.translated(packages, replacements),
                    "difftastic",
                ],
                commands,
            )
        elif platform["ID"] == "fedora":
            replacements = {
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
                "build-essential": "base-devel",
                "clangd": "clang",
                "fd-find": "fd",
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
                "curl": None,
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

    def test_system_package_manifest_has_unique_ownership(self) -> None:
        packages = self.manifest("packages.txt")
        setup = (ROOT / "setup.sh").read_text()

        self.assertEqual(len(packages), len(set(packages)))
        self.assertNotIn("opt/antidote", setup)
        self.assertIn("clone antidote ~/.config/zsh/antidote", setup)
        setup_sudo = (ROOT / "libexec/setup/setup_sudo.sh").read_text()
        self.assertIn("queue_install difftastic", setup_sudo)
        self.assertFalse((ROOT / "libexec/setup/fx-install.sh").exists())


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
            'case "$name:$*:${FAIL_MISE_INSTALL:-}" in mise:install*:1) exit 1;; esac\n'
            'case "$name:$*:${FAIL_OAUTH:-}" in mise:token\\ github\\ --oauth:1) exit 1;; esac\n'
            'if [ "$name" = mise ] && [ "${1:-}" = token ]; then\n'
            '  grep -q "oauth_client_id = \\"Iv23li0gR6P4iv8HXrsF\\"" "$MISE_GLOBAL_CONFIG_FILE" || exit 89\n'
            'fi\n'
            'if [ "$name" = mise ] && [ "${1:-}" = install ]; then\n'
            '  lock_dir=${MISE_GLOBAL_CONFIG_FILE%/*}\n'
            '  [ -f "$lock_dir/mise.lock" ] || exit 88\n'
            'fi\n'
            'case "$name:$*:${FAIL_PYTHON_INSTALL:-}" in mise:*python*:1|python:*:1|python3:*:1) exit 1;; esac\n'
        )
        recorder.chmod(0o755)
        for command in (
            "1password",
            "cargo",
            "clojure",
            "glide",
            "mise",
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
            PATH=f"{self.bin}:/usr/bin:/bin:/usr/sbin:/sbin",
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
            PATH=f"{self.bin}:/usr/bin:/bin:/usr/sbin:/sbin",
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

    def run_github_auth_helper(self, **overrides: str) -> subprocess.CompletedProcess[str]:
        source = (ROOT / "setup.sh").read_text()
        functions = source[: source.index("install_mise()")]
        env = os.environ.copy()
        env.pop("MISE_GITHUB_OAUTH_CLIENT_ID", None)
        env.update(
            HOME=str(self.home),
            INSTALL_COMMAND_LOG=str(self.log),
            MISE_SETUP_CONFIG=str(ROOT / "config/mise.toml"),
            PATH=f"{self.bin}:{env['PATH']}",
        )
        env.update(overrides)
        return subprocess.run(
            [
                "sh",
                "-c",
                functions
                + '\nexists() { command -v "$1" >/dev/null 2>&1; }\n'
                + "authenticate_mise_github\n",
            ],
            cwd=ROOT,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )

    def run_github_auth_offer(
        self, answer: str, **overrides: str
    ) -> subprocess.CompletedProcess[str]:
        source = (ROOT / "setup.sh").read_text()
        functions = source[: source.index("install_mise()")]
        env = os.environ.copy()
        env.pop("MISE_GITHUB_OAUTH_CLIENT_ID", None)
        env.update(
            HOME=str(self.home),
            INSTALL_COMMAND_LOG=str(self.log),
            MISE_SETUP_CONFIG=str(ROOT / "config/mise.toml"),
            PATH=f"{self.bin}:{env['PATH']}",
            SETUP_INTERACTIVE="1",
        )
        env.update(overrides)
        return subprocess.run(
            [
                "sh",
                "-c",
                functions
                + '\nexists() { command -v "$1" >/dev/null 2>&1; }\n'
                + "offer_mise_github_oauth\n",
            ],
            cwd=ROOT,
            env=env,
            input=answer,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_installs_user_tools_and_aliases(self) -> None:
        result = self.run_install()

        self.assertEqual(0, result.returncode, result.stderr)
        commands = self.commands()
        self.assertIn(["mise", "install", "--yes"], commands)
        self.assertFalse(any("binstall" in command for command in commands))
        fish_scripts = [command[2] for command in commands if command[0] == "fish"]
        self.assertTrue(
            any("fisher install jorgebucaran/fisher" in script for script in fish_scripts)
        )
        self.assertTrue(
            any("fisher install icezyclon/zoxide.fish" in script for script in fish_scripts)
        )
        self.assertFalse((ROOT / "install/fish.txt").exists())
        if InstallationTests.platform()["ID"] == "alpine":
            self.assertIn(
                [
                    "python3",
                    "-m",
                    "pip",
                    "install",
                    "--quiet",
                    "--break-system-packages",
                    "-r",
                    "install/python.txt",
                ],
                commands,
            )
        else:
            self.assertIn(
                [
                    "mise",
                    "exec",
                    "--",
                    "python",
                    "-m",
                    "pip",
                    "install",
                    "--quiet",
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

    def test_bootstraps_mise_when_it_is_not_installed(self) -> None:
        (self.bin / "mise").unlink()
        curl = self.bin / "curl"
        curl.write_text(
            "#!/bin/sh\n"
            "printf '%s\\n' "
            "'mkdir -p \"$HOME/.local/bin\"; "
            "ln -sf \"$MISE_TEST_BINARY\" \"$HOME/.local/bin/mise\"'\n"
        )
        curl.chmod(0o755)

        result = self.run_install_with(MISE_TEST_BINARY=str(self.bin / "recorder"))

        self.assertEqual(0, result.returncode, result.stderr)
        mise = self.home / ".local/bin/mise"
        self.assertTrue(mise.is_symlink(), mise)
        self.assertIn(["mise", "install", "--yes"], self.commands())

    def test_download_uses_wget_when_curl_is_not_installed(self) -> None:
        (self.bin / "curl").unlink()
        wget = self.bin / "wget"
        wget.write_text(
            "#!/bin/sh\n"
            'printf "downloaded\\n" > "$2"\n'
        )
        wget.chmod(0o755)
        output = self.directory / "download"
        env = os.environ.copy()
        env.update(HOME=str(self.home), PATH=str(self.bin))

        result = subprocess.run(
            [
                "/bin/sh",
                "-c",
                f'. ./lib/shell/lib.sh; download https://mise.run "{output}"',
            ],
            cwd=ROOT,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("downloaded\n", output.read_text())

    def test_failed_mise_download_stops_before_running_mise(self) -> None:
        (self.bin / "mise").unlink()
        curl = self.bin / "curl"
        curl.write_text("#!/bin/sh\nexit 1\n")

        result = self.run_install()

        self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertFalse(self.log.exists())

    def test_installs_all_declarative_tools_in_one_mise_command(self) -> None:
        result = self.run_install()

        self.assertEqual(0, result.returncode, result.stderr)
        commands = self.commands()
        self.assertEqual(1, commands.count(["mise", "install", "--yes"]))

    def test_checks_github_auth_before_installing_tools(self) -> None:
        result = self.run_install()

        self.assertEqual(0, result.returncode, result.stderr)
        commands = self.commands()
        auth_check = commands.index(["mise", "token", "github"])
        all_tools_install = commands.index(["mise", "install", "--yes"])
        self.assertLess(auth_check, all_tools_install)

    def test_mise_install_uses_runtime_config_and_lockfile(self) -> None:
        setup = (ROOT / "setup.sh").read_text()

        self.assertIn("MISE_SETUP_CONFIG=$PWD/config/mise.toml", setup)
        self.assertNotIn("MISE_SETUP_DIR", setup)
        self.assertNotIn("sed '/^\"cargo:/d'", setup)
        self.assertNotIn("MISE_GLOBAL_CONFIG_FILE=/dev/null mise install", setup)
        self.assertNotIn("gh auth token", setup)
        self.assertNotIn("export GITHUB_TOKEN", setup)

    def test_github_auth_uses_native_mise_oauth_without_exporting_token(self) -> None:
        setup = (ROOT / "setup.sh").read_text()

        self.assertIn("mise token github --oauth", setup)
        self.assertNotIn("gh auth login", setup)
        self.assertIn("Authenticate mise with GitHub to avoid API rate limits?", setup)
        self.assertNotIn("export GITHUB_TOKEN", setup)

    def test_github_auth_helper_uses_native_mise_oauth(self) -> None:
        result = self.run_github_auth_helper()

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual([["mise", "token", "github", "--oauth"]], self.commands())

    def test_menu_interactivity_offers_oauth_without_a_tty(self) -> None:
        result = self.run_github_auth_offer("y\n")

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("Authenticate mise with GitHub", result.stdout)
        self.assertEqual(
            [
                ["mise", "token", "github"],
                ["mise", "token", "github", "--oauth"],
            ],
            self.commands(),
        )

    def test_declining_oauth_warns_about_anonymous_rate_limits(self) -> None:
        result = self.run_github_auth_offer("n\n")

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("GitHub authentication skipped (declined by user)", result.stderr)
        self.assertIn("anonymous API rate limit", result.stderr)
        self.assertEqual([["mise", "token", "github"]], self.commands())

    def test_noninteractive_install_warns_when_auth_is_skipped(self) -> None:
        result = self.run_install_with(CI="1")

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("GitHub authentication skipped (setup is noninteractive)", result.stderr)
        self.assertIn("anonymous API rate limit", result.stderr)

    def test_oauth_warning_explains_when_stdin_reaches_eof(self) -> None:
        result = self.run_github_auth_offer("")

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("no response was available on stdin", result.stderr)

    def test_oauth_warning_explains_when_login_fails(self) -> None:
        result = self.run_github_auth_offer("y\n", FAIL_OAUTH="1")

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("OAuth login failed", result.stderr)

    def test_alpine_setup_omits_node_and_npm_tools(self) -> None:
        setup = (ROOT / "setup.sh").read_text()

        self.assertIn("if exists apk; then", setup)
        self.assertIn("MISE_DISABLE_TOOLS='node,python,aqua:pnpm/pnpm", setup)
        self.assertIn("aqua:Wilfred/difftastic'", setup)
        self.assertNotIn("MISE_SETUP_CONFIG.alpine", setup)

    def test_setup_delegates_cargo_tools_to_mise(self) -> None:
        setup = (ROOT / "setup.sh").read_text()
        with (ROOT / "config/mise.toml").open("rb") as config_file:
            config = tomllib.load(config_file)

        self.assertNotIn("cargo binstall", setup)
        self.assertIs(True, config["settings"]["cargo"]["binstall_only"])

    def test_user_tools_no_longer_bootstrap_homebrew(self) -> None:
        setup = (ROOT / "setup.sh").read_text()
        setup_sudo = (ROOT / "libexec/setup/setup_sudo.sh").read_text()

        self.assertFalse((ROOT / "install/brew_packages.txt").exists())
        self.assertNotIn("Homebrew/install", setup_sudo)
        self.assertNotIn("brew_packages", setup_sudo)
        self.assertNotIn("clojure/brew-install", setup)

    def test_alpine_local_install_requires_rust_runtime_library(self) -> None:
        setup = (ROOT / "setup.sh").read_text()

        self.assertIn("exists apk && ! [ -e /usr/lib/libgcc_s.so.1 ]", setup)
        self.assertIn("run setup option 7 or 9 first", setup)

    def test_alpine_global_install_explicitly_installs_libgcc(self) -> None:
        setup_sudo = (ROOT / "libexec/setup/setup_sudo.sh").read_text()

        self.assertIn("apk add bash less libgcc py3-pip shadow zsh", setup_sudo)

    def test_direct_local_and_all_setups_allow_interactive_oauth(self) -> None:
        setup = (ROOT / "setup.sh").read_text()

        self.assertIn("all|9|install-local|l*|6)", setup)
        self.assertIn('SETUP_NONINTERACTIVE:-', setup)
        self.assertIn("SETUP_INTERACTIVE=1", setup)

    def test_python_install_failure_makes_install_local_fail(self) -> None:
        result = self.run_install_with(FAIL_PYTHON_INSTALL="1")

        self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)

    def test_mise_install_failure_stops_install_local(self) -> None:
        result = self.run_install_with(FAIL_MISE_INSTALL="1")

        self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertEqual(
            [["mise", "token", "github"], ["mise", "install", "--yes"]],
            self.commands(),
        )

    def test_local_install_can_run_twice(self) -> None:
        first = self.run_install_with(CI="1")
        second = self.run_install_with(CI="1")

        self.assertEqual(0, first.returncode, first.stderr)
        self.assertEqual(0, second.returncode, second.stderr)
        self.assertEqual(2, self.commands().count(["mise", "install", "--yes"]))

class MiseConfigTests(unittest.TestCase):
    def test_runtime_contract_is_declared_in_global_config(self) -> None:
        with (ROOT / "config/mise.toml").open("rb") as config_file:
            config = tomllib.load(config_file)

        tools = config["tools"]
        self.assertEqual("lts", tools["node"])
        self.assertEqual("latest", tools["python"])
        self.assertEqual("latest", tools["uv"])
        self.assertEqual("nightly", tools["rust"]["version"])
        self.assertEqual("minimal", tools["rust"]["profile"])
        self.assertEqual(
            {"rustfmt", "clippy", "rust-analyzer", "miri"},
            set(tools["rust"]["components"]),
        )
        self.assertNotIn("idiomatic_version_file_enable_tools", config.get("settings", {}))

        cargo_tools = {
            "bacon",
            "broot",
            "cargo-audit",
            "cargo-outdated",
            "cargo-sweep",
            "counts",
            "librespot",
            "mdbook",
        }
        aqua_tools = {
            "LuaLS/lua-language-server",
            "cargo-bins/cargo-binstall",
            "antonmedv/fx",
            "Wilfred/difftastic",
            "Byron/dua-cli",
            "BurntSushi/ripgrep",
            "Myriad-Dreamin/tinymist",
            "mvdan/sh",
            "pnpm/pnpm",
        }
        npm_tools = {
            "perlnavigator-server",
            "bash-language-server",
            "typescript-language-server",
            "oxlint",
            "vscode-langservers-extracted",
        }
        pipx_tools = {"git-revise", "pytest", "pylint", "yt-dlp"}
        github_tools = {"clojure-lsp/clojure-lsp", "glide-browser/glide"}
        asdf_tools = {"mise-plugins/mise-clojure"}
        self.assertEqual(cargo_tools, self.backend_packages(tools, "cargo"))
        for cargo_tool in cargo_tools:
            self.assertEqual(
                ["rust", "aqua:cargo-bins/cargo-binstall"],
                tools[f"cargo:{cargo_tool}"]["depends"],
            )
        self.assertEqual(
            {
                "version": "rev:a0e7ebe7b037e822c506fcf6308055f8eecfb48a",
                "crate": "jj-cli",
                "bin": "jj",
                "depends": ["rust"],
            },
            tools["cargo:https://github.com/jj-vcs/jj"],
        )
        self.assertEqual(aqua_tools, self.backend_packages(tools, "aqua"))
        self.assertEqual(npm_tools, self.backend_packages(tools, "npm"))
        self.assertEqual(pipx_tools, self.backend_packages(tools, "pipx"))
        self.assertEqual(
            "--with pytest-xdist --with pytest-sugar --with pytest-instafail",
            tools["pipx:pytest"]["uvx_args"],
        )
        self.assertEqual(github_tools, self.backend_packages(tools, "github"))
        self.assertEqual(asdf_tools, self.backend_packages(tools, "asdf"))
        self.assertEqual(
            {"version": "latest", "os": ["linux"], "filter_bins": "glide"},
            tools["github:glide-browser/glide"],
        )
        self.assertEqual("pnpm", config["settings"]["npm"]["package_manager"])
        self.assertIs(True, config["settings"]["cargo"]["binstall"])
        self.assertIs(True, config["settings"]["cargo"]["binstall_only"])
        self.assertIs(True, config["settings"]["lockfile"])
        self.assertIs(True, config["settings"]["locked"])
        self.assertIs(True, config["settings"]["github"]["use_git_credentials"])
        self.assertEqual(
            "Iv23li0gR6P4iv8HXrsF", config["settings"]["github"]["oauth_client_id"]
        )
        self.assertNotIn("credential_command", config["settings"]["github"])
        self.assertEqual(
            "GITHUB_TOKEN", config["settings"]["github"]["oauth_export_env"]
        )
        self.assertFalse((ROOT / "install/rust.txt").exists())
        self.assertIn(
            "ruamel.yaml", (ROOT / "install/python.txt").read_text().splitlines()
        )

        cargo_config = tomllib.loads((ROOT / "config/cargo.toml").read_text())
        self.assertEqual(
            [
                "cargo:token",
                "cargo:libsecret",
                "cargo:macos-keychain",
                "cargo:wincred",
            ],
            cargo_config["registry"]["global-credential-providers"],
        )

    def test_lockfile_covers_every_declared_tool(self) -> None:
        with (ROOT / "config/mise.toml").open("rb") as config_file:
            config = tomllib.load(config_file)
        with (ROOT / "config/mise.lock").open("rb") as lock_file:
            lock = tomllib.load(lock_file)

        self.assertEqual(set(config["tools"]), set(lock["tools"]))
        for tool, resolutions in lock["tools"].items():
            self.assertTrue(resolutions, tool)
            self.assertTrue(all("version" in resolution for resolution in resolutions), tool)

    def test_system_and_mise_package_manifests_do_not_overlap(self) -> None:
        system_packages = {
            line
            for line in (ROOT / "install/packages.txt").read_text().splitlines()
            if line and not line.lstrip().startswith("#")
        }
        with (ROOT / "config/mise.toml").open("rb") as config_file:
            tools = tomllib.load(config_file)["tools"]

        mise_packages = {
            self.mise_package_name(tool, options) for tool, options in tools.items()
        }
        aliases = {"fd-find": "fd", "git-delta": "delta"}
        system_commands = {aliases.get(package, package) for package in system_packages}

        self.assertEqual(set(), system_commands & mise_packages)

    def test_dotbot_installs_mise_lock_beside_config(self) -> None:
        install = json.loads((ROOT / "install.conf.json").read_text())
        links = next(section["link"] for section in install if "link" in section)

        self.assertEqual("config/mise.toml", links["$HOME/.config/mise/config.toml"])
        self.assertEqual("config/mise.lock", links["$HOME/.config/mise/mise.lock"])

    @staticmethod
    def backend_packages(tools: dict[str, object], backend: str) -> set[str]:
        prefix = f"{backend}:"
        return {
            name.removeprefix(prefix)
            for name in tools
            if name.startswith(prefix) and "://" not in name
        }

    @staticmethod
    def mise_package_name(tool: str, options: object) -> str:
        if isinstance(options, dict):
            configured_bin = options.get("bin") or options.get("filter_bins")
            if isinstance(configured_bin, str):
                return configured_bin

        package = tool.split(":", 1)[-1].rsplit("/", 1)[-1]
        aliases = {"dua-cli": "dua", "ripgrep": "rg"}
        return aliases.get(package, package)

    def test_fish_activates_mise_and_no_longer_uses_nvm(self) -> None:
        fish_config = (ROOT / "config/config.fish").read_text()
        install = json.loads((ROOT / "install.conf.json").read_text())
        links = next(section["link"] for section in install if "link" in section)

        self.assertIn("source_init mise activate fish", fish_config)
        self.assertIn("source_init atuin init fish --disable-up-arrow", fish_config)
        self.assertIn("source_init zoxide init fish", fish_config)
        self.assertIn("source_init direnv hook fish", fish_config)
        self.assertIn(
            "set --erase MISE_SHELL __MISE_DIFF __MISE_SESSION __MISE_ORIG_PATH",
            fish_config,
        )
        self.assertIn(
            'contains --index -- "$HOME/.local/share/mise/shims" $PATH', fish_config
        )
        self.assertEqual(
            "config/mise-activate.fish",
            links["$HOME/.config/fish/conf.d/mise-activate.fish"],
        )
        self.assertNotIn("nvm use", fish_config)

    def test_shell_startup_guards_optional_tools_and_formats_durations_plainly(self) -> None:
        fish_config = (ROOT / "config/config.fish").read_text()
        fish_z = (ROOT / "config/z.fish").read_text()
        bashrc = (ROOT / "config/bashrc").read_text()
        zshrc = (ROOT / "config/zshrc").read_text()
        keybindings = (ROOT / "config/keybindings.ahk").read_text()
        inputrc = (ROOT / "config/inputrc").read_text()
        abbreviations = (ROOT / "lib/abbr.txt").read_text().splitlines()
        pre_commit = (ROOT / "config/githooks/pre-commit").read_text()
        pre_commit_driver = (
            ROOT / "tools/git-hooks/git_hooks/pre_commit.py"
        ).read_text()
        tmux = (ROOT / "config/tmux.conf").read_text()

        self.assertIn("prompt-command fish-left $last_status $duration $fish_name", fish_config)
        self.assertIn(
            "prompt-command fish-right 0 $duration $prompt_timestamp", fish_config
        )
        self.assertIn("set -l render_statuses $pipestatus", fish_config)
        self.assertNotIn('math --scale=2 "$duration / 1000"', fish_config)
        self.assertIn("if [ -f ~/.local/lib/fzf-tab-completion", bashrc)
        self.assertIn("if exists atuin; then", bashrc)
        self.assertGreaterEqual(zshrc.count("if exists atuin; then"), 2)
        self.assertIn("if exists direnv; then", zshrc)
        self.assertIn("if exists bat; and string match", fish_config)
        self.assertIn("if exists atuin\n\t\tsource_init atuin", fish_config)
        self.assertIn("if exists zoxide\n\t\tsource_init zoxide", fish_config)
        self.assertIn('if [ -z "${MY_GITHUB:-}" ]; then', bashrc)
        self.assertIn("zoxide_init=$(zoxide init bash) || {", bashrc)
        self.assertIn("zoxide_init=$(zoxide init zsh) || {", zshrc)
        self.assertIn("jj_completion=$(jj util completion bash) || return", bashrc)
        self.assertNotIn("source <(jj util completion bash)", bashrc)
        self.assertIn('source "$ZDOTDIR/antidote/antidote.zsh" || return', zshrc)
        self.assertIn("set keyseq-timeout 100", inputrc)
        self.assertNotIn("set keyseq-timeout 1\n", inputrc)
        self.assertLess(
            inputrc.index("$include /etc/inputrc"),
            inputrc.index("set keyseq-timeout"),
        )
        abbreviation_names = [
            line.partition("=")[0] for line in abbreviations if "=" in line
        ]
        self.assertEqual(len(abbreviation_names), len(set(abbreviation_names)))
        self.assertIn("t=tmux", abbreviations)
        self.assertIn("zmodload -i zsh/termcap || return", zshrc)
        self.assertIn('bindkey "\\e[3;3~" delete-word', zshrc)
        self.assertNotIn('bindkey "3~" delete-word', zshrc)
        self.assertIn('if [ -z "${DOTFILES:-}" ]; then', zshrc)
        self.assertIn("antidote load || return", zshrc)
        self.assertIn("atuin_init=$(atuin init zsh --disable-up-arrow) || {", zshrc)
        self.assertIn("direnv_init=$(direnv hook zsh) || {", zshrc)
        self.assertIn("atuin_init=$(atuin init bash --disable-up-arrow) || {", bashrc)
        self.assertIn("direnv_init=$(direnv hook bash) || {", bashrc)
        self.assertIn("dircolors_init=$(dircolors -b) || {", zshrc)
        for variable in (
            "zoxide_init",
            "atuin_init",
            "direnv_init",
            "dircolors_init",
            "atuin_completions",
            "jj_completion",
        ):
            self.assertIn(f"unset {variable}", bashrc + zshrc)
        self.assertIn("set abbreviations (grep -Ev", fish_config)
        self.assertIn("set git_aliases (git config --get-regexp", fish_config)
        self.assertIn('if [ -z "$old_fish" ]; and exists cargo', fish_config)
        self.assertIn("return $cargo_cache_status", fish_config)
        self.assertIn("if exists bat\n\tfunction cat", fish_config)
        self.assertIn(
            'set -l directory (command fork-github $argv)\n'
            '\t\tor return\n\t[ -n "$directory" ]',
            fish_config,
        )
        self.assertEqual(3, fish_config.count("printf '%s\\n' \"$history["))
        self.assertNotIn("echo $history[", fish_config)
        self.assertIn("abbr --add --global $name $value\n\tor return", fish_config)
        self.assertIn('source ~/.profile || return', bashrc)
        self.assertIn('. ~/.profile\n  profile_status=$?', zshrc)
        self.assertIn('emulate zsh\n  if [ "$profile_status" -ne 0 ]', zshrc)
        self.assertIn('source ~/.local/bashrc || return', bashrc)
        self.assertIn('fzf-bash-completion.sh || return', bashrc)
        self.assertIn("set -l profile_path (realpath ~/.profile); or return", fish_config)
        self.assertIn("set -l kernel (uname); or return", fish_config)
        self.assertIn("if not status --is-interactive\n\treturn\nend", fish_config)
        self.assertNotIn("if not status --is-interactive\n\texit", fish_config)
        self.assertNotIn('"(uname)"', fish_config)
        self.assertIn("if exists cargo; then", bashrc)
        self.assertIn("complete_alias c cargo || return", bashrc)
        self.assertIn("if exists git; then", bashrc)
        self.assertIn("complete_alias g git || return", bashrc)
        self.assertIn("complete_alias cd z || return", bashrc)
        self.assertIn("compinit -C || return", zshrc)
        self.assertIn("set -l results (command zoxide query", fish_z)
        self.assertIn('b"pre_commit_hooks/check_xml.py"', pre_commit_driver)
        self.assertIn('path.endswith(b".xml")', pre_commit_driver)
        self.assertIn('b"pre_commit_hooks/check_yaml.py"', pre_commit_driver)
        self.assertIn('path.endswith((b".yaml", b".yml"))', pre_commit_driver)
        self.assertIn(". ~/.local/profile.fish\n\tor return", fish_config)
        self.assertIn(". $DOTFILES/lib/shell/env.sh; or return", fish_config)
        self.assertIn(". $DOTFILES/lib/shell/paths.sh; or return", fish_config)
        self.assertIn("refresh-fish-cache --destination $brew_cache --dependency $brew_command", fish_config)
        self.assertIn("contains $brew_status 0 75; or return $brew_status", fish_config)
        self.assertIn(". $brew_cache; or return", fish_config)
        self.assertIn(". /usr/share/bash-completion/bash_completion || return", bashrc)
        self.assertIn(". /etc/bash_completion || return", bashrc)
        for line in zshrc.splitlines():
            if line.lstrip().startswith("zsh-defer "):
                self.assertTrue("|| return" in line or "|| {" in line, line)
        self.assertIn("setopt localoptions pipefail", zshrc)
        self.assertIn("fd --print0 | fzf --read0 --print0", zshrc)
        self.assertIn('selected=("${(@0)output}")', zshrc)
        self.assertNotIn("files=$(fd)", zshrc)
        self.assertIn("fd --print0 | fzf_action --read0 --print0", fish_config)
        self.assertIn("printf '%s\\0' \"$selection\" | picker-action copy --read0", fish_config)
        self.assertNotIn("printf %s $selection | copy", fish_config)
        self.assertIn("read --null --line key selection", fish_config)
        self.assertIn("set -l statuses $pipestatus", fish_config)
        self.assertIn("bind -M insert alt-t fzf_file_action", fish_config)
        self.assertNotIn("'fd | fzf_action'", fish_config)
        self.assertIn("set -l startup_status $status", fish_config)
        self.assertIn("return $startup_status\nend\nreturn 0", fish_config)
        self.assertIn("set --local init_output (command $argv)", fish_config)
        self.assertNotIn("command $argv | source", fish_config)
        self.assertNotIn("if . $pending_cache", fish_config)
        self.assertNotIn("command mv $pending_cache", fish_config)
        self.assertIn("--dependency $cargo_abbr_command", fish_config)
        self.assertIn("contains $cargo_cache_status 0 75; or return $cargo_cache_status", fish_config)
        self.assertIn(". $cargo_alias_cache; or return", fish_config)
        self.assertIn("Run 'wt.exe'", keybindings)
        self.assertNotIn("RunWait 'wt.exe'", keybindings)
        self.assertIn('"\\C-l": forward-word', inputrc)
        self.assertNotIn('"\\Cl": forward-word', inputrc)
        self.assertTrue(pre_commit.startswith("#!/usr/bin/env python3\n"))
        self.assertIn('ROOT / "tools/git-hooks"', pre_commit)
        self.assertIn("from git_hooks.pre_commit import main", pre_commit)
        self.assertIn('b"pre_commit_hooks/check_symlinks.py"', pre_commit_driver)
        self.assertIn('b"pre_commit_hooks/destroyed_symlinks.py"', pre_commit_driver)
        self.assertIn("os.path.realpath(path)", pre_commit_driver)
        self.assertNotIn("xargs", pre_commit)
        self.assertNotIn("while read", pre_commit)
        self.assertNotIn('printf -v path %q "$1"', tmux)
        self.assertIn("picker-action edit --read0", tmux)
        self.assertIn("picker-action open -- #{q:mouse_hyperlink}", tmux)
        self.assertNotIn('send-keys "${EDITOR:-vi} {}"', tmux)
        self.assertIn("SSH_AGENT_PID", tmux)
        self.assertNotIn("SSH_AUTH_PID", tmux)

    def test_setup_no_longer_installs_glide_imperatively(self) -> None:
        setup = (ROOT / "setup.sh").read_text()

        self.assertNotIn("glide-browser/glide/releases", setup)

    def test_claude_settings_are_valid_json(self) -> None:
        settings = json.loads((ROOT / "config/claude.json").read_text())

        self.assertEqual("opus", settings["model"])

    def test_kitty_disables_automatic_shell_integration(self) -> None:
        kitty = (ROOT / "config/kitty.conf").read_text()
        bash = (ROOT / "config/bashrc").read_text()
        fish = (ROOT / "config/config.fish").read_text()
        zsh = (ROOT / "config/zshrc").read_text()

        self.assertIn("\nshell_integration disabled\n", kitty)
        self.assertNotIn("#shell_integration disabled", kitty)
        self.assertIn("# XF86Cut (0x1008ff58), treated as another copy key", kitty)
        self.assertIn('source "$KITTY_INSTALLATION_DIR/shell-integration/bash/kitty.bash"', bash)
        self.assertIn(
            'source "$KITTY_INSTALLATION_DIR/shell-integration/fish/vendor_conf.d/kitty-shell-integration.fish"',
            fish,
        )
        self.assertIn(
            'autoload -Uz -- "$KITTY_INSTALLATION_DIR"/shell-integration/zsh/kitty-integration',
            zsh,
        )
        self.assertIn("export KITTY_SHELL_INTEGRATION=enabled", bash)
        self.assertIn("set --global KITTY_SHELL_INTEGRATION enabled", fish)
        self.assertIn("export KITTY_SHELL_INTEGRATION=enabled", zsh)


if __name__ == "__main__":
    unittest.main()
