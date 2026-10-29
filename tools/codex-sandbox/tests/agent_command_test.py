from __future__ import annotations

from pathlib import Path
import runpy
from types import SimpleNamespace
import tempfile
import unittest
from unittest import mock
import uuid


ROOT = Path(__file__).resolve().parents[3]
LAUNCHER = ROOT / "tools/codex-sandbox/codex-sandbox"


class AgentCommandTest(unittest.TestCase):
    def test_user_cache_volume_has_stable_vm_wide_identity(self) -> None:
        launcher = runpy.run_path(str(LAUNCHER))
        runtime = mock.Mock()
        state = SimpleNamespace(uid=501, gid=20)
        with mock.patch.dict(
                launcher["prepare_user_cache_volume"].__globals__,
                OUTER_RUNTIME=runtime):
            launcher["prepare_user_cache_volume"](state)
        runtime.create_owned_volume.assert_called_once_with(
            "codex-user-cache-v1", 501, 20, "codex-user-cache:v1",
            role="user-cache",
        )

    def test_host_pi_resource_paths_bind_prompt_paths_to_guest_mounts(self) -> None:
        launcher = runpy.run_path(str(LAUNCHER))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = SimpleNamespace(
                home=root / "home",
                host_pi_package=root / "pi-package",
                repository=Path("/Users/jyn/src/personal/lapwing/stint"),
                container_repository=Path("/src/personal/lapwing/stint"),
            )
            agents_source = state.home / "src/dotfiles/renamed-instructions.md"
            agents_source.parent.mkdir(parents=True)
            agents_source.write_text("Host instructions.\n", encoding="utf-8")
            resource_paths = launcher["host_pi_resource_paths"]
            with mock.patch.dict(resource_paths.__globals__, {
                "installed_config_source": lambda _target: agents_source,
            }):
                paths = resource_paths(state)
            self.assertEqual(
                "/src/dotfiles/renamed-instructions.md",
                paths[str(state.home / ".pi/agent/AGENTS.md")],
            )
            self.assertNotIn("/home/codex/.pi/agent/AGENTS.md", paths.values())

            self.assertEqual(
                "/src/personal/lapwing/stint",
                paths[str(state.repository)],
            )
            self.assertEqual(
                "/opt/agent-pi/src/packages/coding-agent/docs",
                paths[str(state.host_pi_package / "docs")],
            )
            self.assertEqual(
                "/home/codex/.agents/skills",
                paths[str(state.home / ".agents/skills")],
            )
            self.assertEqual(
                "/home/codex/.agents/sandbox",
                paths[str(state.home / ".agents/sandbox")],
            )
            self.assertEqual(
                "/home/codex/.pi/agent/sessions",
                paths[str(state.home / ".pi/agent/sessions")],
            )
            self.assertEqual(
                "/home/codex/.pi/agent/pi-codex-subagents/runs",
                paths[str(state.home / ".pi/agent/pi-codex-subagents/runs")],
            )
            for source, destination in launcher["STAGED_CONFIG"].values():
                host_path = state.home / source.removeprefix("$HOME/")
                self.assertEqual(destination, paths[str(host_path)])

    def test_host_worker_command_uses_resource_paths_and_session_channel(self) -> None:
        launcher = runpy.run_path(str(LAUNCHER))
        build = launcher["build_agent_command"]
        from workspace_layout_test import git_fixture
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = SimpleNamespace(
                codex_container="agent-container",
                github_credential=None,
                term="xterm-256color",
                pi_model_session_id=str(uuid.uuid4()),
                pi_agent_tmp=root / "private-agent",
                skills_source=root / "skills",
                skills_tmp=root / "staged",
                home=root / "home",
                host_pi_package=root / "pi-package",
                container_repository=Path("/src/repository"),
                repository=root / "repository",
                host_working_directory=root / "repository",
                git_repository=root / "repository/.git",
                git_mount_source=root / "repository/.git",
            )
            state.pi_agent_tmp.mkdir()
            state.skills_source.mkdir()
            state.skills_tmp.mkdir()
            (state.home / "src").mkdir(parents=True)
            (state.host_pi_package / "README.md").parent.mkdir(parents=True)
            for relative in ("README.md", "docs", "examples"):
                path = state.host_pi_package / relative
                path.mkdir() if "." not in path.name else path.touch()
            git_fixture(state.repository)
            dotfiles = git_fixture(root / "installed/dotfiles")
            state.workspaces = [
                launcher["discover_workspace"](state.repository, state.container_repository, state.home),
                launcher["discover_workspace"](dotfiles, Path("/src/shared-dotfiles"), state.home),
            ]
            extensions = root / "pi-extensions"
            extensions.mkdir()

            resource_paths = launcher["host_pi_resource_paths"](state)
            with mock.patch.dict(build.__globals__, {
                "OUTER_RUNTIME": SimpleNamespace(nonrecursive_bind="bind-nonrecursive"),
                "proxy_flags": lambda: [],
                "staged_config_path": lambda _state, _role: root / "config",
                "installed_config_source": lambda _path: root / "installed-config",
            }):
                command = build(
                    state, ["image", "pi"], timing=False,
                    resource_paths=resource_paths,
                    guest_working_directory=Path("/src/repository"),
                    pi_extensions=extensions,
                )

            self.assertIn("PI_MODEL_FILE=/home/codex/.pi/agent/runtime-model.json", command)
            self.assertIn(
                "CARGO_TARGET_DIR=/src/repository/work/cargo-target", command)
            self.assertIn("MYPY_CACHE_DIR=/src/repository/work/cache/mypy", command)
            self.assertIn(
                "PYTHONPYCACHEPREFIX=/src/repository/work/cache/python-bytecode", command)
            self.assertIn("RUFF_CACHE_DIR=/src/repository/work/cache/ruff", command)
            self.assertIn("BUN_INSTALL_CACHE_DIR=/home/codex/.cache/bun", command)
            self.assertIn("GOCACHE=/home/codex/.cache/go-build", command)
            self.assertIn("GOMODCACHE=/home/codex/.cache/go-mod", command)
            self.assertIn("npm_config_cache=/home/codex/.cache/npm", command)
            self.assertIn("PIP_CACHE_DIR=/home/codex/.cache/pip", command)
            self.assertIn("UV_CACHE_DIR=/home/codex/.cache/uv", command)
            self.assertIn("XDG_CACHE_HOME=/home/codex/.cache", command)
            self.assertIn(
                "CODEX_SANDBOX_TOOL_READY=/home/codex/.pi/agent/tool-worker-ready", command)
            session = next(item for item in command if item.startswith("PI_MODEL_SESSION_ID="))
            uuid.UUID(session.removeprefix("PI_MODEL_SESSION_ID="))
            self.assertIn(
                f"type=bind,src={root / 'installed-config'},dst=/home/codex/.gitignore,readonly",
                command,
            )
            self.assertIn(
                f"type=bind,src={state.pi_agent_tmp},dst=/home/codex/.pi/agent",
                command,
            )
            self.assertIn(
                "type=volume,src=codex-user-cache-v1,dst=/home/codex/.cache",
                command,
            )
            session_mounts = [
                item for item in command
                if "dst=/home/codex/.pi/agent/sessions" in item
            ]
            self.assertEqual(
                [f"type=bind,src={state.home / '.pi/agent/sessions'},"
                 "dst=/home/codex/.pi/agent/sessions,readonly"],
                session_mounts,
            )
            self.assertEqual(
                [f"type=bind,src={state.home / '.pi/agent/pi-codex-subagents/runs'},"
                 "dst=/home/codex/.pi/agent/pi-codex-subagents/runs,readonly"],
                [item for item in command
                 if "dst=/home/codex/.pi/agent/pi-codex-subagents/runs" in item],
            )
            host_skills = state.home / ".agents/skills"
            self.assertIn(
                f"type=bind,src={state.skills_source},dst={resource_paths[str(host_skills)]}",
                command,
            )
            self.assertNotIn(
                f"type=bind,src={state.skills_source},dst={host_skills}",
                command,
            )
            for role, (source, _) in launcher["STAGED_CONFIG"].items():
                host_path = state.home / source.removeprefix("$HOME/")
                self.assertIn(
                    f"type=bind,src={root / 'config'},"
                    f"dst={resource_paths[str(host_path)]},readonly",
                    command,
                )
            for relative in launcher["PI_RESOURCE_PATHS"]:
                source = state.host_pi_package / relative
                self.assertIn(
                    f"type=bind,src={source},dst={resource_paths[str(source)]},readonly",
                    command,
                )
            self.assertIn(
                f"type=bind,src={state.repository},dst={resource_paths[str(state.repository)]},"
                "bind-nonrecursive",
                command,
            )
            self.assertIn(
                f"type=bind,src={state.repository / '.jj'},"
                f"dst={Path(resource_paths[str(state.repository)]) / '.jj'},readonly",
                command,
            )
            self.assertIn(
                f"type=bind,src={dotfiles},dst=/src/shared-dotfiles,bind-nonrecursive", command,
            )
            self.assertIn(
                f"type=bind,src={dotfiles / '.jj'},dst=/src/shared-dotfiles/.jj,readonly", command,
            )
            self.assertIn(
                f"type=bind,src={dotfiles / '.agents/sandbox'},"
                "dst=/src/shared-dotfiles/.agents/sandbox,readonly", command,
            )
            launcher["check_mount_destinations"](command)
            self.assertEqual("/src/repository", command[command.index("--workdir") + 1])


if __name__ == "__main__":
    unittest.main()
