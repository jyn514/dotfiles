"""Keep benchmark snapshots out of real Bun discovery without losing intended suites."""

from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests/fixtures/bun-discovery"


@unittest.skipUnless(shutil.which("bun"), "Bun is required for native discovery checks")
class BunDiscoveryTests(unittest.TestCase):
    def copy(self, source, destination):
        destination.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["cp", source, destination], check=True)
        subprocess.run(["cmp", source, destination], check=True)

    def test_runner_excludes_archives_but_keeps_both_native_suite_roots(self):
        with tempfile.TemporaryDirectory(prefix="bun-discovery-") as temporary:
            root = Path(temporary)
            (root / ".gitignore").write_text("target/\n")
            for suite in ("tests/pi", "tools/codex-sandbox/tests"):
                self.copy(FIXTURES / "intended.test.ts.fixture", root / suite / "intended.test.ts")
                self.copy(FIXTURES / "archived.test.ts.fixture",
                          root / "target/saved-source" / suite / "archived.test.ts")

            def run(*patterns):
                return subprocess.run(["bun", "test", *patterns], cwd=root,
                                      capture_output=True, text=True, timeout=30)

            # Reproduce the reported failure: a path substring also selects the archive.
            baseline = run("tests/pi")
            self.assertNotEqual(0, baseline.returncode, baseline.stdout + baseline.stderr)
            self.assertIn("ARCHIVED_TEST_MUST_NOT_EXECUTE", baseline.stdout + baseline.stderr)

            self.copy(ROOT / "bunfig.toml", root / "bunfig.toml")
            for patterns, expected_passes in ((["tests/pi"], 1),
                                              (["tools/codex-sandbox/tests"], 1), ([], 2)):
                with self.subTest(patterns=patterns):
                    result = run(*patterns)
                    output = result.stdout + result.stderr
                    self.assertEqual(0, result.returncode, output)
                    self.assertIn(f"{expected_passes} pass", output)
                    self.assertIn("intended suite executes", output)
                    self.assertNotIn("ARCHIVED_TEST_MUST_NOT_EXECUTE", output)
