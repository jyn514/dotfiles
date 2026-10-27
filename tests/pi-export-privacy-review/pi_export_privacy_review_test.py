import base64
import json
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).parents[2]
AUDIT = ROOT / "skills" / "pi-export-privacy-review" / "scripts" / "audit.mjs"


class PiExportPrivacyReviewTest(unittest.TestCase):
    def run_audit(self, path: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["node", str(AUDIT), str(path)],
            check=False,
            capture_output=True,
            text=True,
        )

    def test_html_inventory_masks_values_and_accounts_for_imported_session(self) -> None:
        secret = "sk-proj-examplevalue12345678901234567890"
        session_id = "01a1562d-d682-7536-87dc-1776d0e5c5ff"
        data = {
            "header": {"cwd": "/home/person/private-project"},
            "systemPrompt": "private internal instructions",
            "tools": [{"name": "read_session"}],
            "entries": [
                {
                    "type": "message",
                    "message": {
                        "role": "assistant",
                        "content": [
                            {
                                "type": "toolCall",
                                "id": "call-1",
                                "name": "read_session",
                                "arguments": {"sessionId": session_id},
                            }
                        ],
                    },
                },
                {
                    "type": "message",
                    "message": {
                        "role": "toolResult",
                        "toolCallId": "call-1",
                        "content": [{"type": "text", "text": f"session {session_id}"}],
                    },
                },
                {
                    "type": "message",
                    "message": {
                        "role": "assistant",
                        "content": [
                            {"type": "thinking", "thinkingSignature": secret},
                            {"type": "text", "text": "contact private.person@example.test"},
                        ],
                    },
                },
            ],
        }
        encoded = base64.b64encode(json.dumps(data).encode()).decode()
        html = (
            "<!doctype html>\n"
            '<script id="session-data" type="application/json">'
            f"{encoded}</script>\n"
        )

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "session.html"
            path.write_text(html)
            result = self.run_audit(path)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn(secret, result.stdout)
        self.assertNotIn("private.person@example.test", result.stdout)
        report = json.loads(result.stdout)
        self.assertEqual(report["input"]["payloadLine"], 2)
        self.assertEqual(report["entries"]["imports"][0]["requestedSession"], session_id)
        self.assertEqual(report["candidates"]["secrets"]["total"], 1)
        self.assertEqual(
            report["candidates"]["personalData"]["emails"]["items"][0]["masked"],
            "pr…@example.test",
        )
        self.assertEqual(report["signatures"]["count"], 1)

    def test_jsonl_parses_every_non_empty_record(self) -> None:
        records = [
            {"type": "session", "id": "session-id", "cwd": "/home/person/project"},
            {"type": "message", "message": {"role": "user", "content": []}},
            {"type": "custom_message", "content": "visible"},
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "session.jsonl"
            path.write_text("\n".join(json.dumps(record) for record in records) + "\n\n")
            result = self.run_audit(path)

        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["input"]["records"], 3)
        self.assertEqual(report["entries"]["entries"], 3)
        self.assertEqual(report["header"]["id"], "session-id")

    def test_invalid_jsonl_identifies_the_unparsed_line(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "session.jsonl"
            path.write_text('{}\n{"broken":\n')
            result = self.run_audit(path)

        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "")
        self.assertIn("invalid JSONL record at line 2", result.stderr)


if __name__ == "__main__":
    unittest.main()
