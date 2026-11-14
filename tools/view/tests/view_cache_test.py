"""Exercise uv's real tool cache against a disposable copy of the view launcher."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[3]
TOOL = ROOT / "tools/view"


@unittest.skipUnless(shutil.which("uvx"), "requires uvx and package-index access")
class ViewCacheTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory(dir=os.environ.get("SANDBOX_WORK"))
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.checkout = self.directory / "checkout"
        for relative in ("bin/view", "lib/shell/lib.sh", "tools/view/pyproject.toml"):
            target = self.checkout / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / relative, target)
        self.package = self.checkout / "tools/view"
        shutil.copytree(
            TOOL / "src/dotfiles_metabrowser_rst",
            self.package / "src/dotfiles_metabrowser_rst",
            ignore=shutil.ignore_patterns("__pycache__"),
        )
        self.environment = os.environ | {
            "UV_CACHE_DIR": str(self.directory / "uv-cache"),
            "UV_TOOL_DIR": str(self.directory / "uv-tools"),
        }
        for name in ("UV_NO_CACHE", "UV_REFRESH", "UV_REINSTALL", "PYTHONPATH"):
            self.environment.pop(name, None)

    def installed_package(self) -> Path:
        result = subprocess.run(
            [str(self.checkout / "bin/view"), "--plugin", "rst", "--json"],
            cwd=self.directory,
            env=self.environment,
            capture_output=True,
            text=True,
            timeout=120,
        )
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        plugin = json.loads(result.stdout)["plugin"]
        installed = Path(plugin["static_root"]).parent
        self.assertFalse(installed.is_relative_to(self.package), installed)
        return installed

    def test_source_and_asset_edits_refresh_the_cached_tool(self) -> None:
        installed = self.installed_package()
        self.assertEqual(installed, self.installed_package(), "unchanged inputs should reuse the cache")
        source = self.package / "src/dotfiles_metabrowser_rst"
        for relative, marker in (
            ("plugin/styles.css", "\n/* cache regression: rst CSS */\n"),
            ("plugin/index.js", "\n/* cache regression: rst JS */\n"),
            ("plugin/manifest.toml", "\n# cache regression: manifest\n"),
            ("sidekick.py", "\n# cache regression: Python\n"),
            ("markdown_mermaid_plugin/styles.css", "\n/* cache regression: Markdown CSS */\n"),
            ("markdown_mermaid_plugin/index.js", "\n/* cache regression: Markdown JS */\n"),
        ):
            with self.subTest(relative=relative):
                target = source / relative
                target.write_text(target.read_text() + marker)
                installed = self.installed_package()
                self.assertEqual(target.read_bytes(), (installed / relative).read_bytes())
                self.assertEqual(installed, self.installed_package())


if __name__ == "__main__":
    unittest.main()
