import json
import os
from pathlib import Path
import signal
import shutil
import subprocess
import sys
import tempfile
import tomllib
import unittest


ROOT = Path(__file__).resolve().parents[2]


class CommandIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)

    def executable(self, name: str, contents: str) -> None:
        path = self.directory / name
        path.write_text("#!/bin/sh\n" + contents)
        path.chmod(0o755)

    def test_claude_statusline_rejects_invalid_workspace(self) -> None:
        result = subprocess.run(
            [str(ROOT / "config/claude-statusline.sh")],
            text=True,
            input='{"cwd":"/directory/that/does/not/exist"}',
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        self.assertEqual(1, result.returncode)
        self.assertEqual("", result.stdout)
    def test_claude_statusline_rejects_malformed_json(self) -> None:
        result = subprocess.run(
            [str(ROOT / "config/claude-statusline.sh")],
            text=True,
            input="not json",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        self.assertNotEqual(0, result.returncode)
        self.assertEqual("", result.stdout)
    def test_claude_statusline_uses_resolved_renderer_not_path(self) -> None:
        marker = self.directory / "path-renderer-called"
        self.executable("prompt-command", f'touch "{marker}"\nexit 99\n')
        workspace = self.directory / "workspace"
        workspace.mkdir()
        installed = self.directory / "statusline-command.sh"
        installed.symlink_to(ROOT / "config/claude-statusline.sh")

        result = subprocess.run(
            [str(installed)],
            text=True,
            input=(
                '{"workspace":{"current_dir":'
                + json.dumps(str(workspace))
                + '},"model":{"display_name":"tea"},'
                '"context_window":{"used_percentage":42.4}}'
            ),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=os.environ
            | {
                "HOME": str(self.directory),
                "PATH": f"{self.directory}:{os.environ['PATH']}",
                "container": "fixture",
            },
        )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertTrue(result.stdout.startswith(" ctx:42% (tea@fixture"), result.stdout)
        self.assertTrue(result.stdout.endswith(") ~/workspace"), result.stdout)
        self.assertFalse(marker.exists())
    def test_claude_statusline_rejects_invalid_model_without_partial_output(self) -> None:
        result = subprocess.run(
            [str(ROOT / "config/claude-statusline.sh")],
            text=True,
            input='{"model":{"display_name":42}}',
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        self.assertNotEqual(0, result.returncode)
        self.assertEqual("", result.stdout)
        self.assertIn("model name must be a string", result.stderr)
    def test_claude_statusline_contains_no_json_or_shell_filters(self) -> None:
        launcher = (ROOT / "config/claude-statusline.sh").read_text()

        self.assertIn('os.execv(command, [str(command), "claude"])', launcher)
        for old_filter in ("jq -r", "head -n", "tr -d", "input=$(cat)", "command -v"):
            self.assertNotIn(old_filter, launcher)


if __name__ == "__main__":
    unittest.main()
