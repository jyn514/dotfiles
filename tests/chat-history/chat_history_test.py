"""Both transcript consumers must use the same bounded Codex history."""

import contextlib
import base64
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

    def pi_tree(self):
        result = subprocess.run(["node", str(Path(__file__).with_name("inspect-pi-session.mjs")),
                                 str(self.output)], env=self.environment, cwd=ROOT,
                                capture_output=True, text=True)
        self.assertEqual(0, result.returncode, result.stderr)
        return json.loads(result.stdout)

    def native_environment(self):
        binaries = self.root / "native bin"
        binaries.mkdir()
        (binaries / "pi").symlink_to(ROOT / "node_modules/.bin/pi")
        self.environment.update(PATH=f"{binaries}:{self.environment['PATH']}", PI_OFFLINE="1",
                                PI_PACKAGE_DIR=str(ROOT / "node_modules/@earendil-works/pi-coding-agent"))

    def exported_tree(self, file):
        encoded = re.search(r'<script id="session-data" type="application/json">([^<]+)</script>',
                            file.read_text()).group(1)
        data = json.loads(base64.b64decode(encoded))
        self.output.write_text("".join(json.dumps(e) + "\n" for e in [data["header"], *data["entries"]]))
        self.assertEqual(data["leafId"], data["entries"][-1]["id"])
        return self.pi_tree()

    def test_codex_branches_export_through_native_pi_html(self):
        _, latest = self.lineage()
        self.native_environment()
        output_dir = self.root / "HTML exports"
        result = self.run_command(EXTRACT, "--branches", "--native", CHILD,
                                  "--extract-dir", output_dir)
        self.assertEqual(0, result.returncode, result.stderr)
        html = output_dir / (latest.stem + ".html")
        self.assertEqual([html], list(output_dir.iterdir()))
        tree = self.exported_tree(html)
        self.assertEqual(["café", "parent continuation", "current child"], tree["active"])
        self.assertEqual({("café", "discarded parent"),
                          ("café", "parent continuation", "after fork"),
                          ("café", "parent continuation", "discarded child"),
                          ("café", "parent continuation", "current child")},
                         {tuple(path) for path in tree["paths"]})
        self.assertNotIn("extract-chat-codex-", result.stdout)

    def test_codex_native_export_without_directory_uses_source_filename(self):
        _, latest = self.lineage()
        self.native_environment()
        result = self.run_command(EXTRACT, "--branches", "--native", latest, cwd=self.root)
        self.assertEqual(0, result.returncode, result.stderr)
        html = self.root / (latest.stem + ".html")
        self.assertTrue(html.is_file())
        self.assertEqual(["café", "parent continuation", "current child"], self.exported_tree(html)["active"])

    def test_branch_markdown_is_rejected_before_writing(self):
        self.lineage()
        result = self.run_command(EXTRACT, "--branches", "--session", CHILD,
                                  "--extract-dir", self.root / "exports")
        self.assertNotEqual(0, result.returncode)
        self.assertIn("--branches requires --native", result.stderr)
        self.assertFalse((self.root / "exports").exists())

    def test_branches_import_forks_and_reverts_as_a_navigable_pi_tree(self):
        self.lineage()
        sibling_id = "019abcde-1234-7000-8000-000000000005"
        parent_revert = next((self.home / "archived_sessions").rglob(f"*_{PARENT_ROLLOUT}.jsonl"))
        sibling = self.write_rollout(f"rollout-2026-10-14T19-00-00-{sibling_id}.jsonl", sibling_id,
                                     [SKILL, "sibling fork", "sibling fork"],
                                     self.position(parent_revert, PARENT_ROLLOUT, 2, 4), archived=True)
        events = [json.loads(line) for line in sibling.read_text().splitlines()]
        events[0]["payload"]["forked_from_id"] = PARENT
        # A common session_id is not a branch link.
        events[0]["payload"]["session_id"] = PARENT
        sibling.write_text("".join(json.dumps(e) + "\n" for e in events))
        unrelated = self.write_rollout("rollout-2026-10-14T20-00-00-unrelated.jsonl", "unrelated",
                                        ["unrelated session"])
        events = [json.loads(line) for line in unrelated.read_text().splitlines()]
        events[0]["payload"]["session_id"] = PARENT
        unrelated.write_text("".join(json.dumps(e) + "\n" for e in events))
        agent = self.write_rollout("rollout-2026-10-14T20-30-00-agent.jsonl", "agent", ["subagent"],
                                   self.position(parent_revert, PARENT_ROLLOUT, 2, 4))
        events = [json.loads(line) for line in agent.read_text().splitlines()]
        events[0]["payload"]["parent_thread_id"] = PARENT
        agent.write_text("".join(json.dumps(e) + "\n" for e in events))
        result = self.run_command(CONVERT, CHILD, "--branches", "-o", self.output)
        self.assertEqual(0, result.returncode, result.stderr)
        tree = self.pi_tree()
        expected_active = ["café", "parent continuation", "current child"]
        self.assertEqual(expected_active, tree["active"])
        self.assertEqual(expected_active, tree["context"])
        self.assertEqual({("café", "discarded parent"),
                          ("café", "parent continuation", "after fork"),
                          ("café", "parent continuation", "discarded child"),
                          tuple(expected_active),
                          ("café", "parent continuation", "sibling fork", "sibling fork")},
                         {tuple(path) for path in tree["paths"]})
        events = [json.loads(line) for line in self.output.read_text().splitlines()]
        texts = [e["message"]["content"] for e in events if e["type"] == "message"]
        self.assertEqual(1, texts.count("café"))
        self.assertEqual(1, texts.count("parent continuation"))
        self.assertEqual(2, texts.count("sibling fork"))
        self.assertTrue(any(sibling_id in label for label in tree["labels"]))

    def test_branch_import_can_select_a_shared_ancestor_or_empty_thread(self):
        parent, latest = self.lineage()
        for file, expected in ((parent, ["café", "discarded parent"]),
                               (latest, ["café", "parent continuation", "current child"])):
            with self.subTest(file=file.name):
                result = self.run_command(CONVERT, file, "--branches", "-o", self.output)
                self.assertEqual(0, result.returncode, result.stderr)
                tree = self.pi_tree()
                self.assertEqual(expected, tree["active"])
                self.assertEqual(expected, tree["context"])
        empty_id = "019abcde-1234-7000-8000-000000000006"
        empty = self.write_rollout(f"rollout-2026-10-14T15-00-00-{empty_id}.jsonl", empty_id, [])
        alternate = self.write_rollout(f"rollout-2026-10-14T16-00-00-{empty_id}_{PARENT_ROLLOUT}.jsonl",
                                        empty_id, ["alternative from empty"])
        result = self.run_command(CONVERT, empty, "--branches", "-o", self.output)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual([], self.pi_tree()["active"])
        result = self.run_command(CONVERT, alternate, "--branches", "-o", self.output)
        self.assertEqual(0, result.returncode, result.stderr)
        tree = self.pi_tree()
        self.assertEqual(["alternative from empty"], tree["active"])
        self.assertEqual({(), ("alternative from empty",)}, {tuple(path) for path in tree["paths"]})
        self.assertTrue(any(empty_id in label for label in tree["labels"]))

    def test_branch_import_rejects_legacy_and_share_sources_without_writing(self):
        file = self.root / "legacy.jsonl"
        file.write_text(json.dumps({"type": "session_meta", "payload": {"id": CHILD}}) + "\n")
        for source in (file, "https://chatgpt.com/share/test"):
            with self.subTest(source=str(source)):
                self.output.write_text("keep existing\n")
                result = self.run_command(CONVERT, source, "--branches", "-o", self.output)
                self.assertNotEqual(0, result.returncode)
                self.assertIn("paginated", result.stderr)
                self.assertEqual("keep existing\n", self.output.read_text())

    def test_missing_history_in_a_related_fork_preserves_existing_output(self):
        self.lineage()
        sibling_id = "019abcde-1234-7000-8000-000000000005"
        sibling = self.write_rollout(f"rollout-2026-10-14T19-00-00-{sibling_id}.jsonl", sibling_id,
                                     ["unreadable fork"], {"thread_id": "missing",
                                                           "end_byte_offset": 1,
                                                           "end_ordinal_exclusive": 1})
        events = [json.loads(line) for line in sibling.read_text().splitlines()]
        events[0]["payload"]["forked_from_id"] = PARENT
        sibling.write_text("".join(json.dumps(e) + "\n" for e in events))
        self.output.write_text("preserve existing\n")
        result = self.run_command(CONVERT, CHILD, "--branches", "-o", self.output)
        self.assertNotEqual(0, result.returncode)
        self.assertIn("missing or ambiguous source", result.stderr)
        self.assertEqual("", result.stdout)
        self.assertEqual("preserve existing\n", self.output.read_text())

    def test_shared_prefix_can_be_the_selected_branch(self):
        parent = self.write_rollout(f"rollout-2026-10-14T16-00-00-{PARENT}.jsonl", PARENT, ["shared"])
        self.write_rollout(f"rollout-2026-10-14T17-00-00-{CHILD}.jsonl", CHILD, ["longer fork"],
                           self.position(parent, PARENT, 2, 2))
        result = self.run_command(CONVERT, PARENT, "--branches", "-o", self.output)
        self.assertEqual(0, result.returncode, result.stderr)
        tree = self.pi_tree()
        self.assertEqual(["shared"], tree["active"])
        self.assertEqual(["shared"], tree["context"])
        self.assertEqual({("shared",), ("shared", "longer fork")},
                         {tuple(path) for path in tree["paths"]})

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
        image = self.root / "image"
        layout = image / "tools/chat-export"
        for relative in ("tools/extract-chat/extract-chat", "libexec/chat-history.clj", "bin/codex-to-pi"):
            target = layout / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(["cp", str(ROOT / relative), str(target)], check=True)
            subprocess.run(["cmp", str(ROOT / relative), str(target)], check=True)
        entrypoint = image / "opt/agent-tools/bin/extract-chat"
        entrypoint.parent.mkdir(parents=True)
        entrypoint.symlink_to(layout / "tools/extract-chat/extract-chat")
        self.lineage()
        result = self.run_command(entrypoint, "--session", CHILD, cwd=self.root)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("## User\n\ncafé\n\n", result.stdout)
        self.assertIn("## User\n\ncurrent child\n\n", result.stdout)
        self.assertNotIn("discarded", result.stdout)
        self.native_environment()
        result = self.run_command(entrypoint, "--branches", "--native", "--session", CHILD,
                                  "--extract-dir", self.root / "packaged HTML", cwd=self.root)
        self.assertEqual(0, result.returncode, result.stderr)
        html = next((self.root / "packaged HTML").glob("*.html"))
        self.assertEqual(["café", "parent continuation", "current child"], self.exported_tree(html)["active"])

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
