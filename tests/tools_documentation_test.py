"""Keep every tracked tools subsystem represented in the tools index."""

from pathlib import Path
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "tools/README.md"


class ToolsDocumentationTest(unittest.TestCase):
    def test_every_tracked_tool_directory_is_linked_from_index(self) -> None:
        tracked = subprocess.run(
            ["git", "ls-files", "tools"],
            cwd=ROOT,
            check=True,
            stdout=subprocess.PIPE,
            text=True,
        ).stdout.splitlines()
        directories = {
            path.split("/", 2)[1] for path in tracked if path.count("/") >= 2
        }
        index = INDEX.read_text(encoding="utf-8")

        missing = sorted(
            directory
            for directory in directories
            if f"]({directory}/)" not in index
        )
        self.assertEqual([], missing, f"undocumented tool directories: {missing}")


if __name__ == "__main__":
    unittest.main()
