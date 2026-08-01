#!/usr/bin/env python3

import hashlib
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class VendoredArtifactTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.manifest = json.loads((ROOT / "install/vendored.json").read_text())

    def test_every_artifact_exists_and_matches_its_checksum(self) -> None:
        for name, artifact in self.manifest["artifacts"].items():
            path = ROOT / artifact["path"]
            with self.subTest(name=name):
                self.assertTrue(path.is_file())
                self.assertEqual(
                    artifact["sha256"], hashlib.sha256(path.read_bytes()).hexdigest()
                )

    def test_every_artifact_records_source_version_and_license_fields(self) -> None:
        for name, artifact in self.manifest["artifacts"].items():
            with self.subTest(name=name):
                self.assertTrue(artifact["source"].startswith("https://"))
                self.assertIn("version", artifact)
                self.assertIn("license", artifact)
                if artifact["license"] is not None:
                    self.assertTrue((ROOT / artifact["license"]).is_file())

    def test_all_large_checked_in_executables_are_inventoried(self) -> None:
        inventoried = {
            artifact["path"] for artifact in self.manifest["artifacts"].values()
        }
        large_executables = {
            str(path.relative_to(ROOT))
            for path in (ROOT / "bin").iterdir()
            if path.is_file() and path.stat().st_size > 100_000
        }
        self.assertLessEqual(large_executables, inventoried)


if __name__ == "__main__":
    unittest.main()
