import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[3]
EDITOR = ROOT / "tools" / "jj-proxy" / "agent-split-editor"
CONFIG = ROOT / "tools" / "jj-proxy" / "jj.toml"
DOCKERFILE = ROOT / "tools" / "jj-proxy" / "Dockerfile"


class AgentSplitEditorEndToEndTest(unittest.TestCase):
    def test_trusted_shell_is_a_regular_executable(self) -> None:
        dockerfile = DOCKERFILE.read_text(encoding="utf-8")
        self.assertIn("cp /bin/busybox /trusted/bin/sh", dockerfile)
        self.assertNotIn("ln -s busybox /trusted/bin/sh", dockerfile)

    def test_config_invokes_editor_through_trusted_shell(self) -> None:
        config = CONFIG.read_text(encoding="utf-8")
        self.assertIn('program = "/trusted/bin/sh"', config)
        self.assertIn(
            'edit-args = ["/trusted/bin/agent-split-editor", "$left", "$right"]',
            config,
        )

    def test_replaces_right_tree_with_selected_patch(self) -> None:
        patch = """diff --git a/note.txt b/note.txt
--- a/note.txt
+++ b/note.txt
@@ -1,3 +1,3 @@
 one
-two
+TWO
 three
"""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            left = root / "left"
            right = root / "right"
            left.mkdir()
            right.mkdir()
            (left / "note.txt").write_text("one\ntwo\nthree\n")
            (right / "note.txt").write_text("one\nTWO\nTHREE\n")
            (right / "unselected.txt").write_text("must disappear\n")
            staged = root / "jj-config"
            staged.mkdir()
            (staged / "agent-split.patch").write_text(patch)

            editor = root / "agent-split-editor"
            editor.write_text(EDITOR.read_text().replace(
                "/tmp/jj-config/agent-split.patch",
                str(staged / "agent-split.patch"),
            ))
            result = subprocess.run(
                ["sh", str(editor), str(left), str(right)],
                env={**os.environ, "PATH": os.environ["PATH"]},
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual("one\nTWO\nthree\n", (right / "note.txt").read_text())
            self.assertFalse((right / "unselected.txt").exists())


if __name__ == "__main__":
    unittest.main()
