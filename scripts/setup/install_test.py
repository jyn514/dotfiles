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

    def test_requests_platform_packages(self) -> None:
        platform = self.platform()

        results = [self.run_install(), self.run_install()]

        for result in results:
            self.assertEqual(0, result.returncode, result.stderr)
        commands = self.commands()
        packages = self.manifest("packages.txt")
        if platform["ID"] == "alpine":
            replacements = {
                "antidote": None,
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
            any("command cat install/fish.txt" in script for script in fish_scripts)
        )
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
                f'. ./lib/lib.sh; download https://mise.run "{output}"',
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
        self.assertIn("MISE_DISABLE_TOOLS='node,python,npm:pnpm", setup)
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
        setup_sudo = (ROOT / "lib/setup_sudo.sh").read_text()

        self.assertFalse((ROOT / "install/brew_packages.txt").exists())
        self.assertNotIn("Homebrew/install", setup_sudo)
        self.assertNotIn("brew_packages", setup_sudo)
        self.assertNotIn("clojure/brew-install", setup)

    def test_alpine_local_install_requires_rust_runtime_library(self) -> None:
        setup = (ROOT / "setup.sh").read_text()

        self.assertIn("exists apk && ! [ -e /usr/lib/libgcc_s.so.1 ]", setup)
        self.assertIn("run setup option 7 or 9 first", setup)

    def test_alpine_global_install_explicitly_installs_libgcc(self) -> None:
        setup_sudo = (ROOT / "lib/setup_sudo.sh").read_text()

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
            "cargo-tree",
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
            "jj-vcs/jj",
            "BurntSushi/ripgrep",
            "Myriad-Dreamin/tinymist",
            "mvdan/sh",
        }
        npm_tools = {
            "pnpm",
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
        self.assertEqual(aqua_tools, self.backend_packages(tools, "aqua"))
        self.assertEqual(npm_tools, self.backend_packages(tools, "npm"))
        self.assertEqual(pipx_tools, self.backend_packages(tools, "pipx"))
        self.assertEqual(github_tools, self.backend_packages(tools, "github"))
        self.assertEqual(asdf_tools, self.backend_packages(tools, "asdf"))
        self.assertEqual(
            {"version": "latest", "os": ["linux"], "filter_bins": "glide"},
            tools["github:glide-browser/glide"],
        )
        self.assertEqual("npm", config["settings"]["npm"]["package_manager"])
        self.assertIs(True, config["settings"]["cargo"]["binstall"])
        self.assertIs(True, config["settings"]["cargo"]["binstall_only"])
        self.assertIs(True, config["settings"]["lockfile"])
        self.assertIs(True, config["settings"]["locked"])
        self.assertIs(True, config["settings"]["github"]["use_git_credentials"])
        self.assertEqual(
            "Iv23li0gR6P4iv8HXrsF", config["settings"]["github"]["oauth_client_id"]
        )
        self.assertNotIn("credential_command", config["settings"]["github"])
        self.assertEqual("", config["settings"]["github"]["oauth_export_env"])
        self.assertFalse((ROOT / "install/rust.txt").exists())

    def test_lockfile_covers_every_declared_tool(self) -> None:
        with (ROOT / "config/mise.toml").open("rb") as config_file:
            config = tomllib.load(config_file)
        with (ROOT / "config/mise.lock").open("rb") as lock_file:
            lock = tomllib.load(lock_file)

        self.assertEqual(set(config["tools"]), set(lock["tools"]))
        for tool, resolutions in lock["tools"].items():
            self.assertTrue(resolutions, tool)
            self.assertTrue(all("version" in resolution for resolution in resolutions), tool)

    def test_dotbot_installs_mise_lock_beside_config(self) -> None:
        install = json.loads((ROOT / "install.conf.json").read_text())
        links = next(section["link"] for section in install if "link" in section)

        self.assertEqual("config/mise.toml", links["$HOME/.config/mise/config.toml"])
        self.assertEqual("config/mise.lock", links["$HOME/.config/mise/mise.lock"])

    @staticmethod
    def backend_packages(tools: dict[str, object], backend: str) -> set[str]:
        prefix = f"{backend}:"
        return {name.removeprefix(prefix) for name in tools if name.startswith(prefix)}

    def test_fish_activates_mise_and_no_longer_uses_nvm(self) -> None:
        fish_config = (ROOT / "config/config.fish").read_text()

        self.assertIn("mise activate fish | source", fish_config)
        self.assertNotIn("nvm use", fish_config)

    def test_setup_no_longer_installs_glide_imperatively(self) -> None:
        setup = (ROOT / "setup.sh").read_text()

        self.assertNotIn("glide-browser/glide/releases", setup)


if __name__ == "__main__":
    unittest.main()
