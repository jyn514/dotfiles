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

    def assert_patch_result(self, counts: str, context: str = "three", succeeds: bool = True) -> None:
        patch = """diff --git a/note.txt b/note.txt
--- a/note.txt
+++ b/note.txt
@@ -1,3 +1,3 @@
 one
-two
+TWO
 three
""".replace("@@ -1,3 +1,3 @@", counts).replace(" three\n", f" {context}\n")
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

            right_inode = right.stat().st_ino
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

            if succeeds:
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertEqual("one\nTWO\nthree\n", (right / "note.txt").read_text())
            else:
                self.assertNotEqual(0, result.returncode)
                self.assertIn("patch does not apply", result.stderr)
                self.assertEqual("one\ntwo\nthree\n", (right / "note.txt").read_text())
            self.assertEqual(right_inode, right.stat().st_ino)
            self.assertEqual("one\ntwo\nthree\n", (left / "note.txt").read_text())
            self.assertEqual(patch, (staged / "agent-split.patch").read_text())
            self.assertFalse((right / "unselected.txt").exists())

    def test_replaces_right_tree_with_selected_patch(self) -> None:
        self.assert_patch_result("@@ -1,3 +1,3 @@")

    def test_recounts_hand_edited_hunks(self) -> None:
        self.assert_patch_result("@@ -1,9 +1,2 @@")

    def test_recount_does_not_accept_stale_context(self) -> None:
        for counts in ["@@ -1,3 +1,3 @@", "@@ -1,9 +1,2 @@"]:
            with self.subTest(counts=counts):
                self.assert_patch_result(counts, context="missing", succeeds=False)


if __name__ == "__main__":
    unittest.main()
