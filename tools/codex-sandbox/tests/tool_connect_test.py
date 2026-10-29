"""Attachment command execution and live-source migration, without a VM/service."""

import io
import json
import os
from pathlib import Path
import runpy
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

TOOL = Path(__file__).resolve().parents[1]
SOURCE = Path(os.environ.get("TEST_TOOL_CONNECT_SOURCE", TOOL / "sandbox-tool-connect"))
BOUND = TOOL / "sandbox-tool-connect-bound"


sys.path.insert(0, str(TOOL))


class ToolConnectTest(unittest.TestCase):
    def environment(self, **values):
        return {**{key: value for key, value in os.environ.items()
                   if not key.startswith("CODEX_SANDBOX_")}, **values}

    def test_new_source_preserves_old_launcher_environment(self):
        # Precisely the deployed boundary: an existing Pi has only its old
        # environment and opens the edited source again on its next tool call.
        admitted = mock.Mock()
        admitted.argv.return_value = ["selected-client", "exec-channel"]
        discover = mock.Mock(return_value=admitted)
        with mock.patch.dict(os.environ, self.environment(
                CODEX_SANDBOX_TOOL_CONTAINER="codex-sandbox-old-attachment"), clear=True), \
                mock.patch.dict(sys.modules, sandbox_runtime=SimpleNamespace(image_runtime=discover)), \
                mock.patch("os.execvp") as execute:
            self.assertEqual(1, runpy.run_path(str(SOURCE))["main"]())
        discover.assert_called_once_with()
        admitted.argv.assert_called_once_with([
            "exec", "--interactive", "codex-sandbox-old-attachment", "node",
            "/opt/agent-tools/bin/tool-connect.mjs",
        ])
        execute.assert_called_once_with("selected-client", ["selected-client", "exec-channel"])

    def test_legacy_invalid_container_does_not_start_a_channel(self):
        discover = mock.Mock()
        with mock.patch.dict(os.environ, self.environment(
                CODEX_SANDBOX_TOOL_CONTAINER="not-a-sandbox"), clear=True), \
                mock.patch.dict(sys.modules, sandbox_runtime=SimpleNamespace(image_runtime=discover)), \
                mock.patch("sys.stderr", new_callable=io.StringIO) as errors, \
                mock.patch("os.execvp") as execute:
            self.assertEqual(1, runpy.run_path(str(SOURCE))["main"]())
        discover.assert_not_called()
        execute.assert_not_called()
        self.assertIn("container is not selected", errors.getvalue())

    def test_bound_source_path_executes_without_runtime_discovery(self):
        result = subprocess.run([sys.executable, str(SOURCE)], input="channel-input\n",
            env=self.environment(CODEX_SANDBOX_RUNTIME="must-not-be-discovered",
                CODEX_SANDBOX_TOOL_COMMAND=json.dumps(["/bin/cat"])),
            text=True, capture_output=True, timeout=10)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("channel-input\n", result.stdout)

    def test_bound_connector_rejects_missing_and_malformed_command_without_legacy_fallback(self):
        for connector in (SOURCE, BOUND):
            for raw in ("", "not-json", "null", "{}", "[]", '["cat", 1]', '["cat", ""]', '["cat\\u0000"]'):
                with self.subTest(connector=connector.name, raw=raw):
                    result = subprocess.run([sys.executable, str(connector)],
                        env=self.environment(CODEX_SANDBOX_TOOL_COMMAND=raw,
                            CODEX_SANDBOX_TOOL_CONTAINER="codex-sandbox-old-attachment",
                            CODEX_SANDBOX_RUNTIME="must-not-be-discovered"),
                        text=True, capture_output=True, timeout=10)
                    self.assertEqual(1, result.returncode, result.stderr)
                    self.assertIn("attachment command is unavailable or invalid", result.stderr)
                    self.assertNotIn("Traceback", result.stderr)
        result = subprocess.run([sys.executable, str(BOUND)], env=self.environment(),
                                text=True, capture_output=True, timeout=10)
        self.assertEqual(1, result.returncode)
        self.assertIn("attachment command is unavailable", result.stderr)

    def test_staged_connector_survives_source_edits_and_new_launch_selects_new_code(self):
        stage = runpy.run_path(str(TOOL / "codex-sandbox"))["stage_tool_connector"]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source/tools/codex-sandbox/sandbox-tool-connect-bound"
            source.parent.mkdir(parents=True)
            shutil.copyfile(BOUND, source)
            scratch = root / "host-private-scratch"
            scratch.mkdir(mode=0o700)
            runtime = SimpleNamespace(argv=mock.Mock(return_value=["/bin/cat"]))
            state = SimpleNamespace(codex_container="codex-sandbox-first")
            later = SimpleNamespace(codex_container="codex-sandbox-later")
            with mock.patch.dict(stage.__globals__, DOTFILES=root / "source", OUTER_RUNTIME=runtime,
                                 scratch_directory=lambda: scratch):
                selected = stage(state)
                old_bytes = state.pi_tool_connector.read_bytes()
                source.write_text("raise SystemExit(23)\n")
                # The actual subprocess executes the producer's staged path and
                # fixed operation, not later source or runtime-selection variables.
                result = subprocess.run([sys.executable, selected["CODEX_SANDBOX_TOOL_CONNECT"]],
                    input="old attachment\n", env=self.environment(**selected,
                        CODEX_SANDBOX_RUNTIME="changed-runtime"), text=True, capture_output=True, timeout=10)
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertEqual("old attachment\n", result.stdout)
                self.assertEqual(old_bytes, state.pi_tool_connector.read_bytes())
                updated = stage(later)
                result = subprocess.run([sys.executable, updated["CODEX_SANDBOX_TOOL_CONNECT"]],
                    env=self.environment(**updated), text=True, capture_output=True, timeout=10)
                self.assertEqual(23, result.returncode)
            self.assertNotEqual(state.pi_tool_connector, later.pi_tool_connector)
            self.assertEqual(scratch, state.pi_tool_connector.parent)
            self.assertEqual(0o600, state.pi_tool_connector.stat().st_mode & 0o777)
            self.assertEqual([
                mock.call(["exec", "--interactive", container, "node", "/opt/agent-tools/bin/tool-connect.mjs"])
                for container in ("codex-sandbox-first", "codex-sandbox-later")
            ], runtime.argv.call_args_list)

    def test_bound_connector_preserves_child_failure(self):
        result = subprocess.run([sys.executable, str(BOUND)],
            env=self.environment(CODEX_SANDBOX_TOOL_COMMAND=json.dumps(["/bin/sh", "-c", "exit 17"])),
            text=True, capture_output=True, timeout=10)
        self.assertEqual(17, result.returncode)


if __name__ == "__main__":
    unittest.main()
