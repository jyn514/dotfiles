"""Runtime packaging keeps production packages and their inspectable workspace sources."""

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
    def test_production_graph_keeps_assets_sources_and_workspace_links_without_build_tools(self):
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
                "src/tools/edit.ts": "nested source",
                "test/example.js": "test fixture",
                "scripts/build.mjs": "build script",
                "tsconfig.json": "{}",
            })
            package("runtime", {"dependencies": {"@fixture/js-runtime": "1.0.0"}}, {
                "dist/index.js": "export const value = 42;\n",
                "src/index.ts": "export const value: number = 42;\n",
            })
            package("js-runtime", {}, {"dist/index.js": "export const js = true;\n"})
            package("compiler", {}, {
                "dist/index.js": "throw Error('build-only');\n", "src/index.ts": "build-only source",
            })
            package("unrelated", {}, {
                "dist/index.js": "throw Error('unrelated');\n", "src/index.ts": "unrelated source",
            })
            subprocess.run([
                "npm", "install", "--ignore-scripts", "--offline", "--no-audit", "--no-fund",
            ], cwd=source, check=True, capture_output=True, text=True)

            extensions = Path(directory) / "extensions"
            adapter = extensions / "node_modules/fixture-adapter"
            adapter.mkdir(parents=True)
            (extensions / "package.json").write_text(json.dumps({"dependencies": {"fixture-adapter": "1.0.0"}}))
            (adapter / "package.json").write_text(json.dumps({"name": "fixture-adapter", "type": "module",
                                                             "main": "index.js"}))
            (adapter / "index.js").write_text("export { external } from '@fixture/external';\n")
            extension_external = extensions / "node_modules/@fixture/external"
            extension_external.mkdir(parents=True)
            (extension_external / "package.json").write_text((external / "package.json").read_text())
            (extension_external / "index.js").write_text("export const external = 99;\n")

            # Changing the package's published file list needs no staging-code edit.
            for include_asset, omit_standalone in ((False, False), (False, True), (True, False), (True, True)):
                with self.subTest(include_asset=include_asset, omit_standalone=omit_standalone):
                    if include_asset and not (agent / "extra-runtime.json").exists():
                        manifest = json.loads((agent / "package.json").read_text())
                        manifest["files"].append("extra-runtime.json")
                        (agent / "package.json").write_text(json.dumps(manifest))
                        (agent / "extra-runtime.json").write_text("{}")
                    output = Path(directory) / f"runtime-{include_asset}-{omit_standalone}"
                    options = ["--omit-standalone"] if omit_standalone else []
                    staged_result = subprocess.run(["node", str(STAGE), str(built), str(output),
                                                    "--extensions", str(extensions), *options],
                                                   capture_output=True, text=True)
                    self.assertEqual(0, staged_result.returncode, staged_result.stderr)
                    staged = output / "src/packages/coding-agent"
                    self.assertTrue((staged / "docs/usage.md").is_file())
                    self.assertTrue((staged / "examples/extension.ts").is_file())
                    self.assertEqual(include_asset, (staged / "extra-runtime.json").exists())
                    self.assertEqual("uncompiled source", (staged / "src/index.ts").read_text())
                    self.assertEqual("nested source", (staged / "src/tools/edit.ts").read_text())
                    self.assertEqual("export const value: number = 42;\n",
                                     (output / "src/packages/runtime/src/index.ts").read_text())
                    self.assertTrue((output / "src/packages/js-runtime/dist/index.js").is_file())
                    self.assertFalse((output / "src/packages/js-runtime/src").exists())
                    self.assertFalse((staged / "test").exists())
                    self.assertFalse((staged / "scripts").exists())
                    self.assertFalse((staged / "tsconfig.json").exists())
                    self.assertFalse((output / "src/packages/compiler").exists())
                    self.assertFalse((output / "src/node_modules/@fixture/compiler").exists())
                    self.assertFalse((output / "src/packages/unrelated").exists())
                    self.assertTrue((output / "standalone").is_symlink())
                    self.assertEqual(not omit_standalone, (output / "standalone/pi").exists())
                    if not omit_standalone:
                        self.assertTrue((output / "standalone/pi").samefile(staged / "dist/pi"))
                    result = subprocess.run([
                        "node", "--input-type=module", "-e",
                        "import { value, external } from '@fixture/coding-agent'; console.log(value + external)",
                    ], cwd=output / "src", check=True, capture_output=True, text=True)
                    self.assertEqual("49\n", result.stdout)
                    adapter_result = subprocess.run([
                        "node", "--input-type=module", "-e",
                        "import { external } from 'fixture-adapter'; console.log(external)",
                    ], cwd=output / "src", check=True, capture_output=True, text=True)
                    self.assertEqual("99\n", adapter_result.stdout)
                    helper = subprocess.run([str(output / "src/node_modules/.bin/runtime-helper")],
                                            check=True, capture_output=True, text=True)
                    self.assertEqual("runtime-helper-ok\n", helper.stdout)

            (extensions / "package.json").write_text(json.dumps({
                "dependencies": {"@fixture/external": "2.0.0"},
            }))
            collision = subprocess.run(["node", str(STAGE), str(built), str(Path(directory) / "collision"),
                                        "--extensions", str(extensions)], capture_output=True, text=True)
            self.assertNotEqual(0, collision.returncode)
            self.assertIn("EEXIST", collision.stderr)


if __name__ == "__main__":
    unittest.main()
