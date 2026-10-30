from __future__ import annotations

import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from urllib.parse import quote_from_bytes


ROOT = Path(__file__).resolve().parents[3]


class LiteralResourceTests(unittest.TestCase):
    def test_selected_filename_stays_literal_at_the_native_tree_lookup(self) -> None:
        names = (
            "ordinary.rs", "literal space; dollar$.rs", "literal*.rs", "literal[ab].rs",
            ":(glob)*", ":(exclude)name", ":(literal)name",
        )
        selectors = (
            {},
            {"GIT_LITERAL_PATHSPECS": "0"},
            {"GIT_LITERAL_PATHSPECS": "1"},
            {"GIT_GLOB_PATHSPECS": "1"},
            {"GIT_NOGLOB_PATHSPECS": "1"},
            {"GIT_ICASE_PATHSPECS": "1"},
            {"GIT_GLOB_PATHSPECS": "1", "GIT_ICASE_PATHSPECS": "1"},
            {"GIT_NOGLOB_PATHSPECS": "1", "GIT_ICASE_PATHSPECS": "1"},
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repository = root / "checkout"
            repository.mkdir()
            # Setup uses only owned repositories/configuration. Selectors enter
            # only the production CLI, never native fixture construction.
            environment = {
                key: value for key, value in os.environ.items()
                if not key.startswith("GIT_")
            } | {
                "HOME": str(root / "home"), "XDG_CONFIG_HOME": str(root / "config"),
                "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
                "GIT_AUTHOR_NAME": "Fixture", "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
                "GIT_COMMITTER_NAME": "Fixture", "GIT_COMMITTER_EMAIL": "fixture@example.invalid",
            }

            def git(*arguments: str) -> bytes:
                return subprocess.check_output(
                    ["git", *arguments], cwd=repository, env=environment, stderr=subprocess.PIPE,
                )

            git("init", "-q", "-b", "main")
            git("commit", "--allow-empty", "-qm", "base")
            for index, name in enumerate(names):
                source = repository / name
                source.write_bytes(f"prefix\nneedle-{index}\n".encode())
                git("--literal-pathspecs", "add", "--", name)
            git("commit", "-qm", "selected source files")
            revision = git("rev-parse", "HEAD").strip()
            git("remote", "add", "origin", "https://github.com/fixture/selected.git")
            git("update-ref", "refs/remotes/origin/main", revision.decode())
            git("symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main")
            for index, name in enumerate(names):
                self.assertEqual(f"prefix\nneedle-{index}\n".encode(), git("show", revision.decode() + ":" + name))
                (repository / name).write_bytes(f"needle-{index}\n".encode())
            missing = "only-local.rs"
            (repository / missing).write_bytes(b"not in upstream\n")
            wrappers = root / "bin"
            wrappers.mkdir()
            opened = root / "opened-url"
            opener = wrappers / "xdg-open"
            opener.write_text('#!/bin/sh\nprintf "%s\\n" "$1" > "$OPENED_URL"\n')
            opener.chmod(0o755)
            refs_before = git("show-ref", "--head")
            for selector in selectors:
                for name in (*names, missing):
                    with self.subTest(selector=selector, filename=name):
                        opened.unlink(missing_ok=True)
                        result = subprocess.run(
                            [str(ROOT / "bin/remote-git-url"), str(repository / name), "1"],
                            cwd=repository,
                            env=environment | selector | {
                                "PATH": str(wrappers) + os.pathsep + os.environ["PATH"],
                                "DISPLAY": ":disposable-opener", "OPENED_URL": str(opened),
                            },
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
                        )
                        absent = name == missing
                        self.assertEqual(1 if absent else 0, result.returncode, result.stderr)
                        expected_revision = b"HEAD" if absent else revision
                        expected_line = b"1" if absent else b"2"
                        self.assertEqual(
                            b"https://github.com/fixture/selected/blob/" + expected_revision + b"/"
                            + quote_from_bytes(os.fsencode(name), safe="/").encode()
                            + b"#L" + expected_line + b"\n",
                            opened.read_bytes(),
                        )
                        self.assertEqual(b"", result.stdout)
                        if absent:
                            self.assertIn(b"does not exist in upstream", result.stderr)
                        else:
                            self.assertEqual(b"", result.stderr)
            self.assertEqual(refs_before, git("show-ref", "--head"))


if __name__ == "__main__":
    unittest.main()
