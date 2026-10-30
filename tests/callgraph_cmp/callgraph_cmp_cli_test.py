import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
FIXTURES = Path(__file__).resolve().parent / "fixtures"


class CommandIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)

    def executable(self, name: str, contents: str) -> None:
        path = self.directory / name
        path.write_text("#!/bin/sh\n" + contents)
        path.chmod(0o755)

    def compare(self, left: str, right: str, *, path: str | None = None):
        return subprocess.run(
            [str(ROOT / "bin/callgraph-cmp"), left, right],
            cwd=self.directory,
            env=os.environ | {"PATH": path or f"{self.directory}:{os.environ['PATH']}"},
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

    def mark_diff(self) -> Path:
        marker = self.directory / "diff-called"
        self.executable("diff", f"printf called > '{marker}'\n")
        return marker

    def test_callgraph_comparison_stops_before_diff_on_read_failure(self) -> None:
        marker = self.mark_diff()
        result = self.compare("missing.dot", "second.dot")

        self.assertEqual(1, result.returncode)
        self.assertFalse(marker.exists())

    @unittest.skipUnless(shutil.which("gvpr"), "Graphviz gvpr is unavailable")
    def test_callgraph_comparison_accepts_graphs_without_edges(self) -> None:
        (self.directory / "first.dot").write_text("digraph { isolated; }\n")
        (self.directory / "second.dot").write_text("digraph {}\n")

        result = self.compare("first.dot", "second.dot")

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("", result.stdout)

    @unittest.skipUnless(shutil.which("gvpr"), "Graphviz gvpr is unavailable")
    def test_native_producer_edges_are_different(self) -> None:
        result = self.compare(str(FIXTURES / "alpha.dot"), str(FIXTURES / "beta.dot"))

        self.assertEqual(1, result.returncode, result.stderr)
        self.assertIn('["main", "alpha"]', result.stdout)
        self.assertIn('["main", "beta"]', result.stdout)

    @unittest.skipUnless(shutil.which("gvpr"), "Graphviz gvpr is unavailable")
    def test_ignores_spelling_attributes_and_duplicate_edges_but_not_direction(self):
        left = self.directory / "first.dot"
        right = self.directory / "second.dot"
        left.write_text('digraph { "main" -> "alpha" [label="90%"]; main -> alpha; }')
        right.write_text('digraph { main -> alpha [label="10%"]; }')
        equal = self.compare(str(left), str(right))
        self.assertEqual(equal.returncode, 0, equal.stderr)
        self.assertEqual(equal.stdout, "")

        right.write_text('digraph { alpha -> main; }')
        reversed_edges = self.compare(str(left), str(right))
        self.assertEqual(reversed_edges.returncode, 1, reversed_edges.stderr)
        self.assertIn('["main", "alpha"]', reversed_edges.stdout)
        self.assertIn('["alpha", "main"]', reversed_edges.stdout)

    @unittest.skipUnless(shutil.which("gvpr"), "Graphviz gvpr is unavailable")
    def test_invalid_or_unsupported_dot_does_not_become_equality(self):
        marker = self.mark_diff()
        left = self.directory / "first.dot"
        right = self.directory / "second.dot"
        right.write_text('digraph {}')
        for invalid in (
            'digraph { main -> }',
            'graph { main -- alpha; }',
            '',
            'digraph { main -> alpha; } garbage',
            'digraph {} digraph {}',
        ):
            with self.subTest(graph=invalid):
                left.write_text(invalid)
                result = self.compare(str(left), str(right))
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, "")
                self.assertTrue(result.stderr)
                self.assertFalse(marker.exists())

    def test_failed_or_malformed_parser_output_does_not_invoke_diff(self):
        marker = self.mark_diff()
        (self.directory / "first.dot").write_text('digraph {}')
        (self.directory / "second.dot").write_text('digraph {}')
        for program, status in (
            ('printf "main\\000alpha\\000"; exit 24\n', 24),
            ('printf "main\\000alpha"\n', 1),
            ('printf "main\\000"\n', 1),
            ('printf "parser diagnostic\\n" >&2\n', 1),
        ):
            with self.subTest(program=program):
                self.executable("gvpr", program)
                result = self.compare("first.dot", "second.dot")
                self.assertEqual(result.returncode, status)
                self.assertEqual(result.stdout, "")
                self.assertTrue(result.stderr)
                self.assertFalse(marker.exists())

    def test_missing_parser_does_not_become_equality(self):
        marker = self.mark_diff()
        (self.directory / "first.dot").write_text('digraph {}')
        (self.directory / "second.dot").write_text('digraph {}')
        (self.directory / "python3").symlink_to(sys.executable)

        result = self.compare("first.dot", "second.dot", path=str(self.directory))

        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "")
        self.assertIn("gvpr", result.stderr)
        self.assertFalse(marker.exists())


if __name__ == "__main__":
    unittest.main()
