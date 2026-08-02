from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "main.py"
SPEC = importlib.util.spec_from_file_location("shell_boundaries", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
shell_boundaries = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(shell_boundaries)


class ShellBoundaryTests(unittest.TestCase):
    def scan(self, contents: str) -> list[str]:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "script.sh"
            path.write_text(contents)
            original_root = shell_boundaries.ROOT
            shell_boundaries.ROOT = Path(directory)
            try:
                return shell_boundaries.violations(path)
            finally:
                shell_boundaries.ROOT = original_root

    def test_flags_complex_shell_boundaries(self) -> None:
        cases = {
            'value=$(dirname "$(readlink "$file")")\n': "nested-substitution",
            "files=$(git diff --name-only HEAD | sort)\n": "filename-lines",
            "value=$(producer | consumer)\n": "unchecked-pipeline",
            "generate > ~/.cache/tool/output\n": "persistent-write",
        }
        for source, rule in cases.items():
            with self.subTest(rule=rule):
                self.assertTrue(any(f": {rule}:" in item for item in self.scan(source)))

    def test_allows_a_documented_exception_beside_the_command(self) -> None:
        source = (
            "# langsec: allow nested-substitution -- resolves this sourced file's repository root\n"
            'root=$(dirname "$(readlink "$file")")\n'
        )
        self.assertEqual([], self.scan(source))

    def test_reason_is_required_and_applies_only_to_the_next_command(self) -> None:
        no_reason = "# langsec: allow nested-substitution\nroot=$(dirname \"$(readlink x)\")\n"
        repeated = (
            "# langsec: allow nested-substitution -- required caller mutation\n"
            'one=$(dirname "$(readlink x)")\n'
            'two=$(dirname "$(readlink y)")\n'
        )
        self.assertEqual(1, len(self.scan(no_reason)))
        self.assertEqual(1, len(self.scan(repeated)))

    def test_ignores_direct_argv_and_checked_producers(self) -> None:
        source = (
            'python3 command.py -- "$path"\n'
            "value=$(producer | consumer) || exit\n"
            "temporary=$(mktemp cache.XXXXXX) || exit\n"
        )
        self.assertEqual([], self.scan(source))

    def test_exact_fingerprint_baseline_does_not_hide_a_modified_line(self) -> None:
        source = 'root=$(dirname "$(readlink x)")\n'
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "script.sh"
            path.write_text(source)
            original_root = shell_boundaries.ROOT
            shell_boundaries.ROOT = Path(directory)
            try:
                key, _, _ = shell_boundaries.findings(path)[0]
                self.assertEqual([], shell_boundaries.violations(path, {key}))
                path.write_text('root=$(dirname "$(readlink y)")\n')
                self.assertEqual(1, len(shell_boundaries.violations(path, {key})))
            finally:
                shell_boundaries.ROOT = original_root


if __name__ == "__main__":
    unittest.main()
