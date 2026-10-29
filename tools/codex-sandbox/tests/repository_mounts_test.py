"""Workspace mounts preserve Git indirection and protect its metadata."""

from pathlib import Path
import runpy
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock


LAUNCHER = Path(__file__).resolve().parents[1] / "codex-sandbox"


def repository_fixture(root: Path, layout: str, *, absolute: bool = False):
    """Create native Git layouts shared by unit and container regressions."""
    from workspace_layout_test import git_fixture, native
    from workspace_layout import discover_workspace
    home = root / "home"
    main = git_fixture(home / "src/team/main")
    common = main / ".git"
    if layout == "directory":
        repo, git_dir = main, common
    elif layout == "linked":
        repo = home / "src/team/worktree"
        native("git", "-C", str(main), "worktree", "add", "--quiet", "--detach", str(repo))
        native("jj", "git", "init", "--colocate", str(repo), cwd=repo)
        git_dir = common / "worktrees/worktree"
        pointer = git_dir if absolute else Path("../main/.git/worktrees/worktree")
        (repo / ".git").write_text(f"gitdir: {pointer}\n")
    elif layout == "missing":
        repo, git_dir = home / "src/team/workspace", common
        native("jj", "workspace", "add", "--no-colocate", str(repo), cwd=main)
    else:
        raise ValueError(layout)
    (repo / ".jj/marker").write_text("protected")
    staging = root / "staged"
    staging.mkdir()
    guest = Path("/src/team") / repo.name
    state = SimpleNamespace(
        home=home, repository=repo, container_repository=guest,
        skills_tmp=staging, git_repository=common, git_mount_source=common,
        workspaces=[discover_workspace(repo, guest, home)],
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


class SharedWorkspaceMountsTest(unittest.TestCase):
    def test_real_layouts_mount_two_writable_roots_once_and_protect_every_metadata_alias(self):
        from workspace_layout_test import git_fixture, native
        from workspace_layout import discover_workspace
        for layout in ("directory", "git-linked", "jj-linked"):
            with self.subTest(layout=layout), tempfile.TemporaryDirectory() as directory:
                root = Path(directory).resolve()
                home = root / "home"
                main = git_fixture(home / "src/team/main")
                repo = main
                if layout == "git-linked":
                    repo = home / "src/team/worktree"
                    native("git", "-C", str(main), "worktree", "add", "--quiet", "--detach", str(repo))
                    native("jj", "git", "init", "--colocate", str(repo), cwd=repo)
                elif layout == "jj-linked":
                    repo = home / "src/team/worktree"
                    native("jj", "workspace", "add", "--no-colocate", str(repo), cwd=main)
                dotfiles = git_fixture(root / "relocated/dotfiles")
                (dotfiles / "skills").mkdir()
                staging = root / "staged"
                staging.mkdir()
                state = SimpleNamespace(home=home, repository=repo,
                    container_repository=Path("/src/team") / repo.name,
                    skills_tmp=staging, skills_source=dotfiles / "skills",
                    workspaces=[discover_workspace(repo, Path("/src/team") / repo.name, home),
                                discover_workspace(dotfiles, Path("/src/dotfiles-2"), home)])
                launcher = runpy.run_path(str(LAUNCHER))
                command = launcher["agent_repository_mounts"](state)
                launcher["check_mount_destinations"](command)
                self.assertEqual(command, launcher["agent_repository_mounts"](state),
                                 "a second consumer must reuse the one source view")
                records = [item for item in command if item.startswith("type=bind,")]
                work_volumes = {
                    launcher["workspace_work_volume"](workspace)[0]
                    for workspace in state.workspaces
                }
                self.assertEqual(len(state.workspaces), len(work_volumes))
                for workspace in state.workspaces:
                    root_mount = [item for item in records if f"dst={workspace.guest_root}," in item]
                    self.assertEqual(1, len(root_mount))
                    self.assertNotIn("readonly", root_mount[0])
                    for source, target in workspace.metadata_mounts():
                        self.assertIn(f"type=bind,src={source},dst={target},readonly", records)
                    policy = workspace.host_root / ".agents/sandbox"
                    if policy.is_dir():
                        self.assertIn(f"type=bind,src={policy},dst={workspace.guest_root}/.agents/sandbox,readonly", records)
                    volume, _ = launcher["workspace_work_volume"](workspace)
                    self.assertIn(
                        f"type=volume,src={volume},dst={workspace.guest_root}/work",
                        command,
                    )
                self.assertFalse((home / "src/dotfiles-2").exists(), "scaffolding must not mutate host sources")

    def test_workspace_work_volume_is_stable_guest_storage_and_refuses_hidden_host_data(self):
        from workspace_layout_test import git_fixture
        from workspace_layout import discover_workspace
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory).resolve()
            repo = git_fixture(home / "src/project")
            workspace = discover_workspace(repo, Path("/src/project"), home)
            state = SimpleNamespace(workspaces=[workspace], uid=501, gid=20)
            launcher = runpy.run_path(str(LAUNCHER))
            runtime = mock.Mock()
            with mock.patch.dict(
                    launcher["prepare_workspace_work_volumes"].__globals__,
                    OUTER_RUNTIME=runtime):
                launcher["prepare_workspace_work_volumes"](state)
            volume, owner = launcher["workspace_work_volume"](workspace)
            self.assertEqual(
                mock.call(volume, 501, 20, owner, role="workspace-work"),
                runtime.create_owned_volume.call_args,
            )
            self.assertEqual([], list((repo / "work").iterdir()))

            (repo / "work/host-artifact").write_text("keep")
            with mock.patch.dict(
                    launcher["prepare_workspace_work_volumes"].__globals__,
                    OUTER_RUNTIME=runtime), self.assertRaisesRegex(
                        launcher["LauncherError"],
                        "non-empty host work directory for active workspace"):
                launcher["prepare_workspace_work_volumes"](state)
            self.assertEqual(1, runtime.create_owned_volume.call_count)

            dotfiles = git_fixture(home / "src/dotfiles")
            dotfiles_workspace = discover_workspace(
                dotfiles, Path("/src/dotfiles"), home)
            (dotfiles / "work").mkdir()
            (dotfiles / "work/host-artifact").write_text("keep")
            state.workspaces = [workspace, dotfiles_workspace]
            (repo / "work/host-artifact").unlink()
            with mock.patch.dict(
                    launcher["prepare_workspace_work_volumes"].__globals__,
                    OUTER_RUNTIME=runtime), self.assertRaisesRegex(
                        launcher["LauncherError"],
                        "non-empty host work directory for launcher dotfiles workspace"):
                launcher["prepare_workspace_work_volumes"](state)

    def test_one_authority_deduplicates_active_dotfiles_mounts(self):
        from workspace_layout_test import git_fixture
        from workspace_layout import discover_workspace
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory).resolve()
            repo = git_fixture(home / "src/relocated")
            state = SimpleNamespace(home=home, skills_tmp=home / "staged",
                workspaces=[discover_workspace(repo, Path("/src/relocated"), home)])
            launcher = runpy.run_path(str(LAUNCHER))
            command = launcher["agent_repository_mounts"](state)
            launcher["check_mount_destinations"](command)
            roots = [item for item in command if "dst=/src/relocated," in item]
            self.assertEqual(1, len(roots))

    def test_conflicting_workspace_destinations_fail_before_mount_construction(self):
        from workspace_layout_test import git_fixture
        from workspace_layout import discover_workspace
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory).resolve()
            first = git_fixture(home / "src/first")
            second = git_fixture(home / "src/second")
            state = SimpleNamespace(home=home, skills_tmp=home / "staged", workspaces=[
                discover_workspace(root, Path("/src/repository"), home) for root in (first, second)])
            launcher = runpy.run_path(str(LAUNCHER))
            with self.assertRaisesRegex(launcher["LauncherError"], "Conflicting workspace mount"):
                launcher["agent_repository_mounts"](state)


if __name__ == "__main__":
    unittest.main()
