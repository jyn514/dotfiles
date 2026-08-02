import importlib.machinery
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "bin/b"
LOADER = importlib.machinery.SourceFileLoader("b_command", str(MODULE_PATH))
SPEC = importlib.util.spec_from_loader(LOADER.name, LOADER)
assert SPEC
b_command = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = b_command
LOADER.exec_module(b_command)


class BaconLauncherTests(unittest.TestCase):
    def test_parses_workspace_and_launches_with_explicit_cwd_and_arguments(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary) / "workspace with spaces"
            workspace.mkdir()
            metadata = json.dumps({"workspace_root": str(workspace)}).encode()
            runner = mock.Mock(
                side_effect=[b_command.Result(0, metadata), b_command.Result(19)]
            )

            self.assertEqual(
                b_command.launch(["--job", "check all"], runner),
                19,
            )

        self.assertEqual(
            runner.call_args_list,
            [
                mock.call(
                    ["cargo", "metadata", "--format-version", "1"],
                    capture_output=True,
                ),
                mock.call(["bacon", "--job", "check all"], cwd=workspace),
            ],
        )

    def test_cargo_failure_discards_partial_output_and_does_not_launch(self):
        runner = mock.Mock(return_value=b_command.Result(23, b'{"workspace_root":'))

        self.assertEqual(b_command.launch([], runner), 23)
        runner.assert_called_once_with(
            ["cargo", "metadata", "--format-version", "1"], capture_output=True
        )

    def test_rejects_malformed_or_wrong_shape_metadata(self):
        cases = [b"not json", b"[]", b"{}", b'{"workspace_root":null}']
        for metadata in cases:
            with self.subTest(metadata=metadata), self.assertRaises(ValueError):
                b_command.workspace_root(metadata)

    def test_missing_workspace_stops_before_bacon(self):
        runner = mock.Mock(
            return_value=b_command.Result(0, b'{"workspace_root":"/missing/workspace"}')
        )
        with mock.patch("sys.stderr", new_callable=io.StringIO) as stderr:
            self.assertEqual(b_command.launch([], runner), 1)

        self.assertIn("workspace does not exist", stderr.getvalue())
        runner.assert_called_once()

    def test_missing_program_returns_shell_compatible_status(self):
        with mock.patch.object(
            b_command.subprocess,
            "run",
            side_effect=FileNotFoundError("missing"),
        ), mock.patch("sys.stderr", new_callable=io.StringIO) as stderr:
            result = b_command.run(["cargo"])

        self.assertEqual(result.status, 127)
        self.assertIn("could not execute 'cargo'", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
