#!/usr/bin/env python3

import os
import platform
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
            "cargo-outdated",
            "cargo-sweep",
            "cargo-tree",
            "difft",
            "dua",
            "rg",
            "jj",
            "mdbook",
            "tinymist",
            "pnpm",
            "perlnavigator",
            "bash-language-server",
            "typescript-language-server",
            "oxlint",
            "vscode-css-language-server",
            "git-revise",
            "pytest",
            "pylint",
            "yt-dlp",
        ]
        if platform.machine() not in {"aarch64", "arm64"}:
            commands.extend(("counts", "librespot"))
        script = "set -e; " + "; ".join(f"command -v {command}" for command in commands)

        self.assert_mise_command("sh", "-c", script)

    def test_python_libraries_import(self) -> None:
        self.assert_mise_command(
            "python",
            "-c",
            "import toml, tomli",
        )


if __name__ == "__main__":
    unittest.main()
