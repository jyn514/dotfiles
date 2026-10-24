"""Exercise the advisory producer through the supported agent-split CLI.

Pi owns retirement/retry and final writes; this suite deliberately sends repeated
requests with the same revision to prove the producer has no retry state.
"""
import base64
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[3]
CLI = ROOT / "libexec/agent-wrappers/bb"


def encoded(content):
    if isinstance(content, str):
        content = content.encode("utf-8")
    return base64.b64encode(content).decode("ascii")


def actual(content, executable=False):
    return {"content": encoded(content), "executable": executable}


@unittest.skipUnless(shutil.which("bb") and shutil.which("jj") and shutil.which("git"),
                     "requires bb, jj and git")
class CheckFileTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="agent-split-check-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.env = dict(os.environ, BB_SOURCE_ROOT=str(ROOT))
        self.jj("git", "init", "--colocate")
        self.jj("config", "set", "--repo", "user.name", "Boundary test")
        self.jj("config", "set", "--repo", "user.email", "boundary@example.invalid")
        self.head = "".join(f"head {n}\n" for n in range(12))
        self.tail = "".join(f"tail {n}\n" for n in range(12))
        self.section = "Instructions\nKeep exact words.\nPreserve this section.\n\n"
        self.base = self.head + self.section + self.tail + "footer\n"
        (self.repo / "note.txt").write_text(self.base)
        (self.repo / "unrelated.txt").write_text("before\n")
        (self.repo / "unchanged.txt").write_text("original\n")
        self.jj("commit", "-m", "base")
        # Both dirty changes precede the reorganization revision. Neither is
        # authorship metadata or authority to commit the unrelated formatting.
        self.current = self.section + self.head + self.tail + "footer  \n"
        (self.repo / "note.txt").write_text(self.current)
        (self.repo / "unrelated.txt").write_text("dirty formatting  \n")
        self.revision = self.capture_revision()
        self.assertRegex(self.revision, r"^[0-9a-f]{40}$")

    def command(self, argv, *, input=None, cwd=None):
        result = subprocess.run(argv, cwd=cwd or self.repo, env=self.env,
                                input=input, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def jj(self, *args):
        return self.command(["jj", *args]).stdout.strip()

    def cli(self, mode, request=None, *, cwd=None, raw=None):
        result = self.command([str(CLI), "agent-split", mode], cwd=cwd,
                              input=raw if raw is not None else
                              (json.dumps(request) if request is not None else None))
        self.assertEqual(result.stderr, "")
        return json.loads(result.stdout)

    def check(self, proposed, *, state=..., path="note.txt", revision=None, cwd=None):
        return self.cli("--check-file", {
            "revision": revision or self.revision,
            "path": path,
            "actual": actual(self.current) if state is ... else state,
            "proposed": encoded(proposed),
        }, cwd=cwd)

    def capture_revision(self):
        self.jj("status")
        return self.jj("log", "--ignore-working-copy", "-r", "@", "--no-graph", "-T", "commit_id")

    def identity(self):
        return (self.jj("log", "--ignore-working-copy", "-r", "@", "--no-graph", "-T", "commit_id"),
                self.jj("op", "log", "--ignore-working-copy", "--limit", "1", "--no-graph", "-T", "id"))

    def assert_unusable(self, result):
        self.assertEqual(result["status"], "unusable", result)
        self.assertEqual(set(result), {"status", "reason"})
        self.assertNotIn("diagnostic", result)

    def trace_jj(self):
        real = shutil.which("jj")
        directory = self.root / "bin"
        directory.mkdir()
        log = self.root / "jj-reads.jsonl"
        shim = directory / "jj"
        shim.write_text("#!/usr/bin/env python3\nimport json, os, sys\n"
                        f"with open({str(log)!r}, 'a') as f: f.write(json.dumps(sys.argv[1:]) + '\\n')\n"
                        f"os.execv({real!r}, [{real!r}, *sys.argv[1:]])\n")
        shim.chmod(0o755)
        self.env["PATH"] = str(directory) + os.pathsep + self.env["PATH"]
        return log

    def test_warning_and_baseline_are_independent_of_retries_and_disk(self):
        before = self.identity()
        proposal = "See the extracted skill.\n\n" + self.head + self.tail + "footer  \n"
        warning = self.check(proposal)
        self.assertEqual(warning["status"], "would-lose", warning)
        self.assertEqual(set(warning), {"status", "reason"})
        reason = ("selected base gap before line 1; original edit at base gap before line 1: "
                  "added lines differ in content, count, order, replacement position, or newline state")
        self.assertEqual(warning, {"status": "would-lose", "reason": reason})
        self.assertNotIn("diagnostic", warning)
        self.assertEqual(self.check(proposal), warning)
        # If another writer already performed that extraction, it is an
        # unusable baseline, not a warning blaming a subsequent proposal.
        lost = self.check(proposal + "later\n", state=actual(proposal))
        self.assertEqual(lost, {"status": "unusable", "reason": "boundary was already lost: " + reason})
        self.assertEqual(self.identity(), before)
        self.assertEqual((self.repo / "note.txt").read_text(), self.current)
        self.assertEqual((self.repo / "unrelated.txt").read_text(), "dirty formatting  \n")

    def test_successive_preserved_checks_retain_one_revision_and_do_not_snapshot(self):
        log = self.trace_jj()
        first = self.current.replace("head 6\n", "independent edit\n")
        second = first.replace("tail 6\n", "another independent edit\n")
        before = self.identity()
        for state, proposal in [(self.current, first), (first, second)]:
            result = self.check(proposal, state=actual(state))
            self.assertEqual(result, {"status": "preserved"})
        # Disk was intentionally not updated: actual is the retained native
        # tool state, not a fresh revision or a read of the checkout target.
        self.assertEqual(self.identity(), before)
        commands = [json.loads(line) for line in log.read_text().splitlines()]
        self.assertTrue(commands)
        reads = {"show": 0, "list": 0}
        for command in commands:
            self.assertIn("--ignore-working-copy", command)
            self.assertNotIn(command[0], ["status", "split", "commit"])
            normalized = [arg for arg in command if arg != "--ignore-working-copy"]
            if normalized[:2] in [["file", "show"], ["file", "list"]]:
                reads[normalized[1]] += 1
                self.assertEqual(normalized[-2:], ["--", 'root-file:"note.txt"'])
        # Count the assertions that actually ran: native JJ inserts its global
        # ignore flag between "file" and "show"/"list".
        self.assertEqual(reads, {"show": 4, "list": 4})

    def test_literal_fileset_metacharacters_only_fetch_the_target(self):
        targets = ["literal*.txt", "note.txt | unrelated.txt", 'quote"name.txt', "back\\slash.txt"]
        for path in targets:
            (self.repo / path).write_text("base\n")
        (self.repo / "literal-other.txt").write_text("other baseline\n")
        self.jj("commit", "-m", "literal filename base")
        for path in targets:
            (self.repo / path).write_text("base\nrevision\n")
        (self.repo / "literal-other.txt").write_text("unrelated dirty hunk\n")
        (self.repo / "unrelated.txt").write_text("another unrelated dirty hunk\n")
        revision = self.capture_revision()
        log = self.trace_jj()
        for path in targets:
            with self.subTest(path=path):
                log.write_text("")
                result = self.check("base\n", path=path, state=actual("base\nrevision\n"),
                                    revision=revision)
                # Quoted/backslash names still hit the shared diff parser's
                # documented encoding limit, after successful exact JJ reads.
                expected = "unusable" if '"' in path or "\\" in path else "would-lose"
                self.assertEqual(result["status"], expected, result)
                if expected == "unusable":
                    self.assertEqual(result["reason"], "canonical diff path encoding is unsupported")
                self.assertEqual(set(result), {"status", "reason"})
                self.assertNotIn("diagnostic", result)
                commands = [json.loads(line) for line in log.read_text().splitlines()]
                reads = {"show": 0, "list": 0}
                for command in commands:
                    normalized = [arg for arg in command if arg != "--ignore-working-copy"]
                    if normalized[:2] in [["file", "show"], ["file", "list"]]:
                        reads[normalized[1]] += 1
                        self.assertEqual(normalized[-2:], ["--", "root-file:" + json.dumps(path)])
                self.assertEqual(reads, {"show": 2, "list": 2})
                self.assertEqual((self.repo / path).read_text(), "base\nrevision\n")
        self.assertEqual((self.repo / "literal-other.txt").read_text(), "unrelated dirty hunk\n")
        self.assertEqual((self.repo / "unrelated.txt").read_text(), "another unrelated dirty hunk\n")

    def test_unchanged_path_and_ordinary_creation(self):
        for path, state, proposal in [
            ("unrelated.txt", actual("dirty formatting  \n"), "dirty formatting  \nmore\n"),
            ("unchanged.txt", actual("already different\n"), "proposal\n"),
            ("new.txt", None, "new UTF-8 é\n"),
            ("empty.txt", None, ""),
        ]:
            result = self.check(proposal, path=path, state=state)
            self.assertEqual(result, {"status": "preserved"})
        # Checkpointed creation is also selectable as a prefix of a later file.
        (self.repo / "created.txt").write_text("first\n")
        revision = self.capture_revision()
        result = self.check("first\nsecond\n", path="created.txt", state=actual("first\n"),
                            revision=revision)
        self.assertEqual(result["status"], "preserved", result)
        self.assertEqual(self.check("replacement\n", path="created.txt", state=actual("first\n"),
                                    revision=revision)["status"], "would-lose")

    def test_executable_mode_is_preserved_in_proposal(self):
        (self.repo / "note.txt").chmod(0o755)
        revision = self.capture_revision()
        result = self.check(self.current + "extra\n", state=actual(self.current, True),
                            revision=revision)
        self.assertEqual(result["status"], "preserved", result)
        # Losing the revision's executable-bit change is a lost baseline.
        self.assert_unusable(self.check(self.current, revision=revision,
                                           state=actual(self.current, False)))

    def test_changed_base_and_missing_id_are_unusable(self):
        self.assertEqual(self.check(self.current, revision="f" * 40),
                         {"status": "unusable", "reason": "revision is unavailable"})
        self.jj("commit", "-m", "changed base")
        result = self.check(self.current)
        self.assert_unusable(result)
        self.assertEqual(result["reason"], "working-copy parent changed")

    def test_unsupported_actual_proposal_and_revision_bytes(self):
        for state in [None,
                      actual(b"bad\x00binary"), actual(b"bad\xffutf8")]:
            self.assert_unusable(self.check(self.current, state=state))
        for proposal in [b"bad\x00binary", b"bad\xffutf8"]:
            self.assert_unusable(self.check(proposal))
        for content in [b"bad\x00binary", b"bad\xffutf8"]:
            (self.repo / "note.txt").write_bytes(content)
            revision = self.capture_revision()
            self.assert_unusable(self.check(self.current, revision=revision))

    def test_symlinks_and_other_parent_counts_are_unusable(self):
        (self.repo / "link").symlink_to("note.txt")
        revision = self.capture_revision()
        self.assert_unusable(self.check("regular\n", path="link", state=actual("regular\n"),
                                           revision=revision))
        self.jj("new", "root()", "-m", "another parent")
        other = self.jj("log", "--ignore-working-copy", "-r", "@", "--no-graph", "-T", "commit_id")
        self.jj("new", revision, other)
        merge = self.capture_revision()
        self.assert_unusable(self.check(self.current, revision=merge))
        self.assert_unusable(self.check(self.current, revision=revision))

    def test_newline_bytes_and_parent_kind_are_not_normalized(self):
        (self.repo / "created.txt").write_bytes(b"line without newline")
        revision = self.capture_revision()
        result = self.check("line without newline\n", path="created.txt",
                            state=actual("line without newline"), revision=revision)
        self.assertEqual(result["status"], "would-lose", result)
        (self.repo / "kind.txt").symlink_to("note.txt")
        self.jj("commit", "-m", "symlink parent")
        (self.repo / "kind.txt").unlink()
        (self.repo / "kind.txt").write_text("now regular\n")
        revision = self.capture_revision()
        self.assert_unusable(self.check("now regular\nmore\n", path="kind.txt",
                                           state=actual("now regular\n"), revision=revision))

    def test_invalid_parent_utf8_and_quoted_paths_are_unusable(self):
        # Git quotes this UTF-8 filename in canonical headers. The shared parser
        # does not support that encoding; it must not silently claim no diff.
        (self.repo / "é.txt").write_text("revision\n")
        revision = self.capture_revision()
        self.assert_unusable(self.check("replacement\n", path="é.txt",
                                           state=actual("revision\n"), revision=revision))
        (self.repo / "invalid.txt").write_bytes(b"invalid\xffparent")
        self.jj("commit", "-m", "malformed parent")
        (self.repo / "invalid.txt").write_text("regular now\n")
        revision = self.capture_revision()
        self.assert_unusable(self.check("regular now\nmore\n", path="invalid.txt",
                                           state=actual("regular now\n"), revision=revision))

    def test_protected_backend_scopes_inspection_to_read_children(self):
        # Exercise the existing proxy read contract without accessing a shared
        # repository: the shim validates caller flags, then runs native JJ in
        # this owned repo as the trusted executor would.
        real = shutil.which("jj")
        directory = self.root / "proxy-bin"
        directory.mkdir()
        log = self.root / "proxy-reads.jsonl"
        shim = directory / "jj"
        shim.write_text("#!/usr/bin/env python3\nimport json, os, sys\n"
                        "args = sys.argv[1:]\n"
                        "inspect = os.environ.get('JJ_PROXY_INSPECT')\n"
                        "assert '--ignore-working-copy' not in args\n"
                        f"with open({str(log)!r}, 'a') as f: f.write(json.dumps([inspect, args]) + '\\n')\n"
                        "if inspect == '1': args.insert(1, '--ignore-working-copy')\n"
                        f"os.execv({real!r}, [{real!r}, *args])\n")
        shim.chmod(0o755)
        helper = self.root / "route.py"
        route = {"backend": "proxy", "workspace": str(self.repo), "destination": str(self.repo),
                 "command": ["split"], "hooks": False}
        helper.write_text(f"print({json.dumps(route)!r})\n")
        self.env.update(PATH=str(directory) + os.pathsep + self.env["PATH"],
                        SANDBOX_PROXY_DIR=str(self.root), JJ_ROUTE_HELPER=str(helper))
        result = self.check(self.current)
        self.assertEqual(result["status"], "preserved", result)
        commands = [json.loads(line) for line in log.read_text().splitlines()]
        self.assertFalse(any(args[0] == "status" for _, args in commands))
        for inspect, args in commands:
            self.assertEqual(inspect, "1")

    def test_repository_subdirectory_and_nonrepo_check(self):
        subdirectory = self.repo / "subdirectory"
        subdirectory.mkdir()
        result = self.check(self.current, cwd=subdirectory)
        self.assertEqual(result["status"], "preserved", result)
        result = self.check(self.current, cwd=self.root)
        self.assert_unusable(result)

    @unittest.skipUnless(os.name == "posix" and Path("/proc").is_dir(), "requires Linux process inspection")
    def test_termination_stops_checker_children_without_a_reply_or_write(self):
        directory = self.root / "slow-bin"
        directory.mkdir()
        marker = self.root / "children.json"
        git = directory / "git"
        git.write_text("#!/usr/bin/env python3\nimport json, os, subprocess\n"
                       "child = subprocess.Popen(['sleep', '60'])\n"
                       f"with open({str(marker)!r}, 'w') as f: json.dump([os.getpid(), child.pid], f)\n"
                       "child.wait()\n")
        git.chmod(0o755)
        self.env["PATH"] = str(directory) + os.pathsep + self.env["PATH"]
        self.env["TMPDIR"] = str(self.root)
        process = subprocess.Popen([str(CLI), "agent-split", "--check-file"], cwd=self.repo,
                                   env=self.env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, text=True)
        try:
            request = {"revision": self.revision, "path": "note.txt",
                       "actual": actual(self.current), "proposed": encoded("replacement\n")}
            process.stdin.write(json.dumps(request))
            process.stdin.close()
            deadline = time.monotonic() + 5
            while not marker.exists() and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertTrue(marker.exists(), "checker never reached the paused diff subprocess")
            pids = json.loads(marker.read_text())
            process.terminate()
            process.wait(timeout=5)
            self.assertNotEqual(process.returncode, 0)
            self.assertEqual(process.stdout.read(), "")
            self.assertEqual((self.repo / "note.txt").read_text(), self.current)
            def alive(pid):
                stat = Path(f"/proc/{pid}/stat")
                try:
                    return stat.read_text().split(") ", 1)[1][0] != "Z"
                except FileNotFoundError:
                    return False
            deadline = time.monotonic() + 5
            while any(alive(pid) for pid in pids) and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertFalse(any(alive(pid) for pid in pids), "checker left a running subprocess")
            self.assertEqual(list(self.root.glob("agent-split-check*")), [])
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
            process.stdout.close()
            process.stderr.close()

    def assert_process_failure(self, raw):
        result = subprocess.run([str(CLI), "agent-split", "--check-file"], cwd=self.repo,
                                env=self.env, input=raw, capture_output=True, text=True, timeout=30)
        self.assertNotEqual(result.returncode, 0, result)
        self.assertEqual(result.stdout, "")
        self.assertTrue(result.stderr)
        return result

    def test_malformed_request_and_unexpected_checker_failure(self):
        request = {"revision": self.revision, "path": "note.txt",
                   "actual": actual(self.current), "proposed": encoded(self.current)}
        for raw in ["{} {}", "[]", "{malformed", "{}", ""]:
            self.assert_process_failure(raw)
        for field, value in [("revision", "@"), ("revision", None),
                             ("actual", {"kind": "file"}),
                             ("actual", {"content": encoded("ok"), "executable": 1}),
                             ("proposed", "!bad!"), ("proposed", None),
                             ("path", "../outside"), ("path", "/absolute"),
                             ("path", "./note.txt"), ("path", "nested/../note.txt"),
                             ("path", "")]:
            with self.subTest(field=field, value=value):
                self.assert_process_failure(json.dumps({**request, field: value}))
        self.assert_process_failure(json.dumps({**request, "checkpoint": {}}))
        # Infrastructure failures must never masquerade as semantic skips.
        directory = self.root / "broken-bin"
        directory.mkdir()
        git = directory / "git"
        git.write_text("#!/bin/sh\necho 'injected diff failure' >&2\nexit 9\n")
        git.chmod(0o755)
        self.env["PATH"] = str(directory) + os.pathsep + self.env["PATH"]
        result = self.assert_process_failure(json.dumps(request))
        self.assertIn("injected diff failure", result.stderr)
        jj = directory / "jj"
        jj.write_text("#!/bin/sh\necho 'injected read failure' >&2\nexit 9\n")
        jj.chmod(0o755)
        result = self.assert_process_failure(json.dumps(request))
        self.assertIn("injected read failure", result.stderr)


if __name__ == "__main__":
    unittest.main()
