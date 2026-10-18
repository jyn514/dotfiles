"""Runtime packaging uses npm's dependency graph and published package contents."""

import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[3]
STAGE = ROOT / "tools/codex-sandbox/image/stage-pi-runtime.mjs"


@unittest.skipUnless(shutil.which("node") and shutil.which("npm"), "Node and npm required")
class PiRuntimeStagingTest(unittest.TestCase):
    def test_production_graph_keeps_assets_and_workspace_links_without_build_inputs(self):
        with tempfile.TemporaryDirectory() as directory:
            built = Path(directory) / "built"
            source = built / "src"
            source.mkdir(parents=True)
            (built / "REVISION").write_text("fixture-revision\n")
            (source / "package.json").write_text(json.dumps({
                "name": "runtime-fixture", "version": "1.0.0",
                "private": True, "workspaces": ["packages/*"],
                "devDependencies": {"@fixture/compiler": "1.0.0"},
            }))

            def package(name, manifest, files):
                path = source / "packages" / name
                path.mkdir(parents=True)
                (path / "package.json").write_text(json.dumps({
                    "name": f"@fixture/{name}", "version": "1.0.0", "type": "module",
                    "main": "dist/index.js", "files": ["dist", "docs", "examples"],
                    # Packing must never run package lifecycle scripts.
                    "scripts": {"prepack": "exit 1"}, **manifest,
                }))
                for filename, contents in files.items():
                    file = path / filename
                    file.parent.mkdir(parents=True, exist_ok=True)
                    file.write_text(contents)
                return path

            external = source / "external"
            external.mkdir()
            (external / "package.json").write_text(json.dumps({
                "name": "@fixture/external", "version": "1.0.0", "type": "module",
                "main": "index.js", "bin": {"runtime-helper": "cli.js"},
            }))
            (external / "index.js").write_text("export const external = 7;\n")
            (external / "cli.js").write_text("#!/usr/bin/env node\nconsole.log('runtime-helper-ok');\n")
            (external / "cli.js").chmod(0o755)
            subprocess.run([
                "npm", "pack", "--ignore-scripts", "--pack-destination", str(source),
            ], cwd=external, check=True, capture_output=True, text=True)
            agent = package("coding-agent", {"dependencies": {
                "@fixture/runtime": "1.0.0", "@fixture/external": "file:../../fixture-external-1.0.0.tgz",
            }, "devDependencies": {"@fixture/compiler": "1.0.0"}}, {
                "dist/index.js": "export { value } from '@fixture/runtime';\n"
                                 "export { external } from '@fixture/external';\n",
                "dist/pi": "binary fixture",
                "docs/usage.md": "runtime documentation",
                "examples/extension.ts": "runtime example",
                "src/index.ts": "uncompiled source",
                "test/example.js": "test fixture",
            })
            package("runtime", {}, {"dist/index.js": "export const value = 42;\n"})
            package("compiler", {}, {"dist/index.js": "throw Error('build-only');\n"})
            package("unrelated", {}, {"dist/index.js": "throw Error('unrelated');\n"})
            subprocess.run([
                "npm", "install", "--ignore-scripts", "--offline", "--no-audit", "--no-fund",
            ], cwd=source, check=True, capture_output=True, text=True)

            # Changing the package's published file list needs no staging-code edit.
            for include_asset in (False, True):
                with self.subTest(include_asset=include_asset):
                    if include_asset:
                        manifest = json.loads((agent / "package.json").read_text())
                        manifest["files"].append("extra-runtime.json")
                        (agent / "package.json").write_text(json.dumps(manifest))
                        (agent / "extra-runtime.json").write_text("{}")
                    output = Path(directory) / f"runtime-{include_asset}"
                    staged_result = subprocess.run(["node", str(STAGE), str(built), str(output)],
                                                   capture_output=True, text=True)
                    self.assertEqual(0, staged_result.returncode, staged_result.stderr)
                    staged = output / "src/packages/coding-agent"
                    self.assertTrue((staged / "docs/usage.md").is_file())
                    self.assertTrue((staged / "examples/extension.ts").is_file())
                    self.assertEqual(include_asset, (staged / "extra-runtime.json").exists())
                    self.assertFalse((staged / "src").exists())
                    self.assertFalse((staged / "test").exists())
                    self.assertFalse((output / "src/node_modules/@fixture/compiler").exists())
                    self.assertFalse((output / "src/packages/unrelated").exists())
                    self.assertTrue((output / "standalone").is_symlink())
                    self.assertTrue((output / "standalone/pi").samefile(staged / "dist/pi"))
                    result = subprocess.run([
                        "node", "--input-type=module", "-e",
                        "import { value, external } from '@fixture/coding-agent'; console.log(value + external)",
                    ], cwd=output / "src", check=True, capture_output=True, text=True)
                    self.assertEqual("49\n", result.stdout)
                    helper = subprocess.run([str(output / "src/node_modules/.bin/runtime-helper")],
                                            check=True, capture_output=True, text=True)
                    self.assertEqual("runtime-helper-ok\n", helper.stdout)


if __name__ == "__main__":
    unittest.main()
