import importlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import tomllib
import unittest


ROOT = Path(__file__).resolve().parents[3]
TOOL = ROOT / "tools" / "view"


class ViewCommandTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.bin = self.directory / "bin"
        self.bin.mkdir()
        self.capture = self.directory / "uvx.args"
        uvx = self.bin / "uvx"
        uvx.write_text(
            "#!/bin/sh\n"
            'for argument do printf "%s\\n" "$argument" >> "$CAPTURE"; done\n'
        )
        uvx.chmod(0o755)
        self.environment = os.environ | {
            "CAPTURE": str(self.capture),
            "PATH": f"{self.bin}:/usr/bin:/bin",
        }

    def run_view(self, *arguments: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
        return subprocess.run(
            [str(ROOT / "bin" / "view"), *arguments],
            cwd=self.directory,
            env=env or self.environment,
            capture_output=True,
            text=True,
        )

    def test_defaults_to_current_directory_and_pins_runtime(self) -> None:
        result = self.run_view()

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(
            [
                "--from",
                "metabrowser==0.12.0",
                "--with",
                str(TOOL),
                "metab",
                ".",
            ],
            self.capture.read_text().splitlines(),
        )

    def test_passes_metabrowser_arguments_through(self) -> None:
        result = self.run_view("notes & examples.rst", "--no-open")

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(
            [
                "--from",
                "metabrowser==0.12.0",
                "--with",
                str(TOOL),
                "metab",
                "notes & examples.rst",
                "--no-open",
            ],
            self.capture.read_text().splitlines(),
        )

    def test_missing_uvx_is_reported(self) -> None:
        realpath = shutil.which("realpath")
        self.assertIsNotNone(realpath)
        minimal_bin = self.directory / "minimal-bin"
        minimal_bin.mkdir()
        (minimal_bin / "realpath").symlink_to(realpath)

        result = self.run_view(env=os.environ | {"PATH": str(minimal_bin)})

        self.assertEqual(127, result.returncode)
        self.assertEqual("view requires uvx\n", result.stderr)


class PluginPackageTests(unittest.TestCase):
    def test_manifest_claims_rst_and_declares_both_views(self) -> None:
        with (TOOL / "src/dotfiles_metabrowser_rst/plugin/manifest.toml").open("rb") as file:
            manifest = tomllib.load(file)

        self.assertEqual("rst", manifest["plugin"]["name"])
        self.assertEqual("0.7", manifest["plugin"]["sdk_version"])
        self.assertEqual(
            [{"id": "rst", "match": {"ext": ".rst"}, "priority": 100}],
            manifest["kind"],
        )
        self.assertEqual(
            [("rendered", True), ("source", None)],
            [(view["id"], view.get("default")) for view in manifest["view"]],
        )
        self.assertEqual(
            "dotfiles_metabrowser_rst.sidekick:rendered_handler",
            manifest["data_hook"][0]["sidekick"],
        )

    def test_pyproject_pins_renderer_dependencies(self) -> None:
        with (TOOL / "pyproject.toml").open("rb") as file:
            pyproject = tomllib.load(file)

        self.assertEqual(
            ["docutils==0.23", "metabrowser==0.12.0"],
            pyproject["project"]["dependencies"],
        )
        self.assertEqual(
            "dotfiles_metabrowser_rst:plugin_dir",
            pyproject["project"]["entry-points"]["metabrowser.plugins"]["dotfiles-rst"],
        )

    def test_entry_point_returns_packaged_plugin_directory(self) -> None:
        sys.path.insert(0, str(TOOL / "src"))
        self.addCleanup(lambda: sys.path.remove(str(TOOL / "src")))
        module = importlib.import_module("dotfiles_metabrowser_rst")

        self.assertEqual(TOOL / "src/dotfiles_metabrowser_rst/plugin", module.plugin_dir())


if __name__ == "__main__":
    unittest.main()
