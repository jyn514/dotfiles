from __future__ import annotations

import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[3]


class SelectedRemoteTests(unittest.TestCase):
    def test_revision_belongs_to_selected_repository_without_restricting_branches(self) -> None:
        # All branches of the selected remote remain eligible. A newer commit
        # in another repository must not supply its revision or matching lines.
        for selected in ("origin", "upstream"):
            for match in ("main", "feature", "missing"):
                with self.subTest(selected=selected, match=match):
                    self.check_selected_remote(selected, match)

    def test_remote_head_range_ignores_local_branch_and_tag_collisions(self) -> None:
        for selected in ("origin", "upstream"):
            for namespace in ("heads", "tags"):
                with self.subTest(selected=selected, namespace=namespace):
                    self.check_selected_remote(selected, "main", namespace)

    def check_selected_remote(
        self, selected: str, match: str, collision_namespace: str | None = None,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            # Native Git must use only these private repositories/configurations,
            # even when the test is launched from a Git hook or alternate worktree.
            environment = {
                key: value for key, value in os.environ.items()
                if not key.startswith("GIT_")
            } | {
                "DISPLAY": "",
                "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_CONFIG_GLOBAL": os.devnull,
                "GIT_AUTHOR_NAME": "Test",
                "GIT_AUTHOR_EMAIL": "test@example.com",
                "GIT_COMMITTER_NAME": "Test",
                "GIT_COMMITTER_EMAIL": "test@example.com",
            }

            def git(repository: Path, *arguments: str, day: int = 1) -> bytes:
                date = f"2020-01-{day:02d}T00:00:00+0000"
                return subprocess.check_output(
                    ["git", "-C", str(repository), *arguments],
                    env=environment | {"GIT_AUTHOR_DATE": date, "GIT_COMMITTER_DATE": date},
                    stderr=subprocess.PIPE,
                )

            remote_repository = root / "selected"
            remote_repository.mkdir()
            git(remote_repository, "init", "-q", "-b", "main")
            source = remote_repository / "file"

            def commit(contents: str, message: str, day: int) -> bytes:
                source.write_text(contents)
                git(remote_repository, "add", "file")
                git(remote_repository, "commit", "-qm", message, day=day)
                return git(remote_repository, "rev-parse", "HEAD").strip()

            commit("base\n", "base", 1)
            main = commit("prefix\nneedle\n" if match == "main" else "other\n", "main", 2)
            git(remote_repository, "checkout", "-qb", "feature")
            feature = commit("one\ntwo\nneedle\n", "feature", 3) if match == "feature" else main
            git(remote_repository, "checkout", "-q", "main")

            foreign = root / "foreign"
            foreign.mkdir()
            git(foreign, "init", "-q", "-b", "main")
            (foreign / "file").write_text("one\ntwo\nthree\nneedle\n")
            git(foreign, "add", "file")
            git(foreign, "commit", "-qm", "foreign", day=4)
            foreign_revision = git(foreign, "rev-parse", "HEAD").strip()
            absent = subprocess.run(
                ["git", "-C", str(remote_repository), "cat-file", "-e", foreign_revision],
                env=environment, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
            )
            self.assertNotEqual(0, absent.returncode)

            checkout = root / "checkout"
            git(root, "clone", "-q", str(remote_repository), str(checkout))
            if selected == "upstream":
                git(checkout, "remote", "rename", "origin", "upstream")
            git(checkout, "remote", "set-url", selected, "https://github.com/selected/project.git")
            # The prefix lookalike also rejects a tempting but too-broad
            # --remotes=origin* / --remotes=upstream* namespace pattern.
            other = "origin" if selected == "upstream" else "origin-extra"
            git(checkout, "remote", "add", other, "https://github.com/foreign/project.git")
            git(checkout, "fetch", "-q", str(foreign), f"refs/heads/main:refs/remotes/{other}/main")
            git(checkout, "update-ref", f"refs/remotes/{selected}-extra/main", foreign_revision.decode())
            local_source = checkout / "file"
            if collision_namespace:
                local_source.write_text("local one\nlocal two\nneedle\n")
                git(checkout, "add", "file")
                git(checkout, "commit", "-qm", "local-only contents", day=5)
                # For a collision at this child, HEAD~^! adds its local-only
                # parent and excludes the actual remote tip from consideration.
                git(checkout, "commit", "--allow-empty", "-qm", "local child", day=6)
                git(checkout, "update-ref", f"refs/{collision_namespace}/{selected}/HEAD", "HEAD")
            local_source.write_text("needle\n")
            result = subprocess.run(
                [str(ROOT / "bin/remote-git-url"), str(local_source), "1"],
                cwd=checkout, env=environment,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
            )
            revision, line = {
                "main": (main, 2), "feature": (feature, 3), "missing": (b"HEAD", 1),
            }[match]
            self.assertEqual(1, result.returncode, result.stderr)
            self.assertEqual(
                b"https://github.com/selected/project/blob/" + revision
                + f"/file#L{line}\n".encode(),
                result.stdout,
            )
            if match == "missing":
                self.assertIn(b"does not exist in upstream", result.stderr)
            else:
                self.assertEqual(b"", result.stderr)


if __name__ == "__main__":
    unittest.main()
