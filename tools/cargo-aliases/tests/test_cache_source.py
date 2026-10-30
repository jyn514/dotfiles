"""Exercise Cargo's cache owner and native Fish fast path in a disposable checkout."""

import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[3]
FISH = shutil.which("fish")


@unittest.skipUnless(FISH, "Fish is required")
class CargoCacheSourceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.checkout = self.directory / "checkout with spaces"
        for relative in (
            "config/config.fish", "bin/generate-cargo-fish-abbr",
            "tools/cargo-aliases/cargo_aliases/__init__.py",
            "tools/cargo-aliases/cargo_aliases/main.py",
        ):
            destination = self.checkout / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / relative, destination)
            os.utime(destination, ns=(1_000_000_000, 1_000_000_000))
        self.home = self.directory / "home"
        self.home.mkdir()
        self.commands = self.home / "bin"
        self.commands.mkdir()
        # The installed command is a symlink; the wrapper resolves its source
        # checkout before importing the renderer. Do not copy into real config.
        (self.commands / "generate-cargo-fish-abbr").symlink_to(
            self.checkout / "bin/generate-cargo-fish-abbr",
        )
        self.cargo = self.commands / "cargo"
        self.cargo.write_text(
            f"#!{sys.executable}\n"
            "import os, pathlib, sys\n"
            "with pathlib.Path(os.environ['CALLS']).open('a') as log:\n"
            "    log.write('cargo --list\\n')\n"
            "print('Installed Commands:\\n    build    Compile a package')\n"
            "raise SystemExit(int(os.environ.get('FAIL_CARGO', '0')))\n"
        )
        self.cargo.chmod(0o755)
        os.utime(self.cargo, ns=(1_000_000_000, 1_000_000_000))
        self.calls = self.directory / "calls"
        self.cache = self.home / ".local/config/cargo.fish"
        self.renderer = self.checkout / "tools/cargo-aliases/cargo_aliases/main.py"
        source = (self.checkout / "config/config.fish").read_text()
        # Use the actual cache owner, including the actual native fast path;
        # loading unrelated interactive config would obscure this dependency.
        refresher = "function refresh-fish-cache\n" + source.split(
            "function refresh-fish-cache\n", 1,
        )[1].split("\nif [ -f ~/.local/profile.fish ]", 1)[0]
        owner = source.split("# load cargo aliases\n", 1)[1].split("\nif exists bat", 1)[0]
        self.script = self.directory / "load.fish"
        self.script.write_text(
            "function exists; command --query $argv; end\n"
            "set -g old_fish ''\n" + refresher + "\n" + owner
            + "\nabbr --show cbuild\n"
        )
        self.environment = os.environ | {
            "HOME": str(self.home), "XDG_CONFIG_HOME": str(self.home / ".config"),
            "DOTFILES": str(self.checkout), "CARGO_HOME": str(self.directory / "cargo-home"),
            "PATH": f"{self.commands}:{ROOT / 'bin'}:{os.environ['PATH']}",
            "CALLS": str(self.calls), "PYTHONDONTWRITEBYTECODE": "1",
        }

    def load(self, **environment: str) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            [FISH, "--no-config", str(self.script)], env=self.environment | environment,
            cwd=self.directory, text=True, capture_output=True, timeout=10,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        return result

    def make_renderer_newer(self) -> None:
        self.renderer.write_text(self.renderer.read_text().replace(
            "fish_literal('cargo ' + command)", "fish_literal('cargo --color always ' + command)",
        ))
        os.utime(self.cache, ns=(2_000_000_000, 2_000_000_000))
        os.utime(self.renderer, ns=(3_000_000_000, 3_000_000_000))

    def test_renderer_edit_refreshes_cache_without_wrapper_or_config_edit(self) -> None:
        first = self.load()
        self.assertIn("'cargo build'", first.stdout)
        self.load()
        self.assertEqual(1, len(self.calls.read_text().splitlines()))
        self.make_renderer_newer()
        result = self.load()
        self.assertIn("'cargo --color always build'", result.stdout)
        self.assertEqual(2, len(self.calls.read_text().splitlines()))
        self.load()
        self.assertEqual(2, len(self.calls.read_text().splitlines()))

    def test_renderer_invalidation_keeps_last_good_cache_on_producer_failure(self) -> None:
        self.load()
        original = self.cache.read_bytes()
        self.make_renderer_newer()
        result = self.load(FAIL_CARGO="19")
        self.assertEqual(2, len(self.calls.read_text().splitlines()))
        self.assertIn("using previous cache", result.stderr)
        self.assertIn("'cargo build'", result.stdout)
        self.assertEqual(original, self.cache.read_bytes())


if __name__ == "__main__":
    unittest.main()
