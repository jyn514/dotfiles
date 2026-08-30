import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]


class AnsiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)

    def test_ansi_resets_background_without_debug_output(self) -> None:
        command = (
            f'source {ROOT / "bin/ansi"}; '
            "ansi::isAnsiSupported() { return 0; }; "
            "ansi --reset-background --no-restore tea"
        )
        result = subprocess.run(
            ["bash", "-c", command],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("\x1b[49mtea", result.stdout)
        self.assertNotIn("set | grep", (ROOT / "bin/ansi").read_text())


    def test_public_command_links_to_inventoried_artifact(self) -> None:
        command = ROOT / "bin/ansi"
        self.assertTrue(command.is_symlink())
        self.assertEqual((ROOT / "vendor/ansi/ansi").resolve(), command.resolve())


if __name__ == "__main__":
    unittest.main()
