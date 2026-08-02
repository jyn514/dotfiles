import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[3]
COMMAND = ROOT / "bin/generate-cargo-fish-abbr"
sys.path.insert(0, str(ROOT / "tools/cargo-aliases"))
from cargo_aliases.main import fish_literal, render  # noqa: E402


class CargoAliasesTest(unittest.TestCase):
    def test_renders_commands_aliases_and_excluded_short_names(self) -> None:
        source = """Installed Commands:
    build                Compile a local package
    b                    alias: build --release
    c                    Check a package
    d                    alias: doc
"""

        self.assertEqual(
            """abbr --add --global 'cbuild' -- 'cargo build'
abbr --add --command cargo 'b' -- 'build --release'
abbr --add --global 'cb' -- 'cargo build --release'
abbr --add --command cargo 'd' -- 'doc'
""",
            render(source),
        )

    def test_fish_literals_preserve_quotes_backslashes_and_expansion_text(self) -> None:
        source = """Installed Commands:
    punctuation          alias: run -- '$value' \\ path && next
"""

        rendered = render(source)

        self.assertIn(fish_literal("run -- '$value' \\ path && next"), rendered)
        self.assertIn(fish_literal("cargo run -- '$value' \\ path && next"), rendered)

    def test_blank_lines_and_descriptionless_commands_are_supported(self) -> None:
        source = "Installed Commands:\n\n    lonely\n"

        self.assertEqual(
            "abbr --add --global 'clonely' -- 'cargo lonely'\n",
            render(source),
        )

    def test_cargo_failure_is_propagated_without_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            cargo = Path(temporary) / "cargo"
            cargo.write_text("#!/bin/sh\nprintf 'partial output\\n'\nexit 19\n")
            cargo.chmod(0o755)

            result = subprocess.run(
                [sys.executable, str(COMMAND), str(cargo)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env={"PATH": os.environ.get("PATH", "")},
                check=False,
            )

        self.assertEqual(19, result.returncode)
        self.assertEqual(b"", result.stdout)

    def test_missing_cargo_reports_command_failure(self) -> None:
        result = subprocess.run(
            [sys.executable, str(COMMAND), "/missing/cargo"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

        self.assertEqual(127, result.returncode)
        self.assertIn(b"could not run Cargo", result.stderr)


if __name__ == "__main__":
    unittest.main()
