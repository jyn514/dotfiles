"""Image fixture generation and commit queries use the consuming JJ interfaces."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from shared_workspace_probe import fixture_commit_revision, initialize_fixture_metadata


TRUSTED_CONFIG = Path(__file__).resolve().parents[2] / "jj-proxy/jj.toml"


class FixtureMetadataTest(unittest.TestCase):
    def test_fixture_queries_find_native_commits_and_their_scoped_changes(self):
        jj = os.environ.get("DOTFILES_TEST_JJ_REAL", "jj")
        with tempfile.TemporaryDirectory(prefix="fixture-jj-descriptions-") as directory:
            root = Path(directory).resolve()
            repository = root / "repository"
            environment = dict(os.environ, HOME=str(root / "home"),
                               XDG_CONFIG_HOME=str(root / "configuration"))

            def native(identity, *arguments, cwd=root):
                return subprocess.run([jj, "--config-file", str(TRUSTED_CONFIG),
                                       "--config", f"user.name={identity}",
                                       "--config", f"user.email={identity}@example.test", *arguments],
                                      cwd=cwd, env=environment, text=True, capture_output=True, check=True).stdout.strip()

            native("Pi-A", "git", "init", "--colocate", str(repository))
            commits = [("A skill", "Pi-A", "skill"), ("B unrelated", "Pi-B", "unrelated")]
            for message, identity, filename in commits:
                (repository / filename).write_text(filename)
                native(identity, "-R", str(repository), "metaedit", "--update-author", "-r", "@")
                native(identity, "-R", str(repository), "commit", f"root:{filename}", "-m", message)
            for message, identity, filename in commits:
                revision = fixture_commit_revision(message)
                attribution = native(identity, "-R", str(repository), "--ignore-working-copy",
                                     "log", "--no-graph", "-r", revision,
                                     "-T", 'author.name() ++ "|" ++ committer.name()')
                self.assertEqual(f"{identity}|{identity}", attribution)
                self.assertEqual(filename, native(identity, "-R", str(repository), "--ignore-working-copy",
                                                  "diff", "-r", revision, "--name-only", cwd=repository))

    def test_consuming_jj_initializes_ordinary_and_absolute_linked_metadata(self):
        jj = os.environ.get("DOTFILES_TEST_JJ_REAL", "jj")
        for linked in (False, True):
            with self.subTest(linked=linked), tempfile.TemporaryDirectory(prefix="fixture jj image-") as directory:
                root = Path(directory).resolve()
                (root / "home/src").mkdir(parents=True)
                dotfiles = root / "external-dotfiles"
                environment = dict(os.environ, HOME=str(root / "home"),
                                   XDG_CONFIG_HOME=str(root / "configuration"),
                                   JJ_FIXTURE_REAL=jj, JJ_FIXTURE_CONFIG=str(TRUSTED_CONFIG))
                if linked:
                    help_result = subprocess.run([jj, "workspace", "add", "--help"], cwd=root,
                                                 env=environment, capture_output=True, text=True, check=True)
                    if "--colocate" not in help_result.stdout:
                        self.skipTest("local JJ predates colocated linked workspaces; run the pinned-image probe")

                def image_reader(*command, input):
                    image = command.index("pinned-jj-image")
                    self.assertEqual("/trusted/bin/sh", command[command.index("--entrypoint") + 1])
                    self.assertIn(f"type=volume,src=fixture-volume,dst={root}", command)
                    result = subprocess.run(["/bin/sh", *command[image + 1:]], input=input, cwd=root,
                                            env=environment, capture_output=True, text=True)
                    self.assertEqual(0, result.returncode, result.stderr)
                    return result

                initialize_fixture_metadata(image_reader, "pinned-jj-image", "fixture-volume", root, linked=linked)
                (dotfiles / "skill").write_text("fixture data\n")
                repositories = [root / "home/src/project", root / "home/src/sibling", dotfiles]
                if linked:
                    main = root / "home/src/linked-source"
                    self.assertEqual(str(main / ".jj/repo"), (dotfiles / ".jj/repo").read_text())
                    self.assertTrue((dotfiles / ".git").is_file())
                    repositories.append(main)
                for repository in repositories:
                    before = {path.relative_to(repository): path.read_bytes()
                              for path in (repository / ".jj").rglob("*") if path.is_file()}
                    status = subprocess.run([jj, "--config-file", str(TRUSTED_CONFIG), "--repository", str(repository),
                                             "--ignore-working-copy", "status"], cwd=root, env=environment,
                                            capture_output=True, text=True)
                    self.assertEqual(0, status.returncode, status.stderr)
                    after = {path.relative_to(repository): path.read_bytes()
                             for path in (repository / ".jj").rglob("*") if path.is_file()}
                    self.assertEqual(before, after)

    def test_failed_initialization_stops_without_publishing_metadata(self):
        with tempfile.TemporaryDirectory(prefix="fixture-jj-failure-") as directory:
            root = Path(directory).resolve()
            (root / "home/src").mkdir(parents=True)
            environment = dict(os.environ, HOME=str(root / "home"),
                               XDG_CONFIG_HOME=str(root / "configuration"),
                               JJ_FIXTURE_REAL=shutil.which("false"), JJ_FIXTURE_CONFIG=str(TRUSTED_CONFIG))

            def failing_reader(*command, input):
                image = command.index("pinned-jj-image")
                return subprocess.run(["/bin/sh", *command[image + 1:]], input=input, cwd=root,
                                      env=environment, capture_output=True, text=True, check=True)

            with self.assertRaises(subprocess.CalledProcessError):
                initialize_fixture_metadata(failing_reader, "pinned-jj-image", "fixture-volume", root, linked=True)
            self.assertFalse(list(root.rglob(".jj")))


if __name__ == "__main__":
    unittest.main()
