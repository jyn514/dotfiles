#!/usr/bin/env python3

import json
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


if __name__ == "__main__":
    unittest.main()
