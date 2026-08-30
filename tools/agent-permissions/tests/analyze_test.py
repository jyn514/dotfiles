import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools/agent-permissions"))

import analyze  # noqa: E402


class AgentPermissionAnalyzerTests(unittest.TestCase):
    def test_loads_only_bash_rules_with_exact_wildcard_semantics(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            settings = Path(temporary) / "settings.json"
            settings.write_text(json.dumps({"permissions": {"allow": [
                "Read", "Bash(git diff *)", "Bash(jj status)",
            ]}}))
            rules = analyze.load_bash_rules(settings)

        self.assertEqual(2, len(rules))
        self.assertTrue(rules[0][1].fullmatch("git diff --stat"))
        self.assertFalse(rules[0][1].fullmatch("git status"))
        self.assertTrue(rules[0][2])
        self.assertFalse(rules[1][2])

    def test_reads_only_bash_tool_calls_from_jsonl_logs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            log = Path(temporary) / "session.jsonl"
            log.write_text("\n".join((
                "not json",
                json.dumps({"message": {"content": [
                    {"type": "tool_use", "name": "Read", "input": {"command": "ignored"}},
                    {"type": "tool_use", "name": "Bash", "input": {"command": "  git status  "}},
                ]}}),
            )))
            commands = list(analyze.iter_bash_commands(temporary))

        self.assertEqual(["git status"], commands)

    def test_signature_discards_environment_assignments(self) -> None:
        self.assertEqual("git diff", analyze.signature("PAGER=cat git diff --stat"))
        self.assertEqual("python3", analyze.signature("python3 ./script.py"))
        self.assertIsNone(analyze.signature("ONLY=value"))

    def test_antipattern_mode_does_not_require_settings_file(self) -> None:
        with mock.patch.object(analyze, "iter_bash_commands", return_value=iter(["cd src"])), \
                mock.patch("sys.stdout", new_callable=io.StringIO) as stdout:
            status = analyze.main(["--antipatterns", "/missing/project"])

        self.assertIsNone(status)
        self.assertIn("leading `cd`", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
