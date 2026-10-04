#!/usr/bin/env python3

import os
import platform
import shutil
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


@unittest.skipUnless(
    os.environ.get("RUN_MISE_SMOKE_TESTS") == "1",
    "set RUN_MISE_SMOKE_TESTS=1 after install-local",
)
class MiseSmokeTests(unittest.TestCase):
    def mise_exec(self, *command: str) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env["MISE_GLOBAL_CONFIG_FILE"] = str(ROOT / "config/mise.toml")
        env["MISE_AUTO_INSTALL"] = "0"
        return subprocess.run(
            ["mise", "exec", "--", *command],
            cwd=ROOT,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )

    def assert_mise_command(self, *command: str) -> str:
        result = self.mise_exec(*command)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        return result.stdout

    def test_runtime_commands_resolve(self) -> None:
        for command in ("node", "python", "rustc", "cargo"):
            with self.subTest(command=command):
                self.assert_mise_command(command, "--version")

    def test_required_rust_components_are_installed(self) -> None:
        output = self.assert_mise_command("rustup", "component", "list", "--installed")

        for component in ("rustfmt", "clippy", "rust-analyzer", "miri"):
            self.assertIn(component, output)

    def test_package_commands_resolve(self) -> None:
        commands = [
            "bacon",
            "broot",
            "cargo-audit",
            "cargo-binstall",
            "cargo-outdated",
            "cargo-sweep",
            "counts",
            "clojure",
            "clojure-lsp",
            "difft",
            "dua",
            "fx",
            "rg",
            "jj",
            "mdbook",
            "lua-language-server",
            "shfmt",
            "tinymist",
            "pnpm",
            "perlnavigator",
            "bash-language-server",
            "typescript-language-server",
            "oxlint",
            "vscode-css-language-server",
            "git-revise",
            "pylint",
            "yt-dlp",
        ]
        if platform.machine() not in {"aarch64", "arm64"}:
            commands.append("librespot")
        if platform.system() == "Linux":
            commands.append("glide-bin" if Path("/usr/bin/glide-bin").exists() else "glide")
        script = "set -e; " + "; ".join(f"command -v {command}" for command in commands)

        self.assert_mise_command("sh", "-c", script)
        self.assert_mise_command("cargo", "tree", "--help")

    def test_python_libraries_import(self) -> None:
        self.assert_mise_command(
            "python",
            "-c",
            "import toml, tomli",
        )

    @unittest.skipIf(platform.system() == "Windows", "Windows uses mise providers")
    def test_native_search_and_formatter_resolve_through_mise_exec(self) -> None:
        env = os.environ.copy()
        env.update(MISE_GLOBAL_CONFIG_FILE=str(ROOT / "config/mise.toml"),
                   MISE_AUTO_INSTALL="0")
        native_paths = ["/usr/bin", "/bin", "/usr/sbin", "/sbin"]
        if platform.system() == "Darwin":
            brew_prefix = subprocess.check_output(["brew", "--prefix"], text=True).strip()
            native_paths.insert(0, str(Path(brew_prefix) / "bin"))
        env["PATH"] = os.pathsep.join(native_paths)
        # An old mise installation must not make a missing native package pass.
        mise = shutil.which("mise")
        self.assertIsNotNone(mise)
        for command in ("rg", "shfmt"):
            with self.subTest(command=command):
                native = shutil.which(command, path=env["PATH"])
                self.assertIsNotNone(native, f"missing native {command}")
                result = subprocess.run(
                    [mise, "exec", "--", "sh", "-c", f"command -v {command}"],
                    cwd=ROOT, env=env, text=True, capture_output=True,
                )
                self.assertEqual(0, result.returncode, result.stdout + result.stderr)
                resolved = Path(result.stdout.strip()).resolve()
                self.assertEqual(Path(native).resolve(), resolved)


if __name__ == "__main__":
    unittest.main()
