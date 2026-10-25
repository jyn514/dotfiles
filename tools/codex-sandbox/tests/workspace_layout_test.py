"""Native disposable repositories exercise launch authority and pointer layouts."""
import json
import contextlib
from concurrent.futures import ThreadPoolExecutor
import threading
import os
from pathlib import Path
import runpy
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from workspace_layout import (
    WorkspaceError, WorkspaceLayout, discover_workspace, ensure_request_lock, workspace_guest_root,
)

LAUNCHER = Path(__file__).resolve().parents[1] / "codex-sandbox"


def native(*args, cwd=None):
    return subprocess.run(args, cwd=cwd, check=True, text=True, capture_output=True)


def git_fixture(path: Path, *, jj=True):
    path.mkdir(parents=True)
    native("git", "init", "--quiet", str(path))
    native("git", "-C", str(path), "-c", "user.name=Fixture", "-c",
           "user.email=fixture@example.invalid", "commit", "--quiet", "--allow-empty", "-m", "fixture")
    if jj:
        native("jj", "git", "init", "--colocate", str(path), cwd=path)
    (path / ".agents/sandbox").mkdir(parents=True)
    (path / ".agents/sandbox/policy").write_text("protected")
    (path / "ordinary").write_text("writable")
    return path


class WorkspaceLayoutTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.home = Path(self.temporary.name).resolve() / "home"
        (self.home / "src").mkdir(parents=True)
        self.main = git_fixture(self.home / "src/team/main")

    def test_native_layouts_keep_pointer_targets_and_share_backing_lock_identity(self):
        linked_git = self.home / "src/team/git-linked"
        native("git", "-C", str(self.main), "worktree", "add", "--quiet", "--detach", str(linked_git))
        native("jj", "git", "init", "--colocate", str(linked_git), cwd=linked_git)
        linked_jj = self.home / "src/team/jj-linked"
        native("jj", "workspace", "add", "--no-colocate", str(linked_jj), cwd=self.main)
        layouts = {}
        for root in (self.main, linked_git, linked_jj):
            with self.subTest(root=root.name):
                layout = discover_workspace(root, Path("/src/team") / root.name, self.home)
                layouts[root.name] = layout
                self.assertEqual(layout, WorkspaceLayout.from_dict(json.loads(json.dumps(layout.to_dict()))))
                ensure_request_lock(layout)
                inode = layout.lock_file.stat().st_ino
                ensure_request_lock(layout)
                self.assertEqual(inode, layout.lock_file.stat().st_ino)
                authority = layout.proxy_authority()
                self.assertEqual({"root", "git_dir", "common_dir", "jj_repo", "lock"}, set(authority))
                self.assertEqual("/run/jj-locks/" + layout.lock_file.name, authority["lock"])
                for path in (layout.git_dir, layout.common_dir, layout.jj_repo):
                    targets = [layout.guest_path(path)]
                    if not path.is_relative_to(root):
                        targets.append(path)
                    for target in targets:
                        self.assertTrue(any(path.is_relative_to(source)
                            and target == guest / path.relative_to(source)
                            for source, guest in layout.metadata_mounts()),
                            f"metadata backing path is not exposed: {path} -> {target}")
        self.assertEqual(layouts["main"].lock_file, layouts["jj-linked"].lock_file)
        self.assertNotEqual(layouts["main"].lock_file, layouts["git-linked"].lock_file)
        self.assertEqual(self.main / ".git/worktrees/git-linked", layouts["git-linked"].git_dir)
        self.assertEqual(self.main / ".git", layouts["git-linked"].common_dir)

    def test_persisted_records_parse_after_host_checkout_is_gone(self):
        layout = discover_workspace(self.main, Path("/src/main"), self.home)
        data = layout.to_dict()
        for key in data:
            if key != "guest_root":
                data[key] = "/missing" + data[key]
        recovered = WorkspaceLayout.from_dict(data)
        self.assertEqual(data, recovered.to_dict())
        self.assertTrue(recovered.metadata_mounts())
        for invalid in ({}, {**data, "unknown": "/extra"}, {**data, "host_root": "relative"},
                        {**data, "git_dir": "/unsafe,delimiter"}, {**data, "jj_repo": "/a/../b"},
                        {**data, "guest_root": "/src"}, {**data, "guest_root": "/other/repo"}):
            with self.subTest(invalid=invalid), self.assertRaises(WorkspaceError):
                WorkspaceLayout.from_dict(invalid)

    def test_guest_allocation_keeps_active_and_does_not_hide_visible_source_entries(self):
        outside = git_fixture(self.home / "elsewhere/installed-dotfiles")
        (self.home / "src/dotfiles").mkdir()
        (self.home / "src/dotfiles-1").symlink_to("missing")
        cases = [
            (self.main, Path("/src/team/main"), self.main, Path("/src/team/main")),
            (outside, Path("/src/repository"), outside, Path("/src/repository")),
            (self.main, Path("/src/team/main"), outside, Path("/src/dotfiles-2")),
            (outside, Path("/src/repository"), self.main, Path("/src/team/main")),
        ]
        for active, active_guest, dotfiles, expected in cases:
            with self.subTest(active=active, dotfiles=dotfiles):
                self.assertEqual(expected, workspace_guest_root(self.home, active, active_guest, dotfiles))

    def test_fallback_allocation_avoids_external_metadata_and_worktree_aliases(self):
        main = git_fixture(self.home / "outside/dotfiles-1")
        active = self.home / "outside/active"
        native("git", "-C", str(main), "worktree", "add", "--quiet", "--detach", str(active))
        native("jj", "git", "init", "--colocate", str(active), cwd=active)
        dotfiles = git_fixture(self.home / "installed/dotfiles")
        (self.home / "src/dotfiles").mkdir()
        layout = discover_workspace(active, Path("/src/repository"), self.home)
        reservations = [*layout.metadata_mounts(),
                        *((layout.host_root, alias) for alias in layout.repository_aliases())]
        self.assertEqual(Path("/src/dotfiles-2"), workspace_guest_root(
            self.home, active, layout.guest_root, dotfiles, reserved=reservations))

    def test_validate_initializes_git_only_dotfiles_without_changing_cwd_and_deduplicates(self):
        launcher = runpy.run_path(str(LAUNCHER))
        dotfiles = git_fixture(self.home / "installed/dotfiles", jj=False)
        state = SimpleNamespace(home=self.home)
        function = launcher["validate_repository"]
        with mock.patch.dict(function.__globals__, DOTFILES=dotfiles), \
                contextlib.chdir(self.main):
            before = Path.cwd()
            function(state)
            self.assertEqual(before, Path.cwd())
            self.addCleanup(state.workspaces_file.unlink, missing_ok=True)
            self.assertEqual([self.main, dotfiles], [item.host_root for item in state.workspaces])
            self.assertEqual([item.to_dict() for item in state.workspaces], json.loads(state.workspaces_file.read_text()))
            metadata = (dotfiles / ".jj/repo").stat().st_ino
            launcher["initialize_dotfiles"](dotfiles)
            self.assertEqual(metadata, (dotfiles / ".jj/repo").stat().st_ino)
        with mock.patch.dict(function.__globals__, DOTFILES=self.main), \
                contextlib.chdir(self.main):
            function(state)
            self.addCleanup(state.workspaces_file.unlink, missing_ok=True)
            self.assertEqual(1, len(state.workspaces))

    def test_concurrent_initializers_recheck_under_existing_coordination_lock(self):
        launcher = runpy.run_path(str(LAUNCHER))
        root = git_fixture(self.home / "concurrent/dotfiles", jj=False)
        start = threading.Barrier(2)

        def initialize():
            start.wait(timeout=5)
            launcher["initialize_dotfiles"](root)

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(initialize) for _ in range(2)]
            for future in futures:
                future.result(timeout=10)
        layout = discover_workspace(root, Path("/src/dotfiles"), self.home)
        self.assertEqual(root / ".jj/repo", layout.jj_repo)

    def test_relocated_authority_drives_resources_and_vm_permissions(self):
        launcher = runpy.run_path(str(LAUNCHER))
        dotfiles = git_fixture(self.home / "elsewhere/dotfiles")
        (dotfiles / "skills").mkdir()
        (self.home / ".codex").mkdir()
        (self.home / ".codex/config.toml").touch()
        for relative in ("README.md", "docs", "examples"):
            path = self.home / "pi-package" / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.touch()
        runtime_directory = self.home / ".cache/proxy-session"
        runtime_directory.mkdir(parents=True)
        workspaces = [discover_workspace(self.main, Path("/src/team/main"), self.home),
                      discover_workspace(dotfiles, Path("/src/dotfiles-3"), self.home)]
        for workspace in workspaces:
            ensure_request_lock(workspace)
        state = SimpleNamespace(home=self.home, repository=self.main,
            container_repository=workspaces[0].guest_root, host_pi_package=self.home / "pi-package",
            workspaces=workspaces, workspaces_file=None, skills_source=dotfiles / "skills",
            metadata_roots=tuple(path for workspace in workspaces for path in
                                 (workspace.host_root / ".jj", workspace.git_dir, workspace.common_dir, workspace.jj_repo)),
            skills_tmp=dotfiles, zuliprc=None, agent_docker=None)
        with mock.patch.dict(launcher["host_pi_resource_paths"].__globals__,
                installed_config_source=lambda _: dotfiles / "config/pi-agent/AGENTS.md"):
            resources = launcher["host_pi_resource_paths"](state)
        self.assertEqual("/src/dotfiles-3", resources[str(dotfiles)])
        self.assertEqual("/src/dotfiles-3/config/pi-agent/AGENTS.md",
                         resources[str(self.home / ".pi/agent/AGENTS.md")])
        backend = mock.Mock()
        with mock.patch.dict(launcher["preflight_lima"].__globals__, OUTER_RUNTIME=backend,
                _secure_codex_auth_directory=lambda _: None,
                proxy_module=lambda: SimpleNamespace(runtime_directory=lambda _: runtime_directory)):
            launcher["preflight_lima"](state)
        binds = backend.check_binds.call_args.args[0]
        for workspace in workspaces:
            self.assertIn((workspace.host_root, True), binds)
            self.assertIn((workspace.lock_file, True), binds)
        self.assertIn((runtime_directory, False), binds)

    def test_join_and_attach_pass_the_same_workspace_description_file(self):
        launcher = runpy.run_path(str(LAUNCHER))
        state = SimpleNamespace(repository=self.main, container_repository=Path("/src/main"),
            workspaces_file=self.home / "workspaces.json", uid=os.getuid(), gid=os.getgid(),
            proxy_state=self.home / "state.json", proxy_prefix="fixture", image="agent",
            sidecar_image="", manifest=self.home / "manifest.json", prepared_images=None,
            policy_source_present=False, zuliprc=None, proxy_lock=mock.Mock(shared=False))
        seen = []

        def helper(*arguments):
            seen.append(arguments)
            if arguments[0] == "join":
                Path(arguments[arguments.index("--manifest") + 1]).write_text('{"capabilities": {}}')
                Path(arguments[arguments.index("--accepted") + 1]).write_text(json.dumps({
                    "source-present": False, "agent-image": "agent", "helper-image": ""}))

        function_globals = launcher["attach_proxies"].__globals__
        with mock.patch.dict(function_globals, helper=helper,
                _secure_codex_auth_directory=lambda _: None, check_agent_pi_revision=lambda *_: None,
                attach_codex_sidecar=lambda *_: [], finalize_proxy_session=lambda *_: []):
            launcher["load_accepted_session"](state)
            launcher["attach_proxies"](state)
        for arguments in seen:
            self.assertEqual(str(state.workspaces_file), arguments[arguments.index("--workspaces") + 1])
        for path in (state.manifest, state.prepared_images):
            path.unlink(missing_ok=True)

    def test_read_only_active_validation_does_not_prepare_dotfiles_or_authority(self):
        launcher = runpy.run_path(str(LAUNCHER))
        scratch = self.home / "validation-scratch"
        scratch.mkdir()
        missing = self.home / "absent-dotfiles"
        git_only = git_fixture(self.home / "git-only-dotfiles", jj=False)
        cache = Path.home() / ".cache/codex-sandbox-proxies"
        before_cache = set(cache.rglob("*")) if cache.exists() else set()
        for dotfiles in (missing, git_only):
            state = SimpleNamespace(home=self.home)
            with self.subTest(dotfiles=dotfiles), mock.patch.dict(
                    launcher["validate_repository"].__globals__, DOTFILES=dotfiles,
                    scratch_directory=lambda: scratch), contextlib.chdir(self.main):
                launcher["validate_repository"](state, initialize_missing=False)
            self.assertEqual(self.main, state.repository)
            self.assertEqual(self.main / ".git", state.git_repository)
            self.assertFalse((dotfiles / ".jj").exists())
            self.assertFalse(hasattr(state, "workspaces_file"))
            self.assertFalse(hasattr(state, "workspaces"))
            self.assertFalse(hasattr(state, "container_repository"))
            self.assertEqual([], list(scratch.iterdir()))
            self.assertFalse((self.home / ".cache").exists())
        self.assertFalse(missing.exists())
        self.assertEqual(before_cache, set(cache.rglob("*")) if cache.exists() else set())

    def test_read_only_destination_rejects_git_only_active_without_initializing_it(self):
        launcher = runpy.run_path(str(LAUNCHER))
        active = git_fixture(self.home / "git-only-active", jj=False)
        with mock.patch.dict(launcher["validate_repository"].__globals__,
                DOTFILES=self.home / "absent-dotfiles"), contextlib.chdir(active):
            with self.assertRaisesRegex(launcher["LauncherError"], "not an existing Jujutsu workspace"):
                launcher["validate_repository"](SimpleNamespace(home=self.home), initialize_missing=False)
        self.assertFalse((active / ".jj").exists())
        self.assertFalse((self.home / "absent-dotfiles").exists())

    def test_malformed_dotfiles_is_not_reinitialized(self):
        launcher = runpy.run_path(str(LAUNCHER))
        for kind in ("file", "directory", "symlink"):
            root = git_fixture(self.home / kind, jj=False)
            entry = root / ".jj"
            if kind == "file":
                entry.write_text("broken metadata")
            elif kind == "directory":
                entry.mkdir()
                (entry / "repo").write_text("missing-backing-store")
            else:
                entry.symlink_to("missing-metadata")
            with self.subTest(kind=kind), mock.patch.dict(
                    launcher["validate_repository"].__globals__, DOTFILES=root), \
                    contextlib.chdir(self.main):
                with self.assertRaisesRegex(launcher["LauncherError"], str(root)):
                    launcher["validate_repository"](SimpleNamespace(home=self.home))
            self.assertTrue(entry.exists() or entry.is_symlink())
            self.assertFalse((entry / "working_copy").exists())


if __name__ == "__main__":
    unittest.main()
