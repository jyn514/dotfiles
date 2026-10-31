"""Both session-ID exporters consume the same paginated Codex UI history."""

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = Path(__file__).resolve().parent
THREAD = "01a1914d-41a7-71d3-bfad-d0e066a2fd73"


class ApiHistoryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="codex API export ")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.home = self.root / "codex"
        self.source = self.home / "sessions/2026/10/31" / f"rollout-2026-10-31T10-32-01-{THREAD}.jsonl"
        self.source.parent.mkdir(parents=True)
        # The raw records deliberately do not describe the displayed conversation.
        self.source.write_text(json.dumps({"type": "session_meta", "payload": {"id": THREAD}}) + "\n" +
                               json.dumps({"type": "event_msg", "payload": {"type": "user_message",
                                                                                 "message": "summary only"}}) + "\n")
        self.output = self.root / "import.jsonl"
        self.fixture_path = self.root / "API.json"
        self.requests = self.root / "requests.jsonl"
        binaries = self.root / "bin"
        binaries.mkdir()
        # A process-spawning shim keeps all fixture mutation in this disposable directory.
        shim = binaries / "codex"
        shim.write_text('#!/bin/sh\nexec node "' + str(FIXTURES / "codex-api-fixture.mjs") + '" "$@"\n')
        shim.chmod(0o755)
        self.env = dict(os.environ, CODEX_HOME=str(self.home),
                        PATH=f"{binaries}:{os.environ['PATH']}", CODEX_HISTORY_FIXTURE=str(self.fixture_path),
                        CODEX_HISTORY_REQUESTS=str(self.requests), PYTHONDONTWRITEBYTECODE="1")
        self.fixture = {"thread": {"id": THREAD, "path": str(self.source), "cwd": str(self.root),
                                    "model": "fixture-model", "createdAt": 1793442721},
                        "pages": [{"data": [self.turn("first", "repeat")], "nextCursor": "1"},
                                  {"data": [], "nextCursor": "2"},
                                  {"data": [self.turn("second", "repeat")], "nextCursor": None}]}

    def turn(self, id, text):
        return {"id": id, "itemsView": "full", "startedAt": 1793442722, "completedAt": 1793442723,
                "items": [{"id": f"user-{id}", "type": "userMessage", "content": [{"type": "text", "text": text}]},
                          {"id": f"agent-{id}", "type": "agentMessage", "text": "done", "phase": "final_answer"}]}

    def run_export(self, converter=True, *flags):
        self.fixture_path.write_text(json.dumps(self.fixture))
        command = ([ROOT / "bin/codex-to-pi", THREAD, "-o", self.output] if converter else
                   [ROOT / "bin/extract-chat", "--session", THREAD])
        return subprocess.run([*map(str, command), *flags], env=self.env, cwd=ROOT, capture_output=True, text=True)

    def test_both_exporters_page_ui_history_and_preserve_repeated_occurrences(self):
        original = self.source.read_bytes()
        for archived in (False, True):
            with self.subTest(archived=archived):
                if archived:
                    target = self.home / "archived_sessions" / self.source.name
                    target.parent.mkdir()
                    self.source.rename(target)
                    self.source = target
                    self.fixture["thread"]["path"] = str(target)
                flags = ("--archived",) if archived else ()
                for converter in (True, False):
                    result = self.run_export(converter, *flags)
                    self.assertEqual(0, result.returncode, result.stderr)
                    if converter:
                        entries = [json.loads(line) for line in self.output.read_text().splitlines()]
                        texts = [e["message"]["content"] if e["message"]["role"] == "user"
                                 else e["message"]["content"][0]["text"] for e in entries[1:]]
                        self.assertEqual(["repeat", "done", "repeat", "done"], texts)
                        self.assertEqual(self.root.as_posix(), entries[0]["cwd"])
                    else:
                        self.assertEqual(["repeat", "done", "repeat", "done"],
                                         re.findall(r"^## (?:User|Assistant)\n\n(.*?)\n\n(?=## |\Z)",
                                                    result.stdout, re.MULTILINE | re.DOTALL))
                self.assertEqual(original, self.source.read_bytes())
        requests = [json.loads(line) for line in self.requests.read_text().splitlines()]
        self.assertEqual({"initialize", "initialized", "thread/read", "thread/turns/list"},
                         {r["method"] for r in requests})
        pages = [r["params"] for r in requests if r["method"] == "thread/turns/list"]
        self.assertEqual([None, "1", "2"] * 4, [r.get("cursor") for r in pages])
        self.assertTrue(all(r["sortDirection"] == "asc" and r["itemsView"] == "full" for r in pages))

    def test_bare_id_and_final_only_share_the_api_reader(self):
        self.fixture["pages"][0]["data"][0]["items"].insert(1, {
            "id": "commentary", "type": "agentMessage", "text": "working", "phase": "commentary"})
        self.fixture_path.write_text(json.dumps(self.fixture))
        for selector in (["--session", THREAD], [THREAD]):
            result = subprocess.run([str(ROOT / "bin/extract-chat"), *selector, "--final-only"],
                                    env=self.env, capture_output=True, text=True)
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertNotIn("working", result.stdout)
            self.assertEqual(2, result.stdout.count("## Assistant\n\ndone"))

    def test_api_failure_and_unsupported_or_incomplete_history_preserve_existing_output(self):
        mutations = [
            lambda f: f.update(error="history unavailable"),
            lambda f: f["pages"][1].update(nextCursor="1"),
            lambda f: f["pages"][0]["data"][0].update(itemsView="summary"),
            lambda f: f["pages"][0]["data"][0]["items"][0]["content"].append({"type": "image", "url": "image"}),
            lambda f: f["pages"][0]["data"][0]["items"][0].update(type="newVisibleMessage"),
            lambda f: f["pages"][2].update(data=f["pages"][0]["data"]),
            lambda f: f["thread"].update(path=str(self.root / "another-rollout.jsonl")),
        ]
        original = json.dumps(self.fixture)
        for index, mutate in enumerate(mutations):
            for converter in (True, False):
                with self.subTest(case=index, converter=converter):
                    self.fixture = json.loads(original)
                    mutate(self.fixture)
                    self.output.write_text("keep existing output\n")
                    result = self.run_export(converter)
                    self.assertNotEqual(0, result.returncode)
                    self.assertEqual("", result.stdout)
                    self.assertTrue(result.stderr)
                    self.assertEqual("keep existing output\n", self.output.read_text())

        destination = self.root / "markdown"
        destination.mkdir()
        markdown = destination / (self.source.stem + ".md")
        markdown.write_text("keep existing Markdown\n")
        self.fixture = json.loads(original)
        self.fixture["error"] = "history unavailable"
        result = self.run_export(False, "--extract-dir", str(destination))
        self.assertNotEqual(0, result.returncode)
        self.assertEqual("keep existing Markdown\n", markdown.read_text())

    def test_packaged_api_reader_resolves_beside_the_extractor_symlink(self):
        image = self.root / "image"
        for name in ("tools/extract-chat/extract-chat", "libexec/chat-history.clj",
                     "libexec/codex-history.mjs", "libexec/codex-client.mjs"):
            target = image / name
            target.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(["cp", str(ROOT / name), str(target)], check=True)
            subprocess.run(["cmp", str(ROOT / name), str(target)], check=True)
        entry = self.root / "extract-chat"
        entry.symlink_to(image / "tools/extract-chat/extract-chat")
        self.fixture_path.write_text(json.dumps(self.fixture))
        result = subprocess.run([str(entry), THREAD], env=self.env, cwd=self.root, capture_output=True, text=True)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(2, result.stdout.count("## User\n\nrepeat"))

    def test_native_import_exports_displayed_history_in_active_and_archived_sessions(self):
        if not shutil.which("codex"):
            self.skipTest("native Codex is not installed")
        # Bypass only the fixture codex shim, retaining the harness's native-tool selection.
        environment = dict(self.env, PATH=os.environ["PATH"])
        (self.home / "config.toml").write_text("[features]\nplugins = false\napps = false\n")
        for archived, fork in ((False, False), (True, False), (False, True), (True, True)):
            with self.subTest(archived=archived, fork=fork):
                flags = ["--archived"] if archived else []
                created = subprocess.run(["node", str(FIXTURES / "native-codex-fixture.mjs"), *flags,
                                          *(["--fork"] if fork else [])],
                                         env=environment, cwd=self.root, capture_output=True, text=True)
                self.assertEqual(0, created.returncode, created.stderr)
                id = json.loads(created.stdout)["id"]
                converted = subprocess.run([str(ROOT / "bin/codex-to-pi"), id, "-o", str(self.output), *flags],
                                           env=environment, capture_output=True, text=True)
                self.assertEqual(0, converted.returncode, converted.stderr)
                entries = [json.loads(line) for line in self.output.read_text().splitlines()]
                texts = [e["message"]["content"] if e["message"]["role"] == "user"
                         else e["message"]["content"][0]["text"] for e in entries[1:]]
                self.assertEqual(["imported summary", "repeat", "done", "repeat", "done"], texts)
                extracted = subprocess.run([str(ROOT / "bin/extract-chat"), id, *flags],
                                           env=environment, capture_output=True, text=True)
                self.assertEqual(0, extracted.returncode, extracted.stderr)
                self.assertNotIn("model-only", extracted.stdout)
                self.assertEqual(2, extracted.stdout.count("## User\n\nrepeat"))
                # Read the actual Pi branch, rather than accepting JSON shape alone.
                inspected = subprocess.run(["node", str(FIXTURES / "inspect-pi-session.mjs"), str(self.output)],
                                           env=environment, capture_output=True, text=True)
                self.assertEqual(0, inspected.returncode, inspected.stderr)
                self.assertEqual(texts, json.loads(inspected.stdout)[0]["active"])


if __name__ == "__main__":
    unittest.main()
