"""Dependency staging preserves npm's workspace graph without source-only inputs."""

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[3]
STAGE = ROOT / "tools/codex-sandbox/image/stage-pi-dependencies.mjs"


@unittest.skipUnless(shutil.which("node") and shutil.which("npm"), "Node and npm required")
class PiDependencyStagingTest(unittest.TestCase):
    def test_locked_workspaces_install_without_sources_and_track_manifest_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source"
            source.mkdir()
            (source / "package.json").write_text(json.dumps({
                "name": "fixture-root", "private": True,
                "workspaces": ["packages/*", "packages/agent/examples/demo"],
            }))
            paths = ["packages/agent", "packages/runtime", "packages/agent/examples/demo"]
            for index, path in enumerate(paths):
                package = source / path
                package.mkdir(parents=True, exist_ok=True)
                (package / "package.json").write_text(json.dumps({
                    "name": f"fixture-workspace-{index}", "version": "1.0.0",
                    "scripts": {"preinstall": "exit 1"},
                }))
                (package / "source.ts").write_text("source-only input")
            (source / ".npmrc").write_text("ignore-scripts=true\n")
            subprocess.run(["npm", "install", "--package-lock-only", "--ignore-scripts",
                            "--offline", "--no-audit", "--no-fund"],
                           cwd=source, check=True, capture_output=True, text=True)
            (source / "REVISION").write_text("first-revision")

            def stage(name):
                output = Path(directory) / name
                subprocess.run(["node", str(STAGE), str(source), str(output)],
                               check=True, capture_output=True, text=True)
                snapshot = {str(path.relative_to(output)): hashlib.sha256(path.read_bytes()).hexdigest()
                            for path in output.rglob("*") if path.is_file()}
                return output, snapshot

            output, first = stage("first")
            self.assertEqual({"package-lock.json", "package.json", ".npmrc",
                              *[f"{path}/package.json" for path in paths]}, set(first))
            subprocess.run(["npm", "ci", "--ignore-scripts", "--offline", "--no-audit", "--no-fund"],
                           cwd=output, check=True, capture_output=True, text=True)
            for index, path in enumerate(paths):
                self.assertEqual((output / path).resolve(),
                                 (output / f"node_modules/fixture-workspace-{index}").resolve())

            (source / "packages/agent/source.ts").write_text("changed source")
            (source / "REVISION").write_text("second-revision")
            _, unchanged = stage("source-change")
            self.assertEqual(first, unchanged)

            package = source / "packages/runtime/package.json"
            manifest = json.loads(package.read_text())
            manifest["description"] = "changed workspace metadata"
            package.write_text(json.dumps(manifest))
            _, changed = stage("manifest-change")
            self.assertNotEqual(first, changed)

            (source / ".npmrc").unlink()
            _, without_config = stage("without-config")
            self.assertNotIn(".npmrc", without_config)

            package.unlink()
            failed = subprocess.run(["node", str(STAGE), str(source), str(Path(directory) / "missing")],
                                    capture_output=True, text=True)
            self.assertNotEqual(0, failed.returncode)
            self.assertIn("ENOENT", failed.stderr)


if __name__ == "__main__":
    unittest.main()
