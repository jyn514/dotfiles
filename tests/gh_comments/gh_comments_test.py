import importlib.machinery
import importlib.util
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "bin/gh-comments"
LOADER = importlib.machinery.SourceFileLoader("gh_comments_command", str(MODULE_PATH))
SPEC = importlib.util.spec_from_loader(LOADER.name, LOADER)
assert SPEC
gh_comments = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = gh_comments
LOADER.exec_module(gh_comments)


class GhCommentsTests(unittest.TestCase):
    def test_parses_canonical_forms_and_removes_page_suffix(self):
        self.assertEqual(
            gh_comments.parse_issue(["owner/repo", "123"]),
            ("https://github.com/owner/repo/issues/123", "123"),
        )
        self.assertEqual(
            gh_comments.parse_issue(
                ["github.com/owner/repo/issues/456?notification_referrer=x#comment"]
            ),
            ("https://github.com/owner/repo/issues/456", "456"),
        )

    def test_rejects_noncanonical_and_unsafe_issue_names(self):
        cases = [
            ["owner/repo", "../escape"],
            ["owner/repo", "１２３"],
            ["https://example.com/owner/repo/issues/1"],
            ["github.com/owner/repo/pull/1"],
        ]
        for arguments in cases:
            with self.subTest(arguments=arguments), mock.patch(
                "sys.stderr", new_callable=io.StringIO
            ):
                self.assertIsNone(gh_comments.parse_issue(arguments))

    def test_exports_normalizes_and_publishes_both_files(self):
        def producer(url, json_path, text_path):
            self.assertEqual(url, "https://github.com/owner/repo/issues/123")
            json_path.write_bytes(b'{"number":123}\n')
            text_path.write_bytes(b"progress\rIssue title\nbody\n")
            return 0, 0

        runner = mock.Mock(return_value=0)
        with tempfile.TemporaryDirectory() as temporary, mock.patch(
            "sys.stdout", new_callable=io.StringIO
        ) as stdout:
            directory = Path(temporary)
            self.assertEqual(
                gh_comments.export_issue(
                    ["owner/repo", "123"],
                    producer=producer,
                    runner=runner,
                    directory=directory,
                ),
                0,
            )
            self.assertEqual((directory / "123.json").read_bytes(), b'{"number":123}\n')
            self.assertEqual((directory / "123.txt").read_bytes(), b"Issue title\nbody\n")
            self.assertEqual(list(directory.glob(".123.*")), [])
            runner.assert_called_once_with(["less", str(directory / "123.txt")])
            self.assertEqual(stdout.getvalue(), "saved 123.txt and 123.json\n")

    def test_producer_failures_publish_nothing_and_prefer_text_status(self):
        for statuses, expected in (((24, 0), 24), ((0, 25), 25), ((24, 25), 25)):
            with self.subTest(statuses=statuses), tempfile.TemporaryDirectory() as temporary:
                directory = Path(temporary)

                def producer(_url, json_path, text_path):
                    json_path.write_bytes(b"partial json")
                    text_path.write_bytes(b"partial text")
                    return statuses

                self.assertEqual(
                    gh_comments.export_issue(
                        ["owner/repo", "123"],
                        producer=producer,
                        runner=mock.Mock(),
                        directory=directory,
                    ),
                    expected,
                )
                self.assertEqual(list(directory.iterdir()), [])

    def test_existing_or_dangling_outputs_are_never_replaced(self):
        producer = mock.Mock()
        with tempfile.TemporaryDirectory() as temporary, mock.patch(
            "sys.stderr", new_callable=io.StringIO
        ):
            directory = Path(temporary)
            (directory / "123.json").symlink_to("missing")
            self.assertEqual(
                gh_comments.export_issue(
                    ["owner/repo", "123"],
                    producer=producer,
                    directory=directory,
                ),
                1,
            )
        producer.assert_not_called()

    def test_less_failure_leaves_complete_exports(self):
        def producer(_url, json_path, text_path):
            json_path.write_bytes(b"json\n")
            text_path.write_bytes(b"text\n")
            return 0, 0

        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            self.assertEqual(
                gh_comments.export_issue(
                    ["owner/repo", "123"],
                    producer=producer,
                    runner=lambda _arguments: 26,
                    directory=directory,
                ),
                26,
            )
            self.assertEqual((directory / "123.json").read_bytes(), b"json\n")
            self.assertEqual((directory / "123.txt").read_bytes(), b"text\n")

    def test_signal_status_is_preserved(self):
        with mock.patch.object(
            gh_comments,
            "export_issue",
            side_effect=gh_comments.SignalExit(143),
        ):
            self.assertEqual(gh_comments.main(["owner/repo", "123"]), 143)


if __name__ == "__main__":
    unittest.main()
