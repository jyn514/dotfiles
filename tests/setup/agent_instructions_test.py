#!/usr/bin/env python3

import copy
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
SHARED = "$HOME/.agents/shared.md"
SKILLS = "$HOME/.agents/skills"
REFERENCE = "$HOME/.agents/skills/references/change-with-evidence.md"


class AgentInstructionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="agent-instructions-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.home = self.root / "home"
        self.home.mkdir()
        self.repository = self.root / "checkout"
        self.repository.mkdir()
        manifest = json.loads((ROOT / "install.conf.json").read_text())
        links = {}
        defaults = []
        for entry in manifest:
            if "defaults" in entry:
                defaults.append(copy.deepcopy(entry))
            for destination, source in entry.get("link", {}).items():
                if destination in (SHARED, SKILLS):
                    self.assertNotIn(destination, links, "each installed role has one authority")
                    links[destination] = copy.deepcopy(source)
        self.assertEqual({SHARED, SKILLS}, set(links))
        self.assertFalse(any("$HOME/.agents/change-with-evidence.md" in entry.get("link", {})
                             or REFERENCE in entry.get("link", {}) for entry in manifest),
                         "the reference must reuse the whole skills link")
        self.configuration = [*defaults, {"link": links}]
        self.config = self.repository / "install.conf.json"
        self.config.write_text(json.dumps(self.configuration))
        self.sources = {}
        for destination, spec in links.items():
            source = spec if isinstance(spec, str) else spec["path"]
            target = self.repository / source
            target.parent.mkdir(parents=True, exist_ok=True)
            if (ROOT / source).is_dir():
                shutil.copytree(ROOT / source, target)
            else:
                shutil.copyfile(ROOT / source, target)
                self.assertEqual((ROOT / source).read_bytes(), target.read_bytes())
            self.sources[destination] = target
        self.environment = dict(os.environ, HOME=str(self.home))

    def install(self) -> None:
        result = subprocess.run(
            [str(ROOT / "vendor/dotbot/bin/dotbot"), "-d", str(self.repository), "-c", str(self.config)],
            env=self.environment, cwd=self.root, text=True, capture_output=True,
        )
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def installed(self, destination: str) -> Path:
        return self.home / destination.removeprefix("$HOME/")

    def routed_reference(self) -> Path:
        shared = self.installed(SHARED).read_text()
        routes = re.findall(r"\[Change with evidence\]\(([^)]+)\)", shared)
        self.assertEqual(1, len(routes), "shared instructions must route to the task reference once")
        self.assertTrue(routes[0].startswith("~/"), "route must address the installed HOME")
        return self.home / routes[0][2:]

    def test_manifest_installs_shared_and_whole_skills_and_reference_route_resolves(self) -> None:
        self.install()
        for destination, source in self.sources.items():
            with self.subTest(destination=destination):
                installed = self.installed(destination)
                self.assertTrue(installed.is_symlink())
                self.assertEqual(source.resolve(), installed.resolve())
                if source.is_file():
                    self.assertEqual(source.read_bytes(), installed.read_bytes())
        self.assertEqual(self.installed(REFERENCE), self.routed_reference())
        reference = self.sources[SKILLS] / "references/change-with-evidence.md"
        self.assertEqual(reference.read_bytes(), self.routed_reference().read_bytes())
        self.assertFalse(self.routed_reference().is_symlink(), "no individual reference link")
        self.assertFalse(reference.read_text().startswith("---"), "plain Markdown, not a skill")

    def test_reference_content_and_source_changes_need_no_shared_routing_edits(self) -> None:
        self.install()
        shared_before = self.installed(SHARED).read_bytes()
        manifest_before = self.config.read_bytes()
        skills_link_before = os.readlink(self.installed(SKILLS))
        reference = self.sources[SKILLS] / "references/change-with-evidence.md"
        updated = reference.read_bytes() + b"\nTemporary authoritative reference revision.\n"
        reference.write_bytes(updated)
        self.assertEqual(updated, self.routed_reference().read_bytes(), "content edits propagate without reinstall")
        self.assertEqual(manifest_before, self.config.read_bytes())
        self.assertEqual(skills_link_before, os.readlink(self.installed(SKILLS)))

        # Relocate the authority by changing only its manifest entry. The
        # installed role and the shared client's Markdown route stay stable.
        replacement = self.repository / "relocated-skills"
        shutil.copytree(self.sources[SKILLS], replacement)
        replacement_reference = replacement / "references/change-with-evidence.md"
        replacement_reference.write_bytes(updated + b"Relocated authoritative skills source.\n")
        spec = self.configuration[-1]["link"][SKILLS]
        if isinstance(spec, str):
            self.configuration[-1]["link"][SKILLS] = str(replacement.relative_to(self.repository))
        else:
            spec["path"] = str(replacement.relative_to(self.repository))
        self.config.write_text(json.dumps(self.configuration))
        self.install()
        self.assertTrue(self.installed(SKILLS).is_symlink())
        self.assertEqual(replacement.resolve(), self.installed(SKILLS).resolve())
        self.assertEqual(replacement_reference.resolve(), self.routed_reference().resolve())
        self.assertEqual(replacement_reference.read_bytes(), self.routed_reference().read_bytes())
        self.assertEqual(shared_before, self.installed(SHARED).read_bytes())
        self.assertEqual(shared_before, self.sources[SHARED].read_bytes())


if __name__ == "__main__":
    unittest.main()
