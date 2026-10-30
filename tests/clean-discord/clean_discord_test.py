"""Exercise the installed-style command with synthetic, non-private chat text."""

from pathlib import Path
import json
import os
import subprocess
import tempfile
import unittest


COMMAND = Path(__file__).resolve().parents[2] / "bin/clean-discord"


class CleanDiscordTests(unittest.TestCase):
    def run_command(self, text="", *args):
        return subprocess.run([str(COMMAND), *map(str, args)], input=text,
                              text=True, capture_output=True)

    def test_split_headers_badges_and_detached_decoration(self):
        text = (
            "02:28\n]\nAda [tty0], \n:\n\n"
            "    A quoted message.\n\n\nYeah, really.\n"
            " [tty0], \n[\n02:29\n]\nLin\n:\nI disagree.\n"
            "[\n02:30\n]\nAda [tty0], \n:\nLast message."
        )
        result = self.run_command(text)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")
        self.assertEqual(result.stdout, (
            "[02:28] <Ada> > A quoted message.\n"
            "[02:28] <Ada> Yeah, really.\n"
            "[02:29] <Lin> I disagree.\n"
            "[02:30] <Ada> Last message.\n"
        ))

    def test_message_content_is_not_mistaken_for_ui(self):
        text = (
            "[\n12:34\n]\nMira [she/her],\n:\n"
            "café — https://example.invalid/a:b\n"
            "[she/her],\nStill text.\n02:29\n]\nNot a header\n"
            "    let x = [1, 2];\n:\n[custom],\n"
        )
        result = self.run_command(text)
        self.assertEqual(result.returncode, 0, result.stderr)
        body = ["café — https://example.invalid/a:b", "[she/her],", "Still text.",
                "02:29", "]", "Not a header", "    let x = [1, 2];", ":", "[custom],"]
        self.assertEqual(result.stdout, "".join(f"[12:34] <Mira> {line}\n" for line in body))

    def test_file_and_explicit_stdin_match_without_changing_source(self):
        text = "[09:05]\r\nA Name\r\n:\r\nhello\r\n\r\nworld\r\n"
        expected = "[09:05] <A Name> hello\n[09:05] <A Name> world\n"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "copied chat.txt"
            path.write_bytes(text.encode())
            for args in [(path,), ("-",), ()]:
                result = self.run_command(text, *args)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout, expected)
            self.assertEqual(path.read_bytes(), text.encode())

    def test_reply_quote_block_and_indented_non_reply(self):
        for body, expected in [
            ("    quoted first line\n    quoted second line\n\n\nreply\n\n",
             "> quoted first line\n> quoted second line\nreply\n"),
            ("    let x = 1;\n    let y = 2;\n",
             "    let x = 1;\n    let y = 2;\n"),
        ]:
            with self.subTest(body=body):
                result = self.run_command("[\n10:00\n]\nAda\n:\n" + body)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout, "".join(
                    f"[10:00] <Ada> {line}\n" for line in expected.splitlines()))

    def test_in_place_replaces_file_without_stdout_and_preserves_permissions(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "copied chat.txt"
            path.write_text("[\n10:00\n]\nAda\n:\n    quote\n\nreply\n\nparagraph\n")
            path.chmod(0o640)
            result = self.run_command("", "-i", path)
            self.assertEqual((result.returncode, result.stdout, result.stderr), (0, "", ""))
            self.assertEqual(path.read_text(), (
                "[10:00] <Ada> > quote\n[10:00] <Ada> reply\n[10:00] <Ada> paragraph\n"))
            self.assertEqual(path.stat().st_mode & 0o777, 0o640)
            self.assertEqual(list(Path(directory).iterdir()), [path])

    def test_in_place_follows_symlink_without_replacing_it(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "chat.txt"
            path.write_text("[10:00]\nAda\n:\nhello\n")
            link = Path(directory) / "link.txt"
            link.symlink_to(path.name)
            result = self.run_command("", link, "-i")
            self.assertEqual((result.returncode, result.stdout, result.stderr), (0, "", ""))
            self.assertTrue(link.is_symlink())
            self.assertEqual(path.read_text(), "[10:00] <Ada> hello\n")

    def test_in_place_keeps_selected_target_when_input_symlink_is_retargeted(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            original = root / "original.txt"
            following = root / "following.txt"
            link = root / "link.txt"
            marker = root / "retargeted.txt"
            original.write_text("[10:00]\nAda\n:\noriginal\n")
            following_text = "[11:00]\nLin\n:\nfollowing\n"
            following.write_text(following_text)
            original.chmod(0o640)
            following.chmod(0o600)
            link.symlink_to(original.name)
            preload = Path(__file__).with_name("retarget_after_read.clj")
            environment = os.environ.copy()
            environment.update({
                "BABASHKA_PRELOADS": environment.get("BABASHKA_PRELOADS", "")
                + f"\n(load-file {json.dumps(str(preload))})",
                "CLEAN_DISCORD_TEST_LINK": str(link),
                "CLEAN_DISCORD_TEST_ORIGINAL": str(original),
                "CLEAN_DISCORD_TEST_NEXT": following.name,
                "CLEAN_DISCORD_TEST_MARKER": str(marker),
            })
            result = subprocess.run([str(COMMAND), "-i", str(link)],
                                    text=True, capture_output=True, env=environment)
            self.assertEqual((result.returncode, result.stdout, result.stderr), (0, "", ""))
            self.assertEqual(marker.read_text(), "retargeted after read\n")
            self.assertTrue(link.is_symlink())
            self.assertEqual(link.readlink(), Path(following.name))
            self.assertEqual(following.read_text(), following_text)
            self.assertEqual(original.read_text(), "[10:00] <Ada> original\n")
            self.assertEqual(original.stat().st_mode & 0o777, 0o640)
            self.assertEqual(following.stat().st_mode & 0o777, 0o600)
            self.assertEqual(set(root.iterdir()), {original, following, link, marker})

            # A new invocation must follow the symlink's new selection.
            result = self.run_command("", "-i", link)
            self.assertEqual((result.returncode, result.stdout, result.stderr), (0, "", ""))
            self.assertEqual(following.read_text(), "[11:00] <Lin> following\n")
            self.assertEqual(original.read_text(), "[10:00] <Ada> original\n")
            self.assertTrue(link.is_symlink())

    def test_in_place_parse_failure_leaves_original_bytes_untouched(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "chat.txt"
            for original in [b"not a Discord paste\r\n", b"[10:00] <Ada> already cleaned\n"]:
                with self.subTest(original=original):
                    path.write_bytes(original)
                    result = self.run_command("", "-i", path)
                    self.assertEqual(result.returncode, 1)
                    self.assertEqual(result.stdout, "")
                    self.assertIn("clean-discord: expected", result.stderr)
                    self.assertEqual(path.read_bytes(), original)
                    self.assertEqual(list(Path(directory).iterdir()), [path])
            missing = Path(directory) / "missing.txt"
            result = self.run_command("", "-i", missing)
            self.assertEqual(result.returncode, 1)
            self.assertFalse(missing.exists())

    def test_in_place_requires_a_file_argument(self):
        for args in [("-i",), ("-i", "-"), ("-i", "one", "two")]:
            with self.subTest(args=args):
                result = self.run_command("[10:00]\nAda\n:\nhello\n", *args)
                self.assertEqual(result.returncode, 2)
                self.assertEqual(result.stdout, "")
                self.assertIn("Usage:", result.stderr)

    def test_empty_input(self):
        result = self.run_command()
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, "", ""))

    def test_unrecognized_text_fails_without_partial_output(self):
        for text in ["plain text", "preamble\n[\n02:28\n]\nAda\n:\nhello"]:
            with self.subTest(text=text):
                result = self.run_command(text)
                self.assertEqual(result.returncode, 1)
                self.assertEqual(result.stdout, "")
                self.assertIn("clean-discord: expected", result.stderr)

    def test_help_usage_and_missing_file(self):
        result = self.run_command("", "--help")
        self.assertEqual(result.returncode, 0)
        self.assertIn("Usage: clean-discord", result.stdout)
        result = self.run_command("", "--unknown")
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, "")
        self.assertIn("Usage:", result.stderr)
        with tempfile.TemporaryDirectory() as directory:
            result = self.run_command("", Path(directory) / "missing")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "")
        self.assertIn("clean-discord:", result.stderr)


if __name__ == "__main__":
    unittest.main()
