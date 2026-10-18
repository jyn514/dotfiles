"""Exercise the launcher's repository mounts on the existing Docker VM."""

import argparse
import contextlib
import json
from pathlib import Path
import runpy
import sys
import tempfile
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from docker_runtime import Docker
from repository_mounts_test import LAUNCHER, repository_fixture


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--image", required=True)
    args = parser.parse_args()
    runtime = Docker(args.state)
    image = runtime.inspect_image(args.image)
    launcher = runpy.run_path(str(LAUNCHER))
    mounts = launcher["agent_repository_mounts"]
    mounts.__globals__["OUTER_RUNTIME"] = runtime
    cases = [("directory", False, "common"), ("missing", False, "common")]
    cases.extend(("linked", absolute, backend)
                 for absolute in (False, True) for backend in ("worktree", "common"))
    for layout, absolute, backend in cases:
        with tempfile.TemporaryDirectory(prefix="repository-mounts-", dir=runtime.host.state / "scratch") as directory:
            state, git_dir, common = repository_fixture(Path(directory), layout, absolute=absolute)
            state.git_repository = git_dir if backend == "worktree" else common
            state.git_mount_source = state.git_repository
            entry = state.repository / ".git"
            original = entry.read_bytes() if entry.is_file() else None
            originally_missing = not entry.exists() and not entry.is_symlink()
            command = mounts(state)
            launcher["check_mount_destinations"](command)
            expected_common = common if absolute else Path("/src/team/main/.git")
            probe = Path(__file__).with_name("repository_mounts_probe.py")
            options = [
                "--network", "none", "--cap-drop=ALL", "--read-only",
                "--entrypoint", "python3", "--workdir", str(state.container_repository),
                "--env", f"EXPECTED_COMMON={expected_common}",
                "--mount", f"type=bind,src={probe},dst=/probe.py,readonly", *command,
            ]
            name = "repository-mounts-" + uuid.uuid4().hex[:12]
            with runtime.workload(image, name, options, ["/probe.py", layout]) as process:
                assert process.wait(timeout=20) == 0
            assert (state.repository / "created").read_text() == "writable"
            if original is not None:
                assert entry.read_bytes() == original
            if originally_missing:
                assert not entry.exists() and not entry.is_symlink(), "host .git entry was created"
            print(f"PASS: {layout}, absolute={absolute}, backend={backend}", flush=True)

    # The production validation flow, not a second hand-built mount planner,
    # supplies both authorities for these real disposable JJ repositories.
    from workspace_layout_test import git_fixture, native
    from workspace_layout import workspace_guest_root
    for layout in ("directory", "git-linked", "jj-linked"):
        with tempfile.TemporaryDirectory(prefix="shared-mounts-", dir=runtime.host.state / "scratch") as directory:
            root = Path(directory).resolve()
            home = root / "home"
            main_repo = git_fixture(home / "src/team/main")
            active = main_repo
            if layout == "git-linked":
                active = home / "src/team/worktree"
                native("git", "-C", str(main_repo), "worktree", "add", "--quiet", "--detach", str(active))
                native("jj", "git", "init", "--colocate", str(active), cwd=active)
            elif layout == "jj-linked":
                active = home / "src/team/worktree"
                native("jj", "workspace", "add", "--no-colocate", str(active), cwd=main_repo)
            dotfiles = git_fixture(root / "installed/dotfiles")
            (dotfiles / "skills").mkdir()
            (dotfiles / "skills/shared").write_text("original")
            (home / "src/dotfiles").mkdir()
            (home / "src/dotfiles/unrelated").write_text("do not hide")
            (home / "src/unlisted").mkdir()
            (home / ".agents").mkdir()
            (home / ".agents/skills").symlink_to(dotfiles / "skills")
            staging = root / "staged"
            staging.mkdir()
            from types import SimpleNamespace
            state = SimpleNamespace(home=home, skills_tmp=staging,
                                    skills_source=(home / ".agents/skills").resolve())
            validate = launcher["validate_repository"]
            old_dotfiles = validate.__globals__["DOTFILES"]
            validate.__globals__["DOTFILES"] = dotfiles
            try:
                with contextlib.chdir(active):
                    validate(state)
                assert state.workspaces[1].guest_root == workspace_guest_root(
                    home, active, state.container_repository, dotfiles)
                assert state.workspaces[1].guest_root != Path("/src/dotfiles")
                command = mounts(state)
                launcher["check_mount_destinations"](command)
                protected = sorted({str(target) for workspace in state.workspaces
                                    for _, target in workspace.metadata_mounts()} | {
                    str(workspace.guest_root / ".agents/sandbox") for workspace in state.workspaces
                    if (workspace.host_root / ".agents/sandbox").is_dir()})
                probe = Path(__file__).with_name("repository_mounts_probe.py")
                options = [
                    "--network", "none", "--cap-drop=ALL", "--read-only",
                    "--entrypoint", "python3", "--workdir", str(state.container_repository),
                    "--env", "WORKSPACE_ROOTS=" + json.dumps([str(workspace.guest_root) for workspace in state.workspaces]),
                    "--env", "PROTECTED_PATHS=" + json.dumps(protected),
                    "--mount", f"type=bind,src={state.skills_source},dst=/home/codex/.agents/skills",
                    "--mount", f"type=bind,src={probe},dst=/probe.py,readonly", *command,
                ]
                name = "shared-mounts-" + uuid.uuid4().hex[:12]
                with runtime.workload(image, name, options, ["/probe.py", "shared"]) as process:
                    assert process.wait(timeout=20) == 0
                for workspace in state.workspaces:
                    assert (workspace.host_root / "created").read_text() == "writable"
                assert (dotfiles / "skills/shared").read_text() == "live skills alias"
                assert (home / "src/dotfiles/unrelated").read_text() == "do not hide"
                print(f"PASS: shared workspace mounts, {layout}", flush=True)
            finally:
                validate.__globals__["DOTFILES"] = old_dotfiles
                if getattr(state, "workspaces_file", None) is not None:
                    state.workspaces_file.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
