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

    def test_configures_exact_remotes_in_checkout_directory(self):
        calls = []

        def runner(arguments, *, cwd=None):
            calls.append((arguments, cwd))
            return fork_github.Result(0)

        repository = fork_github.parse_repository("owner/repository")
        directory = Path("custom checkout")
        self.assertEqual(fork_github.configure(repository, directory, runner), 0)
        self.assertEqual(
            calls,
            [
                (
                    [
                        "git",
                        "clone",
                        "--filter=blob:none",
                        "https://github.com/owner/repository.git",
                        "custom checkout",
                    ],
                    None,
                ),
                (["git", "remote", "rename", "origin", "upstream"], directory),
                (
                    [
                        "git",
                        "remote",
                        "add",
                        "origin",
                        "git@github.com:jyn514/repository.git",
                    ],
                    directory,
                ),
            ],
        )

    def test_each_git_failure_stops_or_rolls_back(self):
        repository = fork_github.parse_repository("owner/repository")
        directory = Path("checkout")
        for stage, status, call_count in ((0, 21, 1), (1, 22, 2), (2, 23, 4)):
            with self.subTest(stage=stage):
                results = [fork_github.Result(0)] * stage + [fork_github.Result(status)]
                if stage == 2:
                    results.append(fork_github.Result(0))
                runner = mock.Mock(side_effect=results)

                self.assertEqual(
                    fork_github.configure(repository, directory, runner), status
                )
                self.assertEqual(runner.call_count, call_count)
                if stage == 2:
                    self.assertEqual(
                        runner.call_args_list[-1],
                        mock.call(
                            ["git", "remote", "rename", "upstream", "origin"],
                            cwd=directory,
                        ),
                    )

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
