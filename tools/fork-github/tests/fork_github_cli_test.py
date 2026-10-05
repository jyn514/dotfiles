import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[3]


class CommandIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.environment = os.environ | {
            "GIT_CONFIG_GLOBAL": str(self.directory / "gitconfig"),
            "GIT_CONFIG_NOSYSTEM": "1",
        }
        # Even a broken normalization must fail locally, never contact a host.
        self.git("config", "--global", "protocol.allow", "never")
        self.git("config", "--global", "protocol.file.allow", "always")
        self.source = self.directory / "source"
        self.git("init", "--initial-branch=main", str(self.source))
        (self.source / "content.txt").write_text("cloned repository content\n")
        self.git("-C", str(self.source), "add", "content.txt")
        self.git(
            "-C", str(self.source), "-c", "user.name=Test",
            "-c", "user.email=test@example.test", "commit", "-m", "fixture",
        )

    def git(self, *arguments: str) -> str:
        result = subprocess.run(
            ["git", *arguments], cwd=self.directory, env=self.environment,
            text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        return result.stdout.strip()

    def local_remote(self, url: str, source: Path | None = None) -> None:
        # Only the exact normalized clone URL can reach the local fixture.
        self.git(
            "config", "--global", f"url.{(source or self.source).as_uri()}.insteadOf", url,
        )

    def fork(self, *arguments: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [str(ROOT / "bin/fork-github"), *arguments],
            cwd=self.directory, text=True, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, env=self.environment, timeout=30,
        )

    def assert_checkout(self, name: str, upstream: str, origin: str) -> None:
        checkout = self.directory / name
        self.assertTrue((checkout / ".jj").is_dir())
        self.assertTrue((checkout / ".git").exists())
        self.assertEqual("cloned repository content\n", (checkout / "content.txt").read_text())
        self.assertEqual(["origin", "upstream"], self.git("-C", str(checkout), "remote").splitlines())
        for remote, url in (("upstream", upstream), ("origin", origin)):
            # Read stored URLs, not Git's insteadOf-expanded transport URLs.
            self.assertEqual(url, self.git("-C", str(checkout), "config", "--get", f"remote.{remote}.url"))
        result = subprocess.run(
            ["jj", "git", "remote", "list"], cwd=checkout,
            # Remote listing should report persisted consumer URLs without the
            # fixture's transport rewrite, which jj otherwise expands too.
            env=self.environment | {"GIT_CONFIG_GLOBAL": os.devnull},
            text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(
            [["origin", origin], ["upstream", upstream]],
            sorted(line.split(maxsplit=1) for line in result.stdout.splitlines()),
        )

    def test_fork_github_strips_page_url_suffixes(self) -> None:
        upstream = "https://github.com/user/repository.git"
        self.local_remote(upstream)
        result = self.fork("https://github.com/user/repository?tab=readme-ov-file")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("repository\n", result.stdout)
        self.assert_checkout("repository", upstream, "git@github.com:jyn514/repository.git")

    def test_fork_github_keeps_repository_name_when_checkout_directory_differs(self) -> None:
        upstream = "https://github.com/owner/repository.git"
        self.local_remote(upstream)
        result = self.fork("owner/repository", "custom checkout")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("custom checkout\n", result.stdout)
        self.assert_checkout("custom checkout", upstream, "git@github.com:jyn514/repository.git")

    def test_preserves_supported_clone_urls_and_personal_remote_host(self) -> None:
        for index, upstream in enumerate((
            "https://example.test:8443/owner/repo.git",
            "ssh://git@example.test:2222/owner/repo.git",
            "git@example.test:owner/repo.git",
        )):
            with self.subTest(url=upstream):
                self.local_remote(upstream)
                name = f"checkout-{index}"
                result = self.fork(upstream, name)
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertEqual(name + "\n", result.stdout)
                self.assert_checkout(name, upstream, "git@example.test:jyn514/repo.git")

    def test_clone_failure_does_not_publish_a_checkout(self) -> None:
        upstream = "https://github.com/owner/missing.git"
        self.local_remote(upstream, self.directory / "missing-source")
        result = self.fork("owner/missing")
        self.assertNotEqual(0, result.returncode)
        self.assertEqual("", result.stdout)
        self.assertTrue(result.stderr)

    def test_remote_setup_failure_preserves_cloned_upstream(self) -> None:
        upstream = "https://github.com/owner/repository.git"
        self.local_remote(upstream)
        real_jj = shutil.which("jj", path=self.environment["PATH"])
        self.assertIsNotNone(real_jj)
        wrappers = self.directory / "wrappers"
        wrappers.mkdir()
        wrapper = wrappers / "jj"
        wrapper.symlink_to(
            Path(__file__).with_name("fixtures") / "jj_remote_setup_failure.sh"
        )
        self.environment |= {
            "REAL_JJ": real_jj,
            "PATH": str(wrappers) + os.pathsep + self.environment["PATH"],
        }
        result = self.fork("owner/repository", "failed setup")
        self.assertEqual(23, result.returncode, result.stderr)
        self.assertEqual("", result.stdout)
        self.assertIn("fixture: remote setup failed", result.stderr)
        checkout = self.directory / "failed setup"
        self.assertTrue((checkout / ".jj").is_dir())
        self.assertEqual("cloned repository content\n", (checkout / "content.txt").read_text())
        self.assertEqual("upstream", self.git("-C", str(checkout), "remote"))
        self.assertEqual(upstream, self.git("-C", str(checkout), "config", "--get", "remote.upstream.url"))

    def test_usage_is_diagnostic_without_creating_a_checkout(self) -> None:
        for arguments in ((), ("owner/repository", "one", "two")):
            with self.subTest(arguments=arguments):
                result = self.fork(*arguments)
                self.assertEqual(2, result.returncode)
                self.assertEqual("", result.stdout)
                self.assertIn("usage:", result.stderr)
        self.assertFalse((self.directory / "repository").exists())


if __name__ == "__main__":
    unittest.main()
