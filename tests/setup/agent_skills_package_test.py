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
    def test_checked_in_plugin_manifests_are_generated_from_package_json(self) -> None:
        subprocess.run([ROOT / "dev/generate-plugin-manifests", "--check"], check=True)

    def test_marketplaces_install_the_published_package_identity(self) -> None:
        package = load_json("package.json")
        codex_plugin = load_json(".codex-plugin/plugin.json")
        codex_marketplace = load_json(".agents/plugins/marketplace.json")
        codex_entry = codex_marketplace["plugins"][0]
        claude_plugin = load_json(".claude-plugin/plugin.json")
        claude_entry = load_json(".claude-plugin/marketplace.json")["plugins"][0]

        self.assertEqual(codex_marketplace["name"], "jyn-plugins")
        for metadata in (codex_plugin, claude_plugin, claude_entry):
            self.assertEqual(metadata["name"], package["name"])
            self.assertEqual(metadata["version"], package["version"])
            self.assertEqual(metadata["description"], package["description"])
        self.assertEqual(codex_entry["name"], package["name"])
        self.assertEqual(
            codex_entry["source"],
            {
                "source": "npm",
                "package": package["name"],
                "version": package["version"],
            },
        )
        self.assertEqual(codex_entry["policy"]["installation"], "AVAILABLE")
        self.assertEqual(codex_entry["policy"]["authentication"], "ON_INSTALL")

    def test_npm_archive_declares_codex_and_skill_resources(self) -> None:
        package = load_json("package.json")
        plugin = load_json(".codex-plugin/plugin.json")

        self.assertIn(".codex-plugin/", package["files"])
        self.assertIn(".claude-plugin/", package["files"])
        self.assertIn("skills/", package["files"])
        self.assertEqual(plugin["skills"], "./skills/")
        self.assertEqual(package["pi"]["skills"], ["skills"])

    def test_design_phase_helpers_are_linked_references_not_skills(self) -> None:
        skill_directory = ROOT / "skills/design-deliberation"
        workflow = (skill_directory / "SKILL.md").read_text(encoding="utf-8")
        for name in ("independent-plan", "cross-critic", "fusion-candidate", "council-review"):
            with self.subTest(phase=name):
                relative_path = f"references/{name}.md"
                reference = skill_directory / relative_path
                self.assertTrue(reference.is_file())
                self.assertIn(f"]({relative_path})", workflow)
                self.assertFalse(reference.read_text(encoding="utf-8").startswith("---"))
                self.assertFalse((ROOT / "skills" / name).exists())
                self.assertFalse(list(skill_directory.rglob("references/**/SKILL.md")))

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
    "has_codex_plugin": (package / ".codex-plugin/plugin.json").is_file(),
    "has_claude_plugin": (package / ".claude-plugin/plugin.json").is_file(),
    "has_claude_marketplace": (package / ".claude-plugin/marketplace.json").is_file(),
    "has_skills": (package / "skills").is_dir(),
    "reference_files": {
        str(path.relative_to(package)): path.read_text(encoding="utf-8")
        for path in (package / "skills").rglob("references/*.md")
    },
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
            self.assertTrue(staged["has_codex_plugin"])
            self.assertTrue(staged["has_claude_plugin"])
            self.assertTrue(staged["has_claude_marketplace"])
            self.assertTrue(staged["has_skills"])
            self.assertIn("skills/references/change-with-evidence.md", staged["reference_files"])
            self.assertEqual(staged["reference_files"], {
                str(path.relative_to(ROOT)): path.read_text(encoding="utf-8")
                for path in (ROOT / "skills").rglob("references/*.md")
            })
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
