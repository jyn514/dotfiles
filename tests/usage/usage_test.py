import importlib.machinery
import importlib.util
import io
from pathlib import Path
import sys
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "bin/usage"
LOADER = importlib.machinery.SourceFileLoader("usage_command", str(MODULE_PATH))
SPEC = importlib.util.spec_from_loader(LOADER.name, LOADER)
assert SPEC
usage = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = usage
LOADER.exec_module(usage)


class UsageTests(unittest.TestCase):
    def test_passes_raw_du_output_to_sort_with_explicit_arguments(self):
        output = b"4.0K\tname with spaces\n1.0M\tinvalid-\xff\n"
        calls = []

        def runner(arguments, **kwargs):
            calls.append((arguments, kwargs))
            if arguments[0] == "du":
                return usage.Result(0, output)
            return usage.Result(0)

        self.assertEqual(usage.show_usage("-leading", runner), 0)
        self.assertEqual(
            calls,
            [
                (
                    ["du", "-h", "-x", "-d", "1", "--", "-leading"],
                    {"capture_output": True, "discard_stderr": True},
                ),
                (
                    ["sort", "-h", "-r"],
                    {"input_bytes": output, "capture_output": False},
                ),
            ],
        )

    def test_du_failure_stops_before_sort_and_preserves_status(self):
        runner = mock.Mock(return_value=usage.Result(27, b"partial output"))

        self.assertEqual(usage.show_usage("directory", runner), 27)
        runner.assert_called_once_with(
            ["du", "-h", "-x", "-d", "1", "--", "directory"],
            capture_output=True,
            discard_stderr=True,
        )

    def test_sort_failure_is_returned(self):
        runner = mock.Mock(side_effect=[usage.Result(0, b"sizes"), usage.Result(18)])

        self.assertEqual(usage.show_usage("directory", runner), 18)

    def test_missing_program_returns_shell_compatible_status(self):
        with mock.patch.object(
            usage.subprocess,
            "run",
            side_effect=FileNotFoundError("missing"),
        ), mock.patch("sys.stderr", new_callable=io.StringIO) as stderr:
            result = usage.run(["missing"])

        self.assertEqual(result.status, 127)
        self.assertIn("could not execute 'missing'", stderr.getvalue())

    def test_usage_message_remains_on_standard_output(self):
        with mock.patch("sys.stdout", new_callable=io.StringIO) as stdout:
            self.assertEqual(usage.main([]), 1)
        self.assertEqual(stdout.getvalue(), "usage: usage <path>\n")


if __name__ == "__main__":
    unittest.main()
