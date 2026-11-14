"""Account exports preserve readable history through the real CLI and Pi loader."""

import base64
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
import zipfile


ROOT = Path(__file__).resolve().parents[3]
COMMAND = ROOT / "bin/codex-to-pi"
FIRST = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
SECOND = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=")


def node(id, parent, role=None, content=None, **extra):
    message = None if role is None else {
        "id": id, "author": {"role": role}, "create_time": 1001.25,
        "content": content or {"content_type": "text", "parts": [id]}, **extra}
    return {"id": id, "parent": parent, "message": message}


def conversation(id=FIRST):
    # Source object order deliberately disagrees with parent order. No children arrays.
    return {"id": id, "title": "café / ../ 日本語", "create_time": 1000,
            "default_model_slug": "export-default", "current_node": "answer",
            "mapping": {
                "answer": node("answer", "recap", "assistant",
                               metadata={"model_slug": "answer-model"}),
                "alternate": node("alternate", "question", "assistant"),
                "root": node("root", None),
                "question": node("question", "root", "user",
                                 {"content_type": "text", "parts": ["repeat", "repeat"]}),
                "thought": node("thought", "question", "assistant", {
                    "content_type": "thoughts", "thoughts": [
                        {"summary": "Plan", "content": "Detailed reasoning", "chunks": ["Detailed", "reasoning"]},
                        {"summary": "Next", "content": "", "chunks": ["one", "two"]}]}),
                "recap": node("recap", "thought", "assistant", {
                    "content_type": "reasoning_recap", "content": "Reasoning summary"})}}


class ChatGPTExportTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="ChatGPT export ")
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.archive = self.directory / "account export.zip"
        self.output = self.directory / "output"
        self.environment = dict(os.environ, PI_CODING_AGENT_DIR=str(self.directory / "agent"),
                                PYTHONDONTWRITEBYTECODE="1")

    def write_export(self, conversations=None, assets=None, shards=False):
        conversations = conversations if conversations is not None else [conversation()]
        with zipfile.ZipFile(self.archive, "w") as archive:
            if shards:
                for index, item in enumerate(conversations):
                    archive.writestr(f"conversations-{index:03}.json", json.dumps([item]))
            else:
                archive.writestr("conversations.json", json.dumps(conversations))
            for name, data in (assets or {}).items():
                archive.writestr(name, json.dumps(data) if isinstance(data, (dict, list)) else data)

    def run_cli(self, *args, source=None, with_cwd=True):
        cwd_args = ["--cwd", str(self.directory)] if with_cwd and "--list" not in args else []
        return subprocess.run([str(COMMAND), str(source or self.archive), *cwd_args, *map(str, args)],
                              cwd=self.directory, env=self.environment, capture_output=True, text=True)

    def read_entries(self, result):
        self.assertEqual(0, result.returncode, result.stderr)
        files = list(self.output.glob("*.jsonl"))
        self.assertEqual(1, len(files))
        return [json.loads(line) for line in files[0].read_text().splitlines()]

    def messages(self, entries):
        return [e["message"] for e in entries if e["type"] == "message"]

    def test_selected_path_preserves_title_times_model_repetition_and_reasoning(self):
        self.write_export()
        entries = self.read_entries(self.run_cli("--output-dir", self.output))
        self.assertEqual(FIRST, entries[0]["id"])
        self.assertEqual("1970-01-01T00:16:40Z", entries[0]["timestamp"])
        self.assertEqual("café / ../ 日本語", entries[-1]["name"])
        messages = self.messages(entries)
        self.assertEqual(["user", "assistant", "assistant", "assistant"], [m["role"] for m in messages])
        self.assertEqual([{"type": "text", "text": "repeat"}] * 2, messages[0]["content"])
        self.assertEqual([{"type": "thinking", "thinking": "Plan\n\nDetailed reasoning\n\nNext\n\none\ntwo"}], messages[1]["content"])
        self.assertEqual([{"type": "thinking", "thinking": "Reasoning summary"}], messages[2]["content"])
        self.assertEqual("answer-model", messages[-1]["model"])
        self.assertEqual("openai", messages[-1]["provider"])
        self.assertEqual(1001250, messages[-1]["timestamp"])
        parent = None
        for entry in entries[1:]:
            self.assertEqual(parent, entry["parentId"])
            parent = entry["id"]

    def test_shards_list_selection_and_batch_import(self):
        self.write_export([conversation(), conversation(SECOND)], shards=True)
        result = self.run_cli("--list")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual([FIRST, SECOND], [line.split("\t")[0] for line in result.stdout.splitlines()])
        self.assertFalse(self.output.exists())
        single = self.directory / "batch-as-single.jsonl"
        result = self.run_cli("-o", single)
        self.assertNotEqual(0, result.returncode)
        self.assertIn("--conversation", result.stderr)
        self.assertFalse(single.exists())
        self.assertFalse(single.with_suffix(".assets").exists())
        result = self.run_cli("--output-dir", self.output)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("8 messages across 2 sessions", result.stdout)
        self.assertEqual(2, len(list(self.output.glob("*.jsonl"))))
        selected = self.directory / "selected.jsonl"
        result = self.run_cli("--conversation", SECOND, "-o", selected)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(SECOND, json.loads(selected.read_text().splitlines()[0])["id"])
        self.assertIn(str(selected), result.stdout)

    def test_import_requires_explicit_cwd_even_with_an_output_path(self):
        self.write_export()
        for options in (("--output-dir", self.output), ("-o", self.directory / "single.jsonl"), ()):
            with self.subTest(options=options):
                result = self.run_cli(*options, with_cwd=False)
                self.assertNotEqual(0, result.returncode)
                self.assertIn("require --cwd DIR", result.stderr)
                self.assertFalse(self.output.exists())
                self.assertFalse((self.directory / "single.jsonl").exists())
                self.assertFalse((self.directory / "agent/sessions").exists())
        result = self.run_cli("--list", with_cwd=False)
        self.assertEqual(0, result.returncode, result.stderr)

    def test_cwd_argument_controls_header_and_default_pi_directory_not_process_cwd(self):
        self.write_export()
        chosen = self.directory / "chosen project"
        result = self.run_cli("--cwd", chosen, with_cwd=False)
        self.assertEqual(0, result.returncode, result.stderr)
        files = list((self.directory / "agent/sessions").rglob("*.jsonl"))
        self.assertEqual(1, len(files))
        self.assertEqual(str(chosen), json.loads(files[0].read_text().splitlines()[0])["cwd"])
        self.assertEqual("--" + str(chosen).lstrip("/").replace("/", "-") + "--", files[0].parent.name)
        # Relative arguments have the same meaning as the caller's ordinary paths.
        explicit = self.directory / "relative.jsonl"
        result = self.run_cli("--cwd", "relative project", "-o", explicit, with_cwd=False)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(str(self.directory / "relative project"), json.loads(explicit.read_text().splitlines()[0])["cwd"])

    def test_default_output_is_discoverable_in_pi_session_directory(self):
        self.write_export()
        result = self.run_cli()
        self.assertEqual(0, result.returncode, result.stderr)
        files = list((self.directory / "agent/sessions").rglob("*.jsonl"))
        self.assertEqual(1, len(files))
        self.assertIn(str(files[0]), result.stdout)

    def test_default_import_includes_all_conversations_in_pi_session_directory(self):
        self.write_export([conversation(), conversation(SECOND)], shards=True)
        result = self.run_cli()
        self.assertEqual(0, result.returncode, result.stderr)
        files = list((self.directory / "agent/sessions").rglob("*.jsonl"))
        self.assertEqual({FIRST, SECOND}, {json.loads(file.read_text().splitlines()[0])["id"] for file in files})
        self.assertIn("8 messages across 2 sessions", result.stdout)

    def test_images_transcriptions_and_files_resolve_dat_and_library_ids(self):
        item = conversation()
        item["mapping"]["question"]["message"]["content"] = {
            "content_type": "multimodal_text", "parts": ["Look", {
                "content_type": "image_asset_pointer", "asset_pointer": "sediment://file-image"},
                {"content_type": "audio_transcription", "text": "Spoken words"}]}
        item["mapping"]["question"]["message"]["metadata"] = {"attachments": [
            {"id": "file-image", "name": "photo.png", "mime_type": "image/png"},
            {"id": "old-file", "library_file_id": "library-one", "name": "../../secret.txt"}]}
        self.write_export([item], {"file-image.dat": PNG, "file-document.dat": b"exact file bytes",
                                  "library_files.json": [{"id": {"id": "library-one"}, "file_id": "file-document"}]})
        entries = self.read_entries(self.run_cli("--output-dir", self.output))
        blocks = self.messages(entries)[0]["content"]
        self.assertEqual(["text", "image", "text", "text"], [b["type"] for b in blocks])
        self.assertEqual(PNG, base64.b64decode(blocks[1]["data"]))
        self.assertEqual("image/png", blocks[1]["mimeType"])
        self.assertEqual("Spoken words", blocks[2]["text"])
        saved = list(self.output.glob("*.assets/*/*"))
        self.assertEqual(2, len(saved))
        document = next(p for p in saved if p.read_bytes() == b"exact file bytes")
        self.assertIn(str(document), blocks[3]["text"])
        self.assertEqual(self.output, document.parents[2])
        self.assertFalse((self.directory / "secret.txt").exists())

    def test_asset_index_supplies_original_filename_and_unsupported_image_is_saved(self):
        item = conversation()
        item["mapping"]["question"]["message"]["content"] = {"content_type": "multimodal_text", "parts": [
            {"content_type": "image_asset_pointer", "asset_pointer": "file-service://file-image", "mime_type": "image/heic"}]}
        item["mapping"]["question"]["message"]["metadata"] = {"attachments": [
            {"id": "file-image", "mime_type": "image/heic"}]}
        self.write_export([item], {"file-image.dat": b"unsupported image bytes",
                                  "conversation_asset_file_names.json": {"file-image.dat": "original.heic"}})
        result = self.run_cli("--output-dir", self.output)
        entries = self.read_entries(result)
        self.assertIn("saved as files", result.stderr)
        self.assertIn("original.heic", self.messages(entries)[0]["content"][0]["text"])
        self.assertEqual(1, len(list(self.output.glob("*.assets/*/*"))))

    def test_missing_assets_and_unknown_parts_are_visible_not_silently_lost(self):
        item = conversation()
        item["mapping"]["question"]["message"]["content"] = {"content_type": "multimodal_text", "parts": [
            {"content_type": "image_asset_pointer", "asset_pointer": "sediment://missing"},
            {"content_type": "future-format", "payload": "keep me"}]}
        self.write_export([item])
        result = self.run_cli("--output-dir", self.output)
        blocks = self.messages(self.read_entries(result))[0]["content"]
        self.assertIn("Missing ChatGPT attachment", blocks[0]["text"])
        self.assertIn("sediment://missing", blocks[0]["text"])
        self.assertIn("keep me", blocks[1]["text"])
        self.assertIn("1 attachment reference with no local file data", result.stderr)
        self.assertIn(FIRST, result.stderr)
        self.assertIn("question", result.stderr)
        self.assertIn("sediment://missing", result.stderr)
        self.assertIn("preserved as JSON", result.stderr)

    def inspect_pi(self):
        result = subprocess.run(["node", str(ROOT / "tests/chat-history/inspect-pi-session.mjs"),
                                 str(next(self.output.glob("*.jsonl")))],
                                env=self.environment, capture_output=True, text=True)
        self.assertEqual(0, result.returncode, result.stderr)
        return json.loads(result.stdout)[0]

    def test_orphan_tool_results_and_system_content_survive_with_files_and_images(self):
        for branches in (False, True):
            with self.subTest(branches=branches):
                self.output = self.directory / str(branches)
                item = conversation()
                system = node("system", "root", "system", {"content_type": "text", "parts": ["Archived instructions"]})
                tool = node("tool", "question", "tool", {"content_type": "multimodal_text", "parts": [
                    "Unique tool output", {"content_type": "image_asset_pointer", "asset_pointer": "file-image"}]},
                    metadata={"attachments": [{"id": "file-image", "name": "result.png"},
                                              {"id": "file-document", "name": "result.txt"}]})
                tool["message"]["author"]["name"] = "python"
                item["mapping"].update(system=system, tool=tool)
                item["mapping"]["question"]["parent"] = "system"
                item["mapping"]["thought"]["parent"] = "tool"
                self.write_export([item], {"file-image.dat": PNG, "file-document.dat": b"tool attachment bytes"})
                result = self.run_cli(*(["--branches"] if branches else []), "--output-dir", self.output)
                entries = self.read_entries(result)
                custom = [e for e in entries if e["type"] == "custom_message"]
                self.assertEqual([system["message"], tool["message"]], [e["details"]["message"] for e in custom])
                self.assertTrue(all(e["display"] for e in custom))
                self.assertFalse(any(m["role"] in ("system", "toolResult") for m in self.messages(entries)))
                self.assertIn("Unique tool output", str(custom[-1]["content"]))
                image = next(b for b in custom[-1]["content"] if b["type"] == "image")
                self.assertEqual(PNG, base64.b64decode(image["data"]))
                self.assertEqual({PNG, b"tool attachment bytes"},
                                 {p.read_bytes() for p in self.output.glob("*.assets/*/*")})
                tree = self.inspect_pi()
                self.assertEqual(tree["active"], tree["context"])
                self.assertEqual(2, tree["roles"].count("custom"))
                self.assertTrue(any("Unique tool output" in value for value in tree["context"]))
                self.assertNotIn("omitted", result.stderr)

    def test_tool_pairs_require_matching_names_and_json_object_arguments(self):
        cases = [("text", '{"query":"résumé"}', "browser", True),
                 ("text", '{"query":"résumé"}', "other-tool", False),
                 ("text", '["not an argument object"]', "browser", False),
                 ("text", 'not JSON', "browser", False),
                 ("text", '{"value":NaN}', "browser", False),
                 ("text", '{"value":1e400}', "browser", False),
                 ("code", 'print("résumé")', "browser", False)]
        for branches in (False, True):
            for index, (kind, body, result_name, native) in enumerate(cases):
                with self.subTest(branches=branches, kind=kind, result_name=result_name, body=body):
                    self.output = self.directory / f"pair-{branches}-{index}"
                    item = conversation()
                    content = {"content_type": kind, **({"parts": [body]} if kind == "text" else {"text": body})}
                    item["mapping"]["call"] = node("call", "question", "assistant", content, recipient="browser")
                    item["mapping"]["gap"] = node("gap", "call")
                    item["mapping"]["result"] = node("result", "gap", "tool",
                        {"content_type": "multimodal_text", "parts": ["Matched tool output",
                            {"content_type": "image_asset_pointer", "asset_pointer": "file-image"}]},
                        metadata={"is_error": True, "attachments": [{"id": "file-tool", "name": "tool.txt"},
                                                                  {"id": "file-image", "name": "result.png"}]})
                    item["mapping"]["result"]["message"]["author"]["name"] = result_name
                    item["mapping"]["thought"]["parent"] = "result"
                    self.write_export([item], {"file-tool.dat": b"native tool attachment", "file-image.dat": PNG})
                    result = self.run_cli(*(["--branches"] if branches else []), "--output-dir", self.output)
                    entries = self.read_entries(result)
                    tree = self.inspect_pi()
                    self.assertEqual(tree["active"], tree["context"])
                    self.assertTrue(any("Matched tool output" in value for value in tree["context"]))
                    self.assertEqual({b"native tool attachment", PNG},
                                     {p.read_bytes() for p in self.output.glob("*.assets/*/*")})
                    if native:
                        self.assertEqual(1, len(tree["toolCalls"]))
                        self.assertEqual({"query": "résumé"}, tree["toolCalls"][0]["arguments"])
                        self.assertEqual("browser", tree["toolCalls"][0]["name"])
                        self.assertEqual(1, len(tree["toolResults"]))
                        self.assertEqual(tree["toolCalls"][0]["id"], tree["toolResults"][0]["toolCallId"])
                        self.assertTrue(tree["toolResults"][0]["isError"])
                        image = next(b for b in tree["toolResults"][0]["content"] if b["type"] == "image")
                        self.assertEqual(PNG, base64.b64decode(image["data"]))
                        self.assertIn("toolResult", tree["roles"])
                        self.assertFalse(any(e["type"] == "custom_message" for e in entries))
                    else:
                        self.assertEqual([], tree["toolCalls"])
                        self.assertEqual([], tree["toolResults"])
                        custom = [e for e in entries if e["type"] == "custom_message"]
                        self.assertEqual(2, len(custom))
                        self.assertTrue(any(body in value for value in tree["context"]))
                        self.assertEqual(content, custom[0]["details"]["message"]["content"])

    def test_native_calls_never_dangle_on_an_imported_branch_or_selected_tip(self):
        for branches in (False, True):
            for current in ("call", "unfinished", "alternate", "result"):
                with self.subTest(branches=branches, current=current):
                    self.output = self.directory / f"branch-{branches}-{current}"
                    item = conversation()
                    item["mapping"] = {
                        "question": node("question", None, "user"),
                        "call": node("call", "question", "assistant",
                                     {"content_type": "text", "parts": ['{"query":"branch"}']}, recipient="browser"),
                        "unfinished": node("unfinished", "call"),
                        "alternate": node("alternate", "call", "assistant"),
                        "result": node("result", "call", "tool")}
                    item["current_node"] = current
                    self.write_export([item])
                    entries = self.read_entries(self.run_cli(*(["--branches"] if branches else []),
                                                             "--output-dir", self.output))
                    expected_native = int(not branches and current == "result")
                    # Check all imported branches, not just the active context.
                    calls = [b for m in self.messages(entries) for b in m["content"] if b["type"] == "toolCall"]
                    results = [m for m in self.messages(entries) if m["role"] == "toolResult"]
                    self.assertEqual(expected_native, len(calls))
                    self.assertEqual(expected_native, len(results))
                    tree = self.inspect_pi()
                    self.assertEqual(tree["active"], tree["context"])
                    self.assertEqual(expected_native, len(tree["toolCalls"]))
                    self.assertEqual(expected_native, len(tree["toolResults"]))

    def test_empty_tool_results_remain_native_results(self):
        for parts in ([""], []):
            with self.subTest(parts=parts):
                self.output = self.directory / f"empty-{len(parts)}"
                item = conversation()
                item["mapping"]["call"] = node("call", "question", "assistant",
                    {"content_type": "text", "parts": ["{}"]}, recipient="browser")
                item["mapping"]["result"] = node("result", "call", "tool",
                    {"content_type": "text", "parts": parts})
                item["mapping"]["thought"]["parent"] = "result"
                self.write_export([item])
                self.read_entries(self.run_cli("--output-dir", self.output))
                tree = self.inspect_pi()
                self.assertEqual(1, len(tree["toolCalls"]))
                self.assertEqual(1, len(tree["toolResults"]))
                self.assertEqual([], tree["toolResults"][0]["content"])
                self.assertEqual(tree["toolCalls"][0]["id"], tree["toolResults"][0]["toolCallId"])
                self.assertFalse(tree["toolResults"][0]["isError"])

    def test_missing_attachment_diagnostics_count_per_message_references_and_identify_each(self):
        first, second = conversation(), conversation(SECOND)
        first["title"] = "First conversation"
        second["title"] = "Second conversation"
        for item, node_id in ((first, "question"), (first, "answer"), (second, "answer")):
            item["mapping"][node_id]["message"]["metadata"] = {"attachments": [
                {"id": "file-missing", "name": "missing\\nfile.pdf"}] * 2}
        first["mapping"]["question"]["message"]["content"] = {"content_type": "multimodal_text", "parts": [
            {"content_type": "image_asset_pointer", "asset_pointer": "file-service://file-missing"}]}
        self.write_export([first, second])
        result = self.run_cli("--output-dir", self.output)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("3 attachment references with no local file data; references retained", result.stderr)
        self.assertNotIn("missing attachment bytes", result.stderr)
        details = [line for line in result.stderr.splitlines() if line.startswith("  conversation ")]
        self.assertEqual(3, len(details))
        for line, id, title, message in zip(details, (FIRST, FIRST, SECOND),
                                          ("First conversation", "First conversation", "Second conversation"),
                                          ("question", "answer", "answer")):
            self.assertIn(id, line)
            self.assertIn(title, line)
            self.assertIn(f'message "{message}"', line)
            self.assertIn('missing\\\\nfile.pdf', line)
            self.assertIn("file-missing", line)

    def test_bad_parent_cycle_and_missing_current_fail_without_outputs(self):
        for fault in ("cycle", "missing-parent", "missing-current"):
            with self.subTest(fault=fault):
                item = conversation()
                if fault == "cycle":
                    item["mapping"]["question"]["parent"] = "answer"
                elif fault == "missing-parent":
                    item["mapping"]["answer"]["parent"] = "absent"
                else:
                    item["current_node"] = "absent"
                self.write_export([item])
                result = self.run_cli("--output-dir", self.output)
                self.assertNotEqual(0, result.returncode)
                self.assertNotIn("Traceback", result.stderr)
                self.assertFalse(self.output.exists())

    def test_existing_destination_is_unchanged_and_batch_preflights_all_outputs(self):
        self.write_export([conversation(), conversation(SECOND)], shards=True)
        first = self.directory / "first.jsonl"
        first.write_text("owned by someone else")
        result = self.run_cli("--conversation", FIRST, "-o", first)
        self.assertNotEqual(0, result.returncode)
        self.assertEqual("owned by someone else", first.read_text())
        self.output.mkdir()
        collision = self.output / f"1970-01-01T00-16-40Z_{SECOND}.jsonl"
        collision.write_text("existing")
        result = self.run_cli("--output-dir", self.output)
        self.assertNotEqual(0, result.returncode)
        self.assertEqual([collision], list(self.output.iterdir()))

    def test_extracted_directory_and_single_json_are_supported(self):
        source = self.directory / "extracted"
        source.mkdir()
        file = source / "conversations.json"
        file.write_text(json.dumps([conversation()]))
        for path in (source, file):
            with self.subTest(source=path):
                output = self.directory / (path.name + ".jsonl")
                result = self.run_cli("-o", output, source=path)
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertTrue(output.is_file())

    def test_branches_load_in_pi_and_current_node_is_selected(self):
        self.write_export()
        self.read_entries(self.run_cli("--branches", "--output-dir", self.output))
        file = next(self.output.glob("*.jsonl"))
        result = subprocess.run(["node", str(ROOT / "tests/chat-history/inspect-pi-session.mjs"), str(file)],
                                env=self.environment, capture_output=True, text=True)
        self.assertEqual(0, result.returncode, result.stderr)
        tree = json.loads(result.stdout)[0]
        self.assertEqual(["repeat\nrepeat", "", "", "answer"], tree["active"])
        self.assertEqual(tree["active"], tree["context"])
        self.assertIn(["repeat\nrepeat", "alternate"], tree["paths"])
        self.assertEqual(5, sum(1 for e in map(json.loads, file.read_text().splitlines()) if e["type"] == "message"))

    def test_invalid_zip_and_json_report_errors_without_tracebacks(self):
        for data in (b"not a zip", None):
            with self.subTest(data=data):
                if data is not None:
                    self.archive.write_bytes(data)
                else:
                    with zipfile.ZipFile(self.archive, "w") as archive:
                        archive.writestr("conversations.json", "not JSON")
                result = self.run_cli("--output-dir", self.output)
                self.assertNotEqual(0, result.returncode)
                self.assertIn("ChatGPT import failed", result.stderr)
                self.assertNotIn("Traceback", result.stderr)
                self.assertFalse(self.output.exists())

    def test_extracted_asset_symlinks_cannot_read_outside_export(self):
        source = self.directory / "export-directory"
        source.mkdir()
        outside = self.directory / "private.txt"
        outside.write_text("not part of the export")
        (source / "file-private.dat").symlink_to(outside)
        item = conversation()
        item["mapping"]["question"]["message"]["metadata"] = {"attachments": [{"id": "file-private"}]}
        (source / "conversations.json").write_text(json.dumps([item]))
        result = self.run_cli("--output-dir", self.output, source=source)
        self.assertNotEqual(0, result.returncode)
        self.assertIn("escapes input directory", result.stderr)
        self.assertFalse(self.output.exists())

    def test_empty_conversation_keeps_title_and_can_load_in_pi(self):
        item = conversation()
        item["mapping"] = {"root": node("root", None)}
        item["current_node"] = "root"
        self.write_export([item])
        entries = self.read_entries(self.run_cli("--branches", "--output-dir", self.output))
        self.assertEqual([], self.messages(entries))
        self.assertEqual("session_info", entries[-1]["type"])
        self.assertIsNone(entries[-1]["parentId"])
        result = subprocess.run(["node", str(ROOT / "tests/chat-history/inspect-pi-session.mjs"),
                                 str(next(self.output.glob("*.jsonl")))],
                                env=self.environment, capture_output=True, text=True)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual([], json.loads(result.stdout)[0]["context"])

    def test_assistant_images_are_file_references_not_invalid_image_blocks(self):
        item = conversation()
        item["mapping"]["answer"]["message"]["content"] = {"content_type": "multimodal_text", "parts": [
            {"content_type": "image_asset_pointer", "asset_pointer": "sediment://generated"}]}
        self.write_export([item], {"generated.dat": PNG})
        entries = self.read_entries(self.run_cli("--output-dir", self.output))
        blocks = self.messages(entries)[-1]["content"]
        self.assertEqual(["text"], [b["type"] for b in blocks])
        self.assertIn("saved to:", blocks[0]["text"])
        self.assertEqual(PNG, next(self.output.glob("*.assets/*/*")).read_bytes())

    def test_archive_member_names_are_never_extracted_as_paths(self):
        item = conversation()
        item["mapping"]["question"]["message"]["metadata"] = {"attachments": [{"id": "../outside", "name": "../evil"}]}
        self.write_export([item], {"../outside.dat": b"safe bytes"})
        self.read_entries(self.run_cli("--output-dir", self.output))
        self.assertFalse((self.directory / "outside.dat").exists())
        saved = list(self.output.glob("*.assets/*/*"))
        self.assertEqual(1, len(saved))
        self.assertEqual(b"safe bytes", saved[0].read_bytes())


if __name__ == "__main__":
    unittest.main()
