"""Both transcript consumers must use the same bounded Codex history."""

import contextlib
import io
import json
import os
from pathlib import Path
import re
import runpy
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
EXTRACT = ROOT / "bin/extract-chat"
CONVERT = ROOT / "bin/codex-to-pi"
PARENT = "019abcde-1234-7000-8000-000000000001"
PARENT_ROLLOUT = "019abcde-1234-7000-8000-000000000002"
CHILD = "019abcde-1234-7000-8000-000000000003"
CHILD_ROLLOUT = "019abcde-1234-7000-8000-000000000004"
STAMP = "2026-10-14T15:57:28.000Z"
SKILL = "<skill>\n<name>example</name>\n<path>/skills/example/SKILL.md</path>\nInstructions.\n</skill>"


class SharedChatHistoryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="chat history ")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.home = self.root / "codex home"
        self.environment = dict(os.environ, CODEX_HOME=str(self.home), PYTHONDONTWRITEBYTECODE="1")
        self.output = self.root / "pi transcript.jsonl"

    def write_rollout(self, name, thread, texts, base=None, archived=False):
        directory = self.home / ("archived_sessions" if archived else "sessions") / "2026/10/14"
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / name
        start = base["end_ordinal_exclusive"] if base else 0
        meta = {"id": thread, "session_id": thread, "history_mode": "paginated",
                "cwd": "/Users/jyn/src/example", "model": "test-model"}
        if base:
            meta["history_base"] = base
        events = [{"type": "session_meta", "ordinal": start, "payload": meta}]
        for index, text in enumerate(texts, start + 1):
            events.append({"type": "response_item", "ordinal": index, "timestamp": STAMP,
                           "payload": {"type": "message", "role": "user",
                                       "content": [{"type": "input_text", "text": text}]}})
        path.write_text("".join(json.dumps(e, ensure_ascii=False) + "\n" for e in events))
        return path

    def position(self, path, rollout, count, ordinal):
        return {"thread_id": rollout, "end_ordinal_exclusive": ordinal,
                "end_byte_offset": sum(map(len, path.read_bytes().splitlines(keepends=True)[:count]))}

    def lineage(self):
        parent = self.write_rollout(f"rollout-2026-10-14T16-00-00-{PARENT}.jsonl",
                                    PARENT, ["café", "discarded parent"], archived=True)
        parent_revert = self.write_rollout(
            f"rollout-2026-10-14T16-30-00-{PARENT}_{PARENT_ROLLOUT}.jsonl", PARENT,
            ["parent continuation", "after fork"], self.position(parent, PARENT, 2, 2), archived=True)
        child = self.write_rollout(f"rollout-2026-10-14T17-00-00-{CHILD}.jsonl", CHILD,
                                   ["discarded child"], self.position(parent_revert, PARENT_ROLLOUT, 2, 4))
        latest = self.write_rollout(f"rollout-2026-10-14T18-00-00-{CHILD}_{CHILD_ROLLOUT}.jsonl",
                                    CHILD, ["current child"], self.position(child, CHILD, 1, 5))
        return parent, latest

    def run_command(self, command, *args, cwd=ROOT):
        return subprocess.run([str(command), *map(str, args)], env=self.environment,
                              cwd=cwd, capture_output=True, text=True)

    def converted_messages(self):
        events = [json.loads(line) for line in self.output.read_text().splitlines()]
        self.assertEqual("session", events[0]["type"])
        self.assertEqual(3, events[0]["version"])
        self.assertEqual(CHILD, events[0]["id"])
        parent = None
        for event in events[1:]:
            self.assertEqual(parent, event["parentId"])
            self.assertEqual(STAMP, event["timestamp"])
            self.assertEqual(1791993448000, event["message"]["timestamp"])
            parent = event["id"]
        return [event["message"]["content"] for event in events[1:]]

    def assert_consumers(self, selector, expected, *flags, cwd=ROOT):
        extracted = self.run_command(EXTRACT, *flags, "--session", selector, cwd=cwd)
        self.assertEqual(0, extracted.returncode, extracted.stderr)
        self.assertEqual(expected, re.findall(r"^## User\n\n(.*?)\n\n(?=## |\Z)",
                                            extracted.stdout, re.MULTILINE | re.DOTALL))
        converted = self.run_command(CONVERT, selector, *flags, "-o", self.output, cwd=cwd)
        self.assertEqual(0, converted.returncode, converted.stderr)
        self.assertEqual(expected, self.converted_messages())

    def test_both_consumers_follow_parent_edits_and_revert_cutoffs(self):
        parent, _ = self.lineage()
        self.assert_consumers(CHILD, ["café", "parent continuation", "current child"])
        # A source change at the shared boundary must reach both consumers.
        content = parent.read_bytes().replace("café".encode(), "thé!".encode())
        parent.write_bytes(content)
        self.assert_consumers(CHILD, ["thé!", "parent continuation", "current child"])

    def test_archived_lookup_and_explicit_files_from_unrelated_directory(self):
        _, latest = self.lineage()
        for path in (self.home / "sessions/2026/10/14").glob("*.jsonl"):
            path.rename(self.home / "archived_sessions/2026/10/14" / path.name)
        self.assert_consumers(CHILD, ["café", "parent continuation", "current child"],
                              "--archived", cwd=self.root)
        latest = self.home / "archived_sessions/2026/10/14" / latest.name
        result = self.run_command(CONVERT, latest, "--normalize", "-o", self.output, cwd=self.root)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(["café", "parent continuation", "current child"], self.converted_messages())
        self.assertEqual("/src/example", json.loads(self.output.read_text().splitlines()[0])["cwd"])

    def test_history_failure_does_not_replace_existing_pi_output(self):
        _, latest = self.lineage()
        events = [json.loads(line) for line in latest.read_text().splitlines()]
        for position in ({"thread_id": "missing", "end_byte_offset": 1, "end_ordinal_exclusive": 1},
                         {"thread_id": CHILD, "end_byte_offset": 9999999, "end_ordinal_exclusive": 5}):
            with self.subTest(position=position):
                events[0]["payload"]["history_base"] = position
                latest.write_text("".join(json.dumps(e) + "\n" for e in events))
                self.output.write_text("preserve existing session\n")
                extracted = self.run_command(EXTRACT, "--session", CHILD)
                converted = self.run_command(CONVERT, CHILD, "-o", self.output)
                self.assertNotEqual(0, extracted.returncode)
                self.assertNotEqual(0, converted.returncode)
                self.assertEqual("", extracted.stdout)
                self.assertEqual("", converted.stdout)
                self.assertEqual("preserve existing session\n", self.output.read_text())

    def test_both_consumers_omit_skill_instructions_in_both_codex_message_formats(self):
        visible = ["$example", "explain SKILL.md", "what does <skill> mean?", "quoted example:\n" + SKILL]
        parent = self.write_rollout(f"rollout-2026-10-14T16-00-00-{PARENT}.jsonl",
                                    PARENT, [SKILL, *visible], archived=True)
        latest = self.write_rollout(f"rollout-2026-10-14T18-00-00-{CHILD}.jsonl", CHILD,
                                    [" \n" + SKILL + "\n ", "continue"],
                                    self.position(parent, PARENT, 6, 6))
        for format in ("response_item", "event_msg"):
            with self.subTest(format=format):
                if format == "event_msg":
                    for file in (parent, latest):
                        events = [json.loads(line) for line in file.read_text().splitlines()]
                        for event in events[1:]:
                            event["type"] = "event_msg"
                            event["payload"] = {"type": "user_message",
                                                "message": event["payload"]["content"][0]["text"]}
                        file.write_text("".join(json.dumps(e) + "\n" for e in events))
                    events = [json.loads(line) for line in latest.read_text().splitlines()]
                    events[0]["payload"]["history_base"] = self.position(parent, PARENT, 6, 6)
                    latest.write_text("".join(json.dumps(e) + "\n" for e in events))
                self.assert_consumers(CHILD, [*visible, "continue"])

    def test_skill_filter_preserves_assistant_messages_and_filters_pi_and_claude_users(self):
        for format in ("pi", "claude", "codex"):
            with self.subTest(format=format):
                file = self.root / f"{format}.jsonl"
                messages = []
                if format == "pi":
                    messages.append({"type": "session", "version": 3, "id": "pi"})
                for role, text in (("user", SKILL), ("user", "$example"), ("assistant", SKILL)):
                    message = {"role": role, "content": [{"type": "text", "text": text}]}
                    if format == "codex":
                        messages.append({"type": "response_item", "payload": {"type": "message", **message}})
                    else:
                        messages.append({"type": "message" if format == "pi" else role, "message": message})
                file.write_text("".join(json.dumps(e) + "\n" for e in messages))
                result = self.run_command(EXTRACT, file)
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertEqual(1, result.stdout.count("<skill>"))
                self.assertIn("## Assistant\n\n" + SKILL, result.stdout)
                self.assertIn("## User\n\n$example", result.stdout)
                if format == "codex":
                    result = self.run_command(CONVERT, file, "-o", self.output)
                    self.assertEqual(0, result.returncode, result.stderr)
                    output = [json.loads(line) for line in self.output.read_text().splitlines()]
                    self.assertEqual(3, len(output))
                    self.assertEqual("$example", output[1]["message"]["content"])
                    self.assertEqual([{"type": "text", "text": SKILL}], output[2]["message"]["content"])

    def test_packaged_extractor_finds_shared_reader_through_symlink(self):
        layout = self.root / "image"
        for relative in ("tools/extract-chat/extract-chat", "libexec/chat-history.clj"):
            target = layout / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(["cp", str(ROOT / relative), str(target)], check=True)
            subprocess.run(["cmp", str(ROOT / relative), str(target)], check=True)
        entrypoint = layout / "opt/agent-tools/bin/extract-chat"
        entrypoint.parent.mkdir(parents=True)
        entrypoint.symlink_to(layout / "tools/extract-chat/extract-chat")
        self.lineage()
        result = self.run_command(entrypoint, "--session", CHILD, cwd=self.root)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("## User\n\ncafé\n\n", result.stdout)
        self.assertIn("## User\n\ncurrent child\n\n", result.stdout)
        self.assertNotIn("discarded", result.stdout)

    def test_share_conversion_keeps_its_existing_message_policy(self):
        module = runpy.run_path(str(CONVERT))
        events = [{"type": "session_meta", "payload": {"session_id": CHILD, "cwd": str(self.root)}}]
        for role, text in (("user", "Make tea."), ("assistant", "Tea is ready.")):
            events.append({"type": "share_message", "role": role, "text": text, "timestamp": STAMP})
        main = module["main"]
        with patch.dict(main.__globals__, read_share=lambda url: events):
            with patch.object(sys, "argv", [str(CONVERT), "https://chatgpt.com/share/test", "-o", str(self.output)]):
                with contextlib.redirect_stdout(io.StringIO()):
                    main()
        output = [json.loads(line) for line in self.output.read_text().splitlines()]
        self.assertEqual("Make tea.", output[1]["message"]["content"])
        self.assertEqual([{"type": "text", "text": "Tea is ready."}], output[2]["message"]["content"])


if __name__ == "__main__":
    unittest.main()
