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
            paths = launcher["host_pi_resource_paths"](state)

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
                "/home/codex/.pi/agent/AGENTS.md",
                paths[str(state.home / ".pi/agent/AGENTS.md")],
            )
            self.assertEqual(
                "/home/codex/.pi/agent/sessions",
                paths[str(state.home / ".pi/agent/sessions")],
            )
            for source, destination in launcher["STAGED_CONFIG"].values():
                host_path = state.home / source.removeprefix("$HOME/")
                self.assertEqual(destination, paths[str(host_path)])

    def test_host_worker_command_uses_resource_paths_and_session_channel(self) -> None:
        launcher = runpy.run_path(str(LAUNCHER))
        build = launcher["build_agent_command"]
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
                git_mount_source=root / "repository/.git",
            )
            state.pi_agent_tmp.mkdir()
            state.skills_source.mkdir()
            state.skills_tmp.mkdir()
            state.home.mkdir()
            (state.host_pi_package / "README.md").parent.mkdir(parents=True)
            for relative in ("README.md", "docs", "examples"):
                path = state.host_pi_package / relative
                path.mkdir() if "." not in path.name else path.touch()
            state.repository.mkdir()
            (state.repository / ".jj").mkdir()
            state.git_mount_source.mkdir(parents=True)
            extensions = root / "pi-extensions"
            extensions.mkdir()

            resource_paths = launcher["host_pi_resource_paths"](state)
            with mock.patch.dict(build.__globals__, {
                "OUTER_RUNTIME": SimpleNamespace(nonrecursive_bind="bind-nonrecursive"),
                "proxy_flags": lambda: [],
                "staged_config_path": lambda _state, _role: root / "config",
                "installed_config_source": lambda _path: root / "installed-config",
                "source_mounts": lambda *_args: [],
                "check_mount_destinations": mock.Mock(),
            }):
                command = build(
                    state, ["image", "pi"], timing=False,
                    resource_paths=resource_paths,
                    guest_working_directory=Path("/src/repository"),
                    protected=[state.repository / ".jj"], repository_aliases=[],
                    external_git_roots=[], pi_extensions=extensions,
                )

            self.assertIn("PI_MODEL_FILE=/home/codex/.pi/agent/runtime-model.json", command)
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
            session_mounts = [
                item for item in command
                if "dst=/home/codex/.pi/agent/sessions" in item
            ]
            self.assertEqual(
                [f"type=bind,src={state.home / '.pi/agent/sessions'},"
                 "dst=/home/codex/.pi/agent/sessions,readonly"],
                session_mounts,
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
            self.assertEqual("/src/repository", command[command.index("--workdir") + 1])


if __name__ == "__main__":
    unittest.main()
