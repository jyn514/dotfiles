"""Real disposable-repository consumers of the numbered-hunk CLI."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[3]
CLI = ROOT / "libexec/agent-wrappers/bb"


@unittest.skipUnless(all(shutil.which(tool) for tool in ("bb", "jj", "git")),
                     "requires bb, jj and git")
class NumberedHunksTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="numbered-hunks-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.env = dict(os.environ, BB_SOURCE_ROOT=str(ROOT))
        self.jj("git", "init", "--colocate")
        self.jj("config", "set", "--repo", "user.name", "Hunk test")
        self.jj("config", "set", "--repo", "user.email", "hunks@example.invalid")
        self.put(".gitignore", "target/\n")
        self.base = "".join(f"line {n}\n" for n in range(30))
        self.paths = ["a.txt", "b space [*].txt"]
        for path in self.paths:
            self.put(path, self.base)
        self.jj("commit", "-m", "base")
        self.current = self.base.replace("line 2\n", "FIRST\n").replace("line 25\n", "LAST\n")
        for path in self.paths:
            self.put(path, self.current)

    def put(self, path, text):
        (self.repo / path).write_text(text)

    def command(self, argv, *, ok=True, input=None):
        result = subprocess.run(argv, cwd=self.repo, env=self.env, input=input,
                                text=True, capture_output=True, timeout=40)
        if ok:
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        return result

    def jj(self, *args):
        return self.command(["jj", *args]).stdout.strip()

    def cli(self, *args, **kwargs):
        return self.command([str(CLI), "agent-split", *args], **kwargs)

    def catalog(self, *args):
        result = self.cli("list", "--json", *args)
        self.assertEqual("", result.stderr)
        return json.loads(result.stdout)

    def split(self, source, ids="1,4", *args, ok=True):
        return self.cli("--from", source, "--hunks", ids, "-m", "selected", "--json", *args, ok=ok)

    def tree(self, rev):
        commit = self.jj("log", "--ignore-working-copy", "-r", rev, "--no-graph", "-T", "commit_id")
        paths = self.command(["git", "ls-tree", "-rz", "--name-only", commit]).stdout.split("\0")
        return {p: self.command(["git", "show", f"{commit}:{p}"]).stdout for p in paths if p}

    def assert_split_trees(self, result, selected):
        ids = json.loads(result.stdout)
        expected = dict(self.tree("@--"), **selected)
        self.assertEqual(expected, self.tree(ids["selected"]))
        self.assertEqual(self.original_tree, self.tree(ids["remaining"]))
        self.assertEqual({"selected", "remaining"}, set(ids))

    def test_first_consumer_two_files_four_hunks(self):
        catalog = self.catalog()
        self.assertEqual([1, 2, 3, 4], [h["id"] for h in catalog["hunks"]])
        self.assertNotIn("parent", catalog)
        self.assertRegex(catalog["source_commit"], r"^[0-9a-f]{40}$")
        self.assertEqual([], catalog["unsupported"])
        self.assertEqual({"start": 1, "count": 6}, catalog["hunks"][0]["parent_range"])
        self.assertEqual({"start": 1, "count": 6}, catalog["hunks"][0]["source_range"])
        self.original_tree = self.tree("@")
        result = self.split(catalog["source_commit"], "4,1", "-m", "second paragraph",
                            "--remaining-message", "remainder")
        self.assert_split_trees(result, {
            self.paths[0]: self.base.replace("line 2\n", "FIRST\n"),
            self.paths[1]: self.base.replace("line 25\n", "LAST\n"),
        })
        self.assertEqual("selected\n\nsecond paragraph", self.jj("log", "-r", "@-", "--no-graph", "-T", "description"))
        self.assertEqual("remainder", self.jj("log", "-r", "@", "--no-graph", "-T", "description"))
        if destination := os.environ.get("AGENT_SPLIT_EVIDENCE"):
            destination = Path(destination)
            destination.mkdir(parents=True, exist_ok=True)
            ids = json.loads(result.stdout)
            (destination / "first-consumer.json").write_text(json.dumps({
                "catalog": catalog, "result": ids, "stderr": result.stderr,
                "input_tree": self.original_tree,
                "selected_tree": self.tree(ids["selected"]),
                "remaining_tree": self.tree(ids["remaining"]),
                "jj": self.jj("--version"),
                "git": self.command(["git", "--version"]).stdout.strip(),
            }, indent=2) + "\n")

    def test_snapshot_counts_and_immutable_inspection(self):
        directory = self.root / "bin"
        directory.mkdir()
        log = self.root / "calls.jsonl"
        real = shutil.which("jj")
        shim = directory / "jj"
        shim.write_text("#!/usr/bin/env python3\nimport json, os, sys\n"
                        f"with open({str(log)!r}, 'a') as f: f.write(json.dumps(sys.argv[1:]) + '\\n')\n"
                        f"os.execv({real!r}, [{real!r}, *sys.argv[1:]])\n")
        shim.chmod(0o755)
        self.env["PATH"] = str(directory) + os.pathsep + self.env["PATH"]
        source = self.catalog()["source_commit"]
        self.assertFalse((self.repo / "target").exists())
        requests = lambda: [json.loads(line) for line in log.read_text().splitlines()]
        self.assertEqual(1, sum(args[0] == "status" for args in requests()))
        log.write_text("")
        self.catalog(source)
        self.assertFalse(any(args[0] == "status" for args in requests()))
        self.assertTrue(all("--ignore-working-copy" in args for args in requests()))
        log.write_text("")
        self.split(source, "1-2")
        self.assertEqual(1, sum(args[0] == "status" for args in requests()))
        self.assertFalse(list((self.repo / "target/jj-split").glob("hunks-*")))

    def test_ranges_filters_unicode_and_option_termination(self):
        self.put("é.txt", self.base)
        self.jj("commit", "-m", "unicode base")
        self.put("é.txt", self.current)
        catalog = self.catalog("--path", "é.txt", "--path", "é.txt", "--", "@")
        self.assertEqual([1, 2], [h["id"] for h in catalog["hunks"]])
        self.original_tree = self.tree("@")
        self.assert_split_trees(self.cli("--from", catalog["source_commit"], "--hunks", "01-02",
                                        "-m", "--json", "--json", "--", "@"), {"é.txt": self.current})
        self.assertEqual("--json", self.jj("log", "-r", "@-", "--no-graph", "-T", "description"))

    def test_legacy_patch_named_list_is_addressable(self):
        source = self.catalog()["source_commit"]
        # Existing legacy artifact safety still applies to ./list outside target.
        (self.repo / "list").write_text("diff --git a/a.txt b/a.txt\n--- a/a.txt\n+++ b/a.txt\n"
                                        + self.catalog(source)["hunks"][0]["text"])
        result = self.cli("./list", "-m", "legacy", ok=False)
        self.assertEqual(1, result.returncode)
        self.assertIn("snapshot safety", result.stderr)
        self.assertNotIn("--path", result.stderr)

    def test_filters_and_configuration_do_not_renumber(self):
        catalog = self.catalog()
        source = catalog["source_commit"]
        filtered = self.catalog("--path", self.paths[1], source)
        self.assertEqual([3, 4], [h["id"] for h in filtered["hunks"]])
        home = self.root / "gitconfig"
        attributes = self.root / "hostile-attributes"
        attributes.write_text("* binary\n")
        home.write_text('[diff]\n algorithm = histogram\n context = 20\n interHunkContext = 30\n indentHeuristic = true\n colorMoved = zebra\n suppressBlankEmpty = true\n outputIndicatorNew = N\n outputIndicatorOld = O\n outputIndicatorContext = C\n[core]\n quotePath = true\n')
        self.env["GIT_CONFIG_GLOBAL"] = str(home)
        self.env["GIT_EXTERNAL_DIFF"] = "/nonexistent-hostile-diff"
        self.env["GIT_DIFF_OPTS"] = "-U100"
        self.env["GIT_CONFIG_COUNT"] = "1"
        self.env["GIT_CONFIG_KEY_0"] = "core.attributesFile"
        self.env["GIT_CONFIG_VALUE_0"] = str(attributes)
        self.assertEqual(catalog, self.catalog(source))
        text = self.cli("list", "--path", self.paths[1], source).stdout
        self.assertIn("[hunk 3]", text)
        self.assertNotIn("[hunk 1]", text)
        for hunk in filtered["hunks"]:
            self.assertIn(hunk["text"], text)
        self.original_tree = self.tree("@")
        self.assert_split_trees(self.split(source), {
            self.paths[0]: self.base.replace("line 2\n", "FIRST\n"),
            self.paths[1]: self.base.replace("line 25\n", "LAST\n"),
        })

    def test_invalid_inputs_do_not_split(self):
        catalog = self.catalog()
        source = catalog["source_commit"]
        before = self.tree("@")
        for ids in ("0", "5", "", "1,", "2-1", "1,1", "1-3,3", "1,,4", "1-999999999999999999999999"):
            result = self.split(source, ids, ok=False)
            self.assertEqual(1, result.returncode, (ids, result))
        for invalid in ("@", source[:12], catalog["source_change"]):
            self.assertEqual(1, self.split(invalid, ok=False).returncode)
        for args in (("--from", source, "-m", "x"), ("--hunks", "1", "-m", "x"),
                     ("--from", source, "--hunks", "1", "patch", "-m", "x"),
                     ("list", "--path", "../outside"), ("list", "--path", "missing")):
            self.assertEqual(1, self.cli(*args, ok=False).returncode, args)
        self.assertEqual(before, self.tree("@"))

    def test_unselected_new_edits_preserve_original_selected_bytes(self):
        catalog = self.catalog()
        # New earlier unselected lines shift later offsets. Selection still uses
        # the inspected hunk, not the latest numbering or latest bytes.
        self.put(self.paths[0], "new unselected\n" + self.current)
        self.jj("status")
        self.original_tree = self.tree("@")
        self.assert_split_trees(self.split(catalog["source_commit"], "2"), {
            self.paths[0]: self.base.replace("line 25\n", "LAST\n")})

    def test_changed_selected_source_is_refused(self):
        catalog = self.catalog()
        self.put(self.paths[0], self.current.replace("FIRST", "DIFFERENT"))
        self.jj("status")
        before = self.tree("@")
        result = self.split(catalog["source_commit"], "1", ok=False)
        self.assertEqual(1, result.returncode, result)
        self.assertIn("not contained", result.stderr)
        self.assertEqual(before, self.tree("@"))

    def test_committed_and_rebased_targets_need_new_listing(self):
        catalog = self.catalog()
        self.jj("commit", "-m", "committed")
        result = self.split(catalog["source_commit"], ok=False)
        self.assertEqual(1, result.returncode)
        self.assertIn("list the target again", result.stderr)
        self.assertIn("Preflight target: @", result.stderr)
        self.assertIn("Resolved commit:", result.stderr)
        self.assertIn("No split was run.", result.stderr)
        self.jj("new", "@--", "-m", "new parent")
        self.put("parent.txt", "other parent\n")
        self.jj("rebase", "-r", catalog["source_change"], "-d", "@")
        result = self.split(catalog["source_commit"], "1", catalog["source_change"], ok=False)
        self.assertEqual(1, result.returncode)
        self.assertIn("list the target again", result.stderr)

    def test_unsupported_operations_are_visible(self):
        self.put("added.txt", "new\n")
        (self.repo / self.paths[0]).unlink()
        (self.repo / self.paths[1]).chmod(0o755)
        self.jj("status")
        catalog = self.catalog()
        self.assertEqual([], catalog["hunks"])
        self.assertEqual({self.paths[0]: "deletion", self.paths[1]: "mode-change", "added.txt": "creation"},
                         {u["path"]: u["kind"] for u in catalog["unsupported"]})
        self.assertEqual(1, self.split(catalog["source_commit"], "1", ok=False).returncode)

    def test_binary_kind_rename_and_quoted_path_operations_are_visible(self):
        (self.repo / "binary").write_bytes(b"old\0bytes")
        (self.repo / "invalid-utf8").write_bytes(b"old\xffbytes")
        for path in ('quote"name', "tab\tname", "line\nname", "slash\\name"):
            self.put(path, self.base)
        self.put("old-name", "unchanged rename bytes\n")
        self.put("kind", "regular\n")
        self.jj("commit", "-m", "operation base")
        (self.repo / "binary").write_bytes(b"new\0bytes")
        (self.repo / "invalid-utf8").write_bytes(b"new\xffbytes")
        for path in ('quote"name', "tab\tname", "line\nname", "slash\\name"):
            self.put(path, self.current)
        (self.repo / "old-name").rename(self.repo / "new-name")
        (self.repo / "kind").unlink()
        (self.repo / "kind").symlink_to("a.txt")
        catalog = self.catalog()
        self.assertEqual([], catalog["hunks"])
        self.assertEqual({"binary": "binary", "invalid-utf8": "binary", 'quote"name': "path-encoding",
                          "kind": "kind-change", "old-name": "deletion", "new-name": "creation",
                          "tab\tname": "path-encoding", "line\nname": "path-encoding", "slash\\name": "path-encoding"},
                         {u["path"]: u["kind"] for u in catalog["unsupported"]})

    def test_empty_revision_omits_unchanged_newline_symlinks_but_lists_changes(self):
        paths = ("unchanged\nlink", "unchanged\rlink", "\n", 'quoted"link')
        for path in paths:
            (self.repo / path).symlink_to("a.txt")
        self.jj("commit", "-m", "symlink base")
        empty = self.catalog()
        self.assertEqual([], empty["hunks"])
        self.assertEqual([], empty["unsupported"])

        for path in paths:
            (self.repo / path).unlink()
            (self.repo / path).symlink_to(self.paths[1])
        changed = self.catalog()
        self.assertEqual([], changed["hunks"])
        self.assertEqual({path: "non-regular" for path in paths},
                         {u["path"]: u["kind"] for u in changed["unsupported"]})
        self.assertEqual(1, self.split(changed["source_commit"], "1", ok=False).returncode)

    def test_repeated_lines_and_grouped_overlapping_context(self):
        base = "same\nold\nsame\n" + "padding\n" * 16 + "same\nold\nsame\n"
        self.put("repeated", base)
        self.jj("commit", "-m", "repeat base")
        self.put("repeated", base.replace("old", "first", 1).rsplit("old", 1)[0] + "second\nsame\n")
        catalog = self.catalog()
        self.assertEqual(2, len(catalog["hunks"]))
        self.original_tree = self.tree("@")
        expected = base.rsplit("old", 1)[0] + "second\nsame\n"
        self.assert_split_trees(self.split(catalog["source_commit"], "2"), {"repeated": expected})
        # Two nearby edits are intentionally a single selectable hunk.
        self.jj("commit", "-m", "grouped base")
        content = self.tree("@")["a.txt"]
        self.put("a.txt", content.replace("line 5", "near A").replace("line 8", "near B"))
        grouped = self.catalog()
        self.assertEqual(1, len(grouped["hunks"]))
        self.assertIn("+near A\n", grouped["hunks"][0]["text"])
        self.assertIn("+near B\n", grouped["hunks"][0]["text"])
        self.jj("status")
        self.original_tree = self.tree("@")
        self.assert_split_trees(self.split(grouped["source_commit"], "1"), {
            "a.txt": content.replace("line 5", "near A").replace("line 8", "near B")})

    def test_empty_catalog(self):
        empty = self.catalog("@-")
        # Base adds files and is unsupported, root's empty child is truly empty.
        self.jj("new", "@-", "-m", "empty")
        empty = self.catalog()
        self.assertEqual([], empty["hunks"])
        self.assertEqual([], empty["unsupported"])
        self.assertEqual(1, self.split(empty["source_commit"], "1", ok=False).returncode)

    def test_missing_newline_and_earlier_line_count_change(self):
        for path in self.paths:
            self.put(path, self.base.rstrip("\n"))
        self.jj("commit", "-m", "no newline base")
        self.put(self.paths[0], "inserted\n" + self.base.rstrip("\n").replace("line 29", "last changed"))
        catalog = self.catalog()
        self.assertEqual(2, len(catalog["hunks"]))
        self.assertIn("\\ No newline at end of file\n", catalog["hunks"][1]["text"])
        self.original_tree = self.tree("@")
        self.assert_split_trees(self.split(catalog["source_commit"], "2"), {
            self.paths[0]: self.base.rstrip("\n").replace("line 29", "last changed")})


if __name__ == "__main__":
    unittest.main()
