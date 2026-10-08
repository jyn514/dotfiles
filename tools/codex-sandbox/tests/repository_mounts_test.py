"""Workspace mounts preserve Git indirection and protect its metadata."""

from pathlib import Path
import runpy
import subprocess
import tempfile
from types import SimpleNamespace
import unittest


LAUNCHER = Path(__file__).resolve().parents[1] / "codex-sandbox"


def repository_fixture(root: Path, layout: str, *, absolute: bool = False):
    """Create native Git layouts shared by unit and container regressions."""
    home = root / "home"
    main = home / "src/team/main"
    main.mkdir(parents=True)
    subprocess.run(["git", "init", "--quiet", str(main)], check=True)
    subprocess.run([
        "git", "-C", str(main), "-c", "user.name=Fixture", "-c",
        "user.email=fixture@example.invalid", "commit", "--quiet", "--allow-empty",
        "-m", "fixture",
    ], check=True)
    common = main / ".git"
    if layout == "directory":
        repo, git_dir = main, common
    elif layout == "linked":
        repo = home / "src/team/worktree"
        subprocess.run([
            "git", "-C", str(main), "worktree", "add", "--quiet", "--detach", str(repo),
        ], check=True)
        git_dir = common / "worktrees/worktree"
        pointer = git_dir if absolute else Path("../main/.git/worktrees/worktree")
        (repo / ".git").write_text(f"gitdir: {pointer}\n")
    elif layout == "missing":
        repo, git_dir = home / "src/team/workspace", common
        repo.mkdir()
    else:
        raise ValueError(layout)
    (repo / ".jj").mkdir()
    (repo / ".jj/marker").write_text("protected")
    staging = root / "staged"
    staging.mkdir()
    state = SimpleNamespace(
        home=home, repository=repo, container_repository=Path("/src/team") / repo.name,
        skills_tmp=staging, git_repository=common, git_mount_source=common,
    )
    return state, git_dir, common


class RepositoryMountsTest(unittest.TestCase):
    def test_linked_worktree_preserves_the_gitfile_for_both_backend_paths(self):
        launcher = runpy.run_path(str(LAUNCHER))
        mounts = launcher["agent_repository_mounts"]
        for absolute in (False, True):
            for backend in ("worktree", "common"):
                with self.subTest(absolute=absolute, backend=backend), tempfile.TemporaryDirectory() as directory:
                    state, git_dir, common = repository_fixture(Path(directory), "linked", absolute=absolute)
                    state.git_repository = git_dir if backend == "worktree" else common
                    state.git_mount_source = state.git_repository
                    command = mounts(state)
                    launcher["check_mount_destinations"](command)
                    gitfile_mounts = [argument for argument in command
                                      if f"dst={state.container_repository}/.git," in argument]
                    self.assertEqual([
                        f"type=bind,src={state.repository / '.git'},"
                        f"dst={state.container_repository / '.git'},readonly",
                    ], gitfile_mounts)
                    self.assertIn(f"type=bind,src={common},dst={common},readonly", command)
                    self.assertIn(f"type=bind,src={common},dst=/src/team/main/.git,readonly", command)

    def test_directory_and_missing_git_entries_keep_a_directory_overlay(self):
        launcher = runpy.run_path(str(LAUNCHER))
        for layout in ("directory", "missing"):
            with self.subTest(layout=layout), tempfile.TemporaryDirectory() as directory:
                state, _, common = repository_fixture(Path(directory), layout)
                command = launcher["agent_repository_mounts"](state)
                launcher["check_mount_destinations"](command)
                self.assertEqual(1, command.count(
                    f"type=bind,src={common},dst={state.container_repository / '.git'},readonly",
                ))


if __name__ == "__main__":
    unittest.main()
