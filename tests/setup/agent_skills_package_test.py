#!/usr/bin/env python3

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def load_json(path: str) -> dict:
    with (ROOT / path).open(encoding="utf-8") as file:
        return json.load(file)


class AgentSkillsPackageTest(unittest.TestCase):
    def test_codex_marketplace_installs_the_published_package(self) -> None:
        package = load_json("package.json")
        plugin = load_json(".codex-plugin/plugin.json")
        marketplace = load_json(".agents/plugins/marketplace.json")
        entry = marketplace["plugins"][0]

        self.assertEqual(marketplace["name"], "jyn-plugins")
        self.assertEqual(plugin["name"], package["name"])
        self.assertEqual(plugin["version"], package["version"])
        self.assertEqual(entry["name"], package["name"])
        self.assertEqual(
            entry["source"],
            {
                "source": "npm",
                "package": package["name"],
                "version": package["version"],
            },
        )
        self.assertEqual(entry["policy"]["installation"], "AVAILABLE")
        self.assertEqual(entry["policy"]["authentication"], "ON_INSTALL")

    def test_npm_archive_declares_codex_and_skill_resources(self) -> None:
        package = load_json("package.json")
        plugin = load_json(".codex-plugin/plugin.json")

        self.assertIn(".codex-plugin/", package["files"])
        self.assertIn("skills/", package["files"])
        self.assertEqual(plugin["skills"], "./skills/")
        self.assertEqual(package["pi"]["skills"], ["skills"])

    def test_publish_command_stages_the_skills_readme(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            temporary_path = Path(temporary)
            bin_directory = temporary_path / "bin"
            bin_directory.mkdir()
            capture = temporary_path / "capture.json"
            fake_npm = bin_directory / "npm"
            fake_npm.write_text(
                """#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path

package = Path(sys.argv[2])
Path(os.environ["CAPTURE"]).write_text(json.dumps({
    "arguments": sys.argv[1:2] + sys.argv[3:],
    "package": str(package),
    "readme": (package / "README.md").read_text(),
    "has_manifest": (package / "package.json").is_file(),
    "has_license": (package / "LICENSE").is_file(),
    "has_plugin": (package / ".codex-plugin/plugin.json").is_file(),
    "has_skills": (package / "skills").is_dir(),
}), encoding="utf-8")
raise SystemExit(int(os.environ.get("FAKE_NPM_EXIT", "0")))
""",
                encoding="utf-8",
            )
            fake_npm.chmod(0o755)
            environment = os.environ | {
                "CAPTURE": str(capture),
                "PATH": f"{bin_directory}{os.pathsep}{os.environ['PATH']}",
            }

            subprocess.run(
                [ROOT / "dev/publish-skills", "--dry-run", "--access", "public"],
                check=True,
                env=environment,
            )

            staged = json.loads(capture.read_text(encoding="utf-8"))
            self.assertEqual(staged["arguments"], ["publish", "--dry-run", "--access", "public"])
            self.assertEqual(
                staged["readme"],
                (ROOT / "skills/README.md").read_text(encoding="utf-8"),
            )
            self.assertTrue(staged["has_manifest"])
            self.assertTrue(staged["has_license"])
            self.assertTrue(staged["has_plugin"])
            self.assertTrue(staged["has_skills"])
            self.assertFalse(Path(staged["package"]).exists())

            failed_environment = environment | {"FAKE_NPM_EXIT": "23"}
            failed = subprocess.run(
                [ROOT / "dev/publish-skills", "--dry-run"],
                check=False,
                env=failed_environment,
            )
            self.assertEqual(failed.returncode, 23)


if __name__ == "__main__":
    unittest.main()
