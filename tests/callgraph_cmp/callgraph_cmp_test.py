import importlib.machinery
import importlib.util
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "bin/callgraph-cmp"
LOADER = importlib.machinery.SourceFileLoader("callgraph_cmp", str(MODULE_PATH))
SPEC = importlib.util.spec_from_loader(LOADER.name, LOADER)
assert SPEC
callgraph_cmp = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = callgraph_cmp
LOADER.exec_module(callgraph_cmp)


class CallgraphComparisonTests(unittest.TestCase):
    def test_extracts_unique_sorted_edges_as_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            graph = Path(temporary) / "graph.dot"
            graph.write_bytes(
                b'digraph {\n"z" -> "a" [label="ignored"];\n'
                b'"\xff" -> "b"; "z" -> "a";\n}\n'
            )

            self.assertEqual(
                callgraph_cmp.edge_bytes(graph),
                b'"z" -> "a"\n"\xff" -> "b"',
            )

    def test_stages_both_edge_sets_and_returns_diff_status(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            left = directory / "left.dot"
            right = directory / "right.dot"
            left.write_text('"b" -> "c";\n"a" -> "b";\n')
            right.write_text('digraph {}\n')
            calls = []

            def runner(arguments):
                calls.append(arguments)
                self.assertEqual(Path(arguments[-2]).read_bytes(), b'"a" -> "b"\n"b" -> "c"')
                self.assertEqual(Path(arguments[-1]).read_bytes(), b"")
                return 1

            self.assertEqual(callgraph_cmp.compare(left, right, runner), 1)

        self.assertEqual(calls[0][:3], ["diff", "--color=always", "--"])
        self.assertFalse(Path(calls[0][-2]).exists())

    def test_read_failure_does_not_invoke_diff(self):
        runner = mock.Mock()
        with tempfile.TemporaryDirectory() as temporary, mock.patch(
            "sys.stderr", new_callable=io.StringIO
        ) as stderr:
            missing = Path(temporary) / "missing.dot"
            status = callgraph_cmp.compare(missing, missing, runner)

        self.assertEqual(status, 1)
        self.assertIn("could not read graph", stderr.getvalue())
        runner.assert_not_called()

    def test_missing_diff_returns_shell_compatible_status(self):
        with mock.patch.object(
            callgraph_cmp.subprocess,
            "run",
            side_effect=FileNotFoundError("missing"),
        ), mock.patch("sys.stderr", new_callable=io.StringIO) as stderr:
            status = callgraph_cmp.run_diff(["diff"])

        self.assertEqual(status, 127)
        self.assertIn("could not execute 'diff'", stderr.getvalue())

    def test_usage_matches_existing_interface(self):
        with mock.patch("sys.stderr", new_callable=io.StringIO) as stderr:
            self.assertEqual(callgraph_cmp.main(["one"]), 1)
        self.assertEqual(stderr.getvalue(), "usage: callgraph-cmp <dot1> <dot2>\n")


if __name__ == "__main__":
    unittest.main()
