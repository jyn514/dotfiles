import importlib.machinery
import importlib.util
import io
from pathlib import Path
import sys
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[3]
MODULE_PATH = ROOT / "tools/fork-github/fork-github"
LOADER = importlib.machinery.SourceFileLoader("fork_github_command", str(MODULE_PATH))
SPEC = importlib.util.spec_from_loader(LOADER.name, LOADER)
assert SPEC
fork_github = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = fork_github
LOADER.exec_module(fork_github)


class ForkGithubTests(unittest.TestCase):
    def test_normalizes_github_page_and_shorthand_urls(self):
        page = fork_github.parse_repository(
            "https://github.com/owner/project.git/tree/main?tab=readme"
        )
        shorthand = fork_github.parse_repository("owner/other")

        self.assertEqual(
            page,
            fork_github.Repository(
                "https://github.com/owner/project.git", "project", "github.com"
            ),
        )
        self.assertEqual(
            shorthand,
            fork_github.Repository(
                "https://github.com/owner/other.git", "other", "github.com"
            ),
        )

    def test_extracts_hosts_from_supported_clone_url_forms(self):
        cases = {
            "https://example.test:8443/owner/repo.git": "example.test",
            "ssh://git@example.test:2222/owner/repo.git": "example.test",
            "git@example.test:owner/repo.git": "example.test",
        }
        for url, host in cases.items():
            with self.subTest(url=url):
                self.assertEqual(fork_github.parse_repository(url).host, host)

    def test_clone_and_remote_setup_failures_stop_without_publishing_directory(self):
        # Clone creates upstream directly; there is no rename to roll back.
        for stage, status in ((0, 21), (1, 22)):
            with self.subTest(stage=stage):
                runner = mock.Mock(side_effect=(
                    [fork_github.Result(0)] * stage + [fork_github.Result(status)]
                ))
                with mock.patch("sys.stdout", new_callable=io.StringIO) as stdout:
                    self.assertEqual(
                        fork_github.fork(["owner/repository", "checkout"], runner),
                        status,
                    )
                self.assertEqual(stdout.getvalue(), "")
                self.assertEqual(runner.call_count, stage + 1)

    def test_execution_errors_are_diagnostic_and_have_shell_statuses(self):
        for error, status in ((FileNotFoundError("missing"), 127),
                              (PermissionError("denied"), 126)):
            with self.subTest(error=error):
                with mock.patch.object(fork_github.subprocess, "run", side_effect=error):
                    with mock.patch("sys.stderr", new_callable=io.StringIO) as stderr:
                        self.assertEqual(fork_github.run(["jj"]).status, status)
                self.assertIn("could not execute 'jj'", stderr.getvalue())

    def test_signal_exit_status_is_preserved(self):
        completed = fork_github.subprocess.CompletedProcess(["jj"], -15)
        with mock.patch.object(fork_github.subprocess, "run", return_value=completed):
            self.assertEqual(fork_github.run(["jj"]).status, 143)

    def test_prints_directory_only_after_complete_configuration(self):
        runner = mock.Mock(return_value=fork_github.Result(0))
        with mock.patch("sys.stdout", new_callable=io.StringIO) as stdout:
            self.assertEqual(
                fork_github.fork(["owner/repository", "directory with spaces"], runner),
                0,
            )
        self.assertEqual(stdout.getvalue(), "directory with spaces\n")

    def test_usage_is_diagnostic_with_status_two(self):
        with mock.patch("sys.stderr", new_callable=io.StringIO) as stderr:
            self.assertEqual(fork_github.fork([]), 2)
        self.assertEqual(
            stderr.getvalue(), "usage: fork-github <repository> [directory]\n"
        )


if __name__ == "__main__":
    unittest.main()
