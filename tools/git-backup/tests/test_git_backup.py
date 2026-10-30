from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
COMMAND = ROOT / "bin/git-backup"
COMPATIBILITY_COMMAND = ROOT / "bin/git-save"


class GitBackupTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name)
        self.repository = self.directory / "repository with spaces"
        subprocess.run(["git", "init", "-q", "-b", "main", self.repository], check=True)
        subprocess.run(["git", "-C", self.repository, "config", "user.name", "Test"], check=True)
        subprocess.run(
            ["git", "-C", self.repository, "config", "user.email", "test@example.com"],
            check=True,
        )
        (self.repository / "file with spaces.txt").write_text("backup contents\n")
        subprocess.run(["git", "-C", self.repository, "add", "--all"], check=True)
        subprocess.run(["git", "-C", self.repository, "commit", "-qm", "initial"], check=True)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def run_command(
        self, *arguments: str, environment: dict[str, str] | None = None
    ) -> subprocess.CompletedProcess[bytes]:
        return subprocess.run(
            [os.fsencode(COMMAND), *(os.fsencode(argument) for argument in arguments)],
            cwd=self.directory,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

    def test_creates_bundle_and_portable_checkout_archives(self) -> None:
        output = self.directory / "backup output"
        result = self.run_command(str(self.repository), str(output))
        self.assertEqual(0, result.returncode, result.stderr)

        archive = Path(f"{output}.tar")
        listing = subprocess.check_output(["tar", "tf", archive]).splitlines()
        self.assertIn(b"repository with spaces/repository with spaces.bundle", listing)
        self.assertIn(b"repository with spaces/master.tar.xz", listing)

        extracted = self.directory / "extracted"
        extracted.mkdir()
        subprocess.run(["tar", "xf", archive, "-C", extracted], check=True)
        bundle = extracted / "repository with spaces/repository with spaces.bundle"
        subprocess.run(
            ["git", "bundle", "verify", bundle],
            cwd=self.repository,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        subprocess.run(
            ["tar", "xf", extracted / "repository with spaces/master.tar.xz", "-C", extracted],
            check=True,
        )
        self.assertEqual(
            "backup contents\n",
            (extracted / "master/file with spaces.txt").read_text(),
        )

    def test_option_like_repository_name_is_a_literal_archive_operand(self) -> None:
        name = "--add-file=."
        source = self.directory / name
        self.repository.rename(source)
        expected_head = subprocess.check_output(
            ["git", "-C", source, "rev-parse", "HEAD"]
        ).strip()
        for command in (COMMAND, COMPATIBILITY_COMMAND):
            with self.subTest(command=command.name):
                output = self.directory / command.name
                result = subprocess.run(
                    [command, source, output],
                    cwd=self.directory,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    check=False,
                )
                self.assertEqual(0, result.returncode, result.stderr)
                archive = Path(f"{output}.tar")
                members = subprocess.check_output(["tar", "tf", archive]).splitlines()
                self.assertEqual(
                    {
                        f"{name}/".encode(),
                        f"{name}/{name}.bundle".encode(),
                        f"{name}/master.tar.xz".encode(),
                    },
                    set(members),
                )
                extracted = self.directory / f"extracted-{command.name}"
                extracted.mkdir()
                subprocess.run(["tar", "xf", archive, "-C", extracted], check=True)
                bundle = extracted / name / f"{name}.bundle"
                heads = subprocess.check_output(["git", "bundle", "list-heads", bundle])
                self.assertIn(expected_head + b" HEAD", heads.splitlines())
                restored = self.directory / f"restored-{command.name}"
                subprocess.run(["git", "clone", "-q", bundle, restored], check=True)
                self.assertEqual(
                    "backup contents\n", (restored / "file with spaces.txt").read_text()
                )
                subprocess.run(
                    ["tar", "xf", extracted / name / "master.tar.xz", "-C", extracted],
                    check=True,
                )
                self.assertEqual(
                    "backup contents\n", (extracted / "master/file with spaces.txt").read_text()
                )

    def test_explicit_repository_wins_over_inherited_repository_environment(self) -> None:
        expected_head = subprocess.check_output(
            ["git", "-C", self.repository, "rev-parse", "HEAD"]
        ).strip()
        cases = {
            "git-dir": {"GIT_DIR": ".git"},
            "common-dir": {"GIT_COMMON_DIR": ".git"},
            "object-directory": {"GIT_OBJECT_DIRECTORY": ".git/objects"},
            "work-tree": {"GIT_WORK_TREE": "."},
            "index-file": {"GIT_INDEX_FILE": ".git/index"},
            "alternate-objects": {"GIT_ALTERNATE_OBJECT_DIRECTORIES": ".git/objects"},
            "repository-paths": {
                "GIT_DIR": ".git",
                "GIT_COMMON_DIR": ".git",
                "GIT_WORK_TREE": ".",
                "GIT_INDEX_FILE": ".git/index",
                "GIT_OBJECT_DIRECTORY": ".git/objects",
                "GIT_ALTERNATE_OBJECT_DIRECTORIES": ".git/objects",
            },
        }
        for name, selectors in cases.items():
            with self.subTest(name=name):
                other = self.directory / f"other repository {name}"
                subprocess.run(["git", "init", "-q", "-b", "other", other], check=True)
                subprocess.run(["git", "-C", other, "config", "user.name", "Test"], check=True)
                subprocess.run(
                    ["git", "-C", other, "config", "user.email", "test@example.com"], check=True
                )
                (other / "file with spaces.txt").write_text("other repository contents\n")
                subprocess.run(["git", "-C", other, "add", "--all"], check=True)
                subprocess.run(["git", "-C", other, "commit", "-qm", "other"], check=True)
                other_files = {
                    path: path.read_bytes()
                    for path in (other / ".git/index", other / ".git/config")
                }
                other_head = subprocess.check_output(["git", "-C", other, "rev-parse", "HEAD"])
                output = self.directory / name
                environment = dict(os.environ)
                environment.update({key: str(other / suffix) for key, suffix in selectors.items()})
                result = self.run_command(
                    self.repository.as_uri(), str(output), environment=environment
                )
                self.assertEqual(0, result.returncode, result.stderr)
                extracted = self.directory / f"extracted-{name}"
                extracted.mkdir()
                subprocess.run(
                    ["tar", "xf", f"{output}.tar", "-C", extracted], check=True
                )
                (contents,) = extracted.iterdir()
                (bundle,) = contents.glob("*.bundle")
                heads = subprocess.check_output(
                    ["git", "bundle", "list-heads", bundle]
                ).splitlines()
                self.assertIn(expected_head + b" HEAD", heads)
                self.assertTrue(all(line.split()[0] == expected_head for line in heads))
                subprocess.run(
                    ["tar", "xf", contents / "master.tar.xz", "-C", extracted], check=True
                )
                self.assertEqual(
                    "backup contents\n", (extracted / "master/file with spaces.txt").read_text()
                )
                self.assertEqual(
                    other_head, subprocess.check_output(["git", "-C", other, "rev-parse", "HEAD"])
                )
                for path, original in other_files.items():
                    self.assertEqual(original, path.read_bytes())

    def test_inherited_git_configuration_still_controls_local_transport(self) -> None:
        output = self.directory / "denied"
        environment = dict(
            os.environ,
            GIT_CONFIG_COUNT="1",
            GIT_CONFIG_KEY_0="protocol.file.allow",
            GIT_CONFIG_VALUE_0="never",
        )
        result = self.run_command(
            str(self.repository), str(output), environment=environment
        )
        self.assertNotEqual(0, result.returncode)
        self.assertIn(b"transport 'file' not allowed", result.stderr)
        self.assertFalse(Path(f"{output}.tar").exists())

    def test_refuses_to_overwrite_an_existing_archive_before_cloning(self) -> None:
        output = self.directory / "existing"
        archive = Path(f"{output}.tar")
        archive.write_text("keep me\n")
        git = self.directory / "git"
        git.write_text("#!/bin/sh\nexit 99\n")
        git.chmod(0o755)
        environment = os.environ.copy()
        environment["PATH"] = f"{self.directory}{os.pathsep}{environment['PATH']}"

        result = self.run_command("missing", str(output), environment=environment)

        self.assertEqual(1, result.returncode)
        self.assertEqual("keep me\n", archive.read_text())

    def test_clone_failure_preserves_no_partial_destination(self) -> None:
        fake_bin = self.directory / "fake-bin"
        fake_bin.mkdir()
        git = fake_bin / "git"
        git.write_text("#!/bin/sh\nexit 23\n")
        git.chmod(0o755)
        environment = os.environ.copy()
        environment["PATH"] = f"{fake_bin}{os.pathsep}{environment['PATH']}"
        output = self.directory / "failed"

        result = self.run_command("repository", str(output), environment=environment)

        self.assertEqual(23, result.returncode)
        self.assertFalse(Path(f"{output}.tar").exists())

    def test_installed_symlink_works_from_another_directory(self) -> None:
        for command in (COMMAND, COMPATIBILITY_COMMAND):
            with self.subTest(command=command.name):
                installed = self.directory / f"installed-{command.name}"
                installed.symlink_to(command)
                output = self.directory / f"linked-{command.name}"
                result = subprocess.run(
                    [installed, self.repository, output],
                    cwd="/",
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    check=False,
                )
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertTrue(Path(f"{output}.tar").is_file())

    @unittest.skipUnless(os.name == "posix", "byte paths require POSIX")
    @unittest.skipIf(sys.platform == "darwin", "macOS requires UTF-8 filenames")
    def test_undecodable_repository_and_destination_names_round_trip(self) -> None:
        source = os.fsencode(self.repository)
        unusual_source = os.path.join(os.fsencode(self.directory), b"repository-\xff")
        unusual_output = os.path.join(os.fsencode(self.directory), b"backup-\xfe")
        os.rename(source, unusual_source)

        result = subprocess.run(
            [os.fsencode(COMMAND), unusual_source, unusual_output],
            cwd=b"/",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertTrue(os.path.isfile(unusual_output + b".tar"))


if __name__ == "__main__":
    unittest.main()
