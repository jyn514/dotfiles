#!/usr/bin/env python3
"""Fixture-preparation CLI tests; this file also acts as the fake jj executable."""

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest

PREPARE = Path(__file__).with_name("unavailable_issue") / "prepare.py"


def fake_jj() -> int:
    args = sys.argv[1:]
    case = os.environ.get("FIXTURE_CASE", "success")
    if args[:2] == ["file", "list"]:
        if case == "list-failure":
            sys.stdout.buffer.write(b"partial output")
            print("listing denied", file=sys.stderr)
            return 7
        if case == "traversal":
            sys.stdout.buffer.write(b"../outside\0file\0false\0")
        elif case == "absolute":
            sys.stdout.buffer.write(b"/outside\0file\0false\0")
        elif case == "duplicate":
            sys.stdout.buffer.write(b"x\0file\0false\0x\0file\0false\0")
        elif case == "collision":
            sys.stdout.buffer.write(b"x\0file\0false\0x/y\0file\0false\0")
        elif case == "framing":
            sys.stdout.buffer.write(b"x\0file\0false")
        else:
            if args[-2] != "-T" or "path.display()" not in args[-1]:
                return 9
            sys.stdout.buffer.write(
                b"binary.dat\0file\0false\0bin/run\0file\0true\0odd!.md\0file\0false\0"
                b".claude/skills\0symlink\0false\0"
                b"other excluded\0git-submodule\0false\0"
            )
        return 0
    if args[:2] == ["file", "show"]:
        path = json.loads(args[-1].removeprefix("root:"))
        if case == "show-failure" and path == "binary.dat":
            sys.stdout.buffer.write(b"failed file bytes must never publish")
            print("export denied", file=sys.stderr)
            return 8
        payloads = {"binary.dat": bytes(range(256)) + b"\x00\xff\r\n", "bin/run": b"#!/bin/sh\nexit 0\n", "odd!.md": b"literal fileset punctuation"}
        if path not in payloads:
            print("attempted to show a nonregular entry", file=sys.stderr)
            return 10
        sys.stdout.buffer.write(payloads[path])
        return 0
    return 11


class FixturePreparationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.repository = self.root / "repository"
        self.repository.mkdir()
        self.bin = self.root / "bin"
        self.bin.mkdir()
        fake = self.bin / "jj"
        shutil.copyfile(__file__, fake)
        fake.chmod(0o755)
        self.output = self.root / "output"

    def run_prepare(self, case: str = "success") -> subprocess.CompletedProcess:
        environment = dict(os.environ, PATH=f"{self.bin}{os.pathsep}{os.environ['PATH']}", FIXTURE_CASE=case)
        return subprocess.run(
            [sys.executable, str(PREPARE), "--repository", str(self.repository), "--output", str(self.output)],
            env=environment, capture_output=True, text=True, check=False,
        )

    def test_binary_modes_exclusions_and_self_contained_data(self) -> None:
        result = self.run_prepare()
        self.assertEqual(result.returncode, 0, result.stderr)
        shutil.rmtree(self.repository)
        manifest = json.loads((self.output / "manifest.json").read_text())
        archive_bytes = (self.output / "flower.tar").read_bytes()
        self.assertEqual(manifest["archive"]["sha256"], hashlib.sha256(archive_bytes).hexdigest())
        self.assertEqual(manifest["snapshot_kind"], "tracked regular-file snapshot")
        self.assertEqual(manifest["excluded_paths"], [
            {"path": ".claude/skills", "type": "symlink"},
            {"path": "other excluded", "type": "git-submodule"},
        ])
        with tarfile.open(self.output / "flower.tar") as archive:
            self.assertEqual(archive.getnames(), ["flower/bin/run", "flower/binary.dat", "flower/odd!.md"])
            self.assertTrue(all(member.isfile() for member in archive))
            self.assertEqual(archive.getmember("flower/bin/run").mode, 0o755)
            self.assertEqual(archive.getmember("flower/binary.dat").mode, 0o644)
            self.assertEqual(archive.extractfile("flower/binary.dat").read(), bytes(range(256)) + b"\x00\xff\r\n")
            for record in manifest["files"]:
                member = archive.getmember("flower/" + record["path"])
                self.assertEqual(record["mode"], member.mode)
                self.assertEqual(record["sha256"], hashlib.sha256(archive.extractfile(member).read()).hexdigest())
        for name, digest in manifest["data_files"].items():
            self.assertEqual(hashlib.sha256((self.output / "data" / name).read_bytes()).hexdigest(), digest)
        self.assertEqual(set(manifest["data_files"]), {"issue.md", "packet.md", "worker-skill.md", "provenance.json"})

    def test_failed_commands_do_not_publish_or_leave_staging(self) -> None:
        for case, diagnostic in [("list-failure", "listing denied"), ("show-failure", "export denied")]:
            with self.subTest(case=case):
                result = self.run_prepare(case)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(diagnostic, result.stderr)
                self.assertFalse(self.output.exists())
                self.assertEqual(sorted(path.name for path in self.root.iterdir()), ["bin", "repository"])

    def test_rejects_traversal_and_malformed_lists_before_publication(self) -> None:
        for case in ["traversal", "absolute", "duplicate", "collision", "framing"]:
            with self.subTest(case=case):
                result = self.run_prepare(case)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(self.output.exists())
                self.assertFalse((self.root / "outside").exists())

    def test_existing_output_is_never_replaced(self) -> None:
        self.output.mkdir()
        marker = self.output / "owned"
        marker.write_bytes(b"keep")
        result = self.run_prepare()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(marker.read_bytes(), b"keep")
        self.assertEqual(list(self.output.iterdir()), [marker])

    def test_archive_is_repeatable(self) -> None:
        first = self.run_prepare()
        self.assertEqual(first.returncode, 0, first.stderr)
        first_archive = (self.output / "flower.tar").read_bytes()
        self.output = self.root / "second"
        second = self.run_prepare()
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual((self.output / "flower.tar").read_bytes(), first_archive)


if __name__ == "__main__":
    if Path(sys.argv[0]).name == "jj":
        sys.exit(fake_jj())
    unittest.main()
