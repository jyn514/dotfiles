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
    def test_guest_command_contains_session_scoped_model_channel(self) -> None:
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
                pi_auth_mask=root / "auth.json",
                skills_source=root / "skills",
                skills_tmp=root / "staged",
                home=root / "home",
                container_repository=Path("/src/repository"),
                repository=root / "repository",
                git_mount_source=root / "repository/.git",
                container_working_directory=Path("/src/repository"),
            )
            state.pi_agent_tmp.mkdir()
            state.pi_auth_mask.touch()
            state.skills_source.mkdir()
            state.skills_tmp.mkdir()
            state.home.mkdir()
            state.repository.mkdir()
            (state.repository / ".jj").mkdir()
            state.git_mount_source.mkdir(parents=True)
            extensions = root / "pi-extensions"
            extensions.mkdir()

            with mock.patch.dict(build.__globals__, {
                "OUTER_RUNTIME": SimpleNamespace(nonrecursive_bind="bind-nonrecursive"),
                "proxy_flags": lambda: [],
                "staged_config_path": lambda _state, _role: root / "config",
                "installed_config_source": lambda _path: root / "installed-config",
                "source_mounts": lambda *_args: [],
                "check_mount_destinations": mock.Mock(),
            }):
                command = build(
                    state, ["image", "pi"], host_pi=False, timing=False,
                    protected=[state.repository / ".jj"], repository_aliases=[],
                    external_git_roots=[], persistent_package_directories=[],
                    sessions=root / "sessions", pi_extensions=extensions,
                )

            self.assertIn("PI_MODEL_FILE=/home/codex/.pi/agent/runtime-model.json", command)
            session = next(item for item in command if item.startswith("PI_MODEL_SESSION_ID="))
            uuid.UUID(session.removeprefix("PI_MODEL_SESSION_ID="))
            self.assertIn(
                f"type=bind,src={state.pi_agent_tmp},dst=/home/codex/.pi/agent",
                command,
            )


if __name__ == "__main__":
    unittest.main()
