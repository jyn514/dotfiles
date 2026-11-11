"""Exercise jj c against disposable repositories, including real squash/rebase behavior."""

import json
import os
from pathlib import Path
import subprocess
import tempfile
import tomllib
import unittest


ROOT = Path(__file__).resolve().parents[2]
CONFIG = tomllib.loads((ROOT / "config/jj.toml").read_text())


class PrivateCommitTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="jj-private-commit-")
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.repo = self.directory / "repo"
        self.config = self.directory / "config.toml"
        # Use the installed alias definition, not a duplicate of its command.
        self.config.write_text(
            '[user]\nname = "Test"\nemail = "test@example.org"\n'
            '[git]\nprivate-commits = \'description("secret:*")\'\n'
            '[aliases]\nc = ' + json.dumps(CONFIG["aliases"]["c"]) + "\n"
        )
        self.env = {
            **os.environ,
            "JJ_CONFIG": str(self.config),
            "PATH": str(ROOT / "bin") + os.pathsep + os.environ["PATH"],
            "JJ_EDITOR": "false",
        }
        self.jj("git", "init", "--no-colocate", str(self.repo), cwd=self.directory)
        self.write("base", "base\n")
        self.jj("commit", "-m", "base")
        self.base = self.rev("@-")
        self.jj("bookmark", "create", "dev", "-r", self.base)

    def jj(self, *args, cwd=None, check=True):
        result = subprocess.run(
            ["jj", "--no-pager", *args], cwd=cwd or self.repo,
            env=self.env, text=True, capture_output=True,
        )
        if check:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def write(self, path, contents):
        (self.repo / path).write_text(contents)

    def rev(self, expression, template="commit_id"):
        return self.jj("log", "--no-graph", "-r", expression, "-T", template).stdout.strip()

    def private_stack(self):
        self.write("private", "private setting\n")
        self.jj("commit", "-m", "secret: local settings")
        return self.rev("@-", "change_id")

    def assert_public_commit(self, subject="public change"):
        public = self.rev(f'description(exact:"{subject}\\n")')
        self.assertTrue(public)
        self.assertEqual(self.rev(f"{public}-"), self.base)
        self.assertEqual(self.rev(f"{public} & description(\"secret:*\")::"), "")
        self.assertEqual(self.rev("@", "empty"), "true")
        self.assertEqual(self.jj("file", "show", "-r", public, "public").stdout, "public edit\n")
        self.assertEqual(self.jj("file", "show", "private").stdout, "private setting\n")
        self.assertEqual(self.rev("dev"), self.base)
        return public

    def test_linear_stack_keeps_private_changes_and_working_copy(self):
        private = self.private_stack()
        working = self.rev("@", "change_id")
        self.write("public", "public edit\n")
        self.jj("c", "-m", "public change")
        public = self.assert_public_commit()
        self.assertEqual(self.rev("@", "change_id"), working)
        self.assertEqual(self.rev("@-", "change_id"), private)
        self.assertEqual(self.rev(f"{private}-"), public)
        # Repeating the command selects the new public head, not the bookmark.
        self.write("next", "next edit\n")
        self.jj("c", "-m", "next public change")
        self.assertEqual(self.rev('description(exact:"next public change\\n")-'), public)
        self.assertEqual(self.rev("@", "empty"), "true")

    def test_merge_working_copy_keeps_both_parents(self):
        private = self.private_stack()
        self.jj("new", self.base)
        self.write("branch", "public branch\n")
        self.jj("commit", "-m", "public branch")
        public_parent = self.rev("@-")
        self.jj("bookmark", "set", "dev", "-r", public_parent)
        self.jj("new", "dev", private)
        original_private = self.rev(private)
        self.write("public", "public edit\n")
        self.jj("c", "-m", "public change")
        public = self.rev('description(exact:"public change\\n")')
        self.assertEqual(self.rev(f"{public}-"), public_parent)
        self.assertEqual(set(self.rev("@-", 'commit_id ++ "\\n"').splitlines()),
                         {public, original_private})
        self.assertEqual(self.rev(f"{public} & {private}::"), "")
        self.assertEqual(self.jj("file", "show", "private").stdout, "private setting\n")
        self.assertEqual(self.rev("@", "empty"), "true")
        self.assertEqual(self.rev("dev"), public_parent)

    def test_nonprivate_descendant_of_private_is_not_a_public_destination(self):
        private = self.private_stack()
        self.write("intermediate", "not marked private, but depends on it\n")
        self.jj("commit", "-m", "intermediate")
        self.write("public", "public edit\n")
        self.jj("c", "-m", "public change")
        public = self.assert_public_commit()
        self.assertEqual(self.rev(f"{private}-"), public)

    def ambiguous_stack(self):
        self.write("left", "left\n")
        self.jj("commit", "-m", "left branch")
        left = self.rev("@-")
        self.jj("new", self.base)
        self.write("right", "right\n")
        self.jj("commit", "-m", "right branch")
        right = self.rev("@-")
        self.jj("new", left, right)
        self.write("public", "public edit\n")
        return left, right

    def operation(self):
        self.jj("status")
        return self.jj("op", "log", "--no-graph", "-n", "1", "-T", "id").stdout

    def test_multiple_public_heads_fail_with_candidates_without_rewriting(self):
        self.ambiguous_stack()
        operation = self.operation()
        result = self.jj("c", "-m", "public change", check=False)
        self.assertEqual(result.returncode, 2)
        self.assertIn("multiple public heads", result.stderr)
        self.assertIn("left branch", result.stderr)
        self.assertIn("right branch", result.stderr)
        self.assertIn("--into", result.stderr)
        self.assertEqual(self.operation(), operation)

    def test_explicit_public_head_resolves_ambiguity(self):
        left, right = self.ambiguous_stack()
        self.jj("c", "--into", left, "-m", "public change")
        public = self.rev('description(exact:"public change\\n")')
        self.assertEqual(self.rev(f"{public}-"), left)
        self.assertEqual(set(self.rev("@-", 'commit_id ++ "\\n"').splitlines()), {public, right})

    def test_no_eligible_head_fails_without_rewriting(self):
        self.config.write_text(self.config.read_text().replace(
            'private-commits = \'description("secret:*")\'', 'private-commits = "all()"'))
        operation = self.operation()
        result = self.jj("c", "-m", "public change", check=False)
        self.assertEqual(result.returncode, 2)
        self.assertIn("no eligible public destination", result.stderr)
        self.assertEqual(self.operation(), operation)

    def test_explicit_private_target_is_rejected(self):
        private = self.private_stack()
        operation = self.operation()
        result = self.jj("c", "--into", private, "-m", "no", check=False)
        self.assertEqual(result.returncode, 2)
        self.assertIn("no eligible public destination", result.stderr)
        self.assertEqual(self.operation(), operation)

    def test_paths_and_message_forms_pass_through(self):
        self.private_stack()
        self.write("public", "public edit\n")
        self.write("remaining", "keep working\n")
        self.jj("c", "--message=public change", "--", "public")
        public = self.rev('description(exact:"public change\\n")')
        self.assertEqual(self.jj("file", "show", "-r", public, "public").stdout, "public edit\n")
        self.assertEqual(self.jj("diff", "--name-only").stdout.strip(), "remaining")
        self.jj("c", "-mnext change")
        self.assertEqual(self.rev('description(exact:"next change\\n")-', "commit_id"), public)

    def test_no_private_history_uses_direct_parent(self):
        self.write("public", "public edit\n")
        self.jj("c", "-m", "public change")
        self.assertEqual(self.rev("@--"), self.base)
        self.assertEqual(self.rev("@-", "description.first_line()"), "public change")
        self.assertEqual(self.rev("@", "empty"), "true")

    def test_argument_errors_do_not_rewrite_history(self):
        for arguments in (("--from", "dev"), ("--insert-after", "dev"), ("-m",), ("--into",)):
            with self.subTest(arguments=arguments):
                operation = self.operation()
                result = self.jj("c", *arguments, check=False)
                self.assertEqual(result.returncode, 2)
                self.assertEqual(self.operation(), operation)

    def test_configuration_failure_does_not_continue(self):
        with self.config.open("a") as config:
            config.write('\n[git]\ninvalid = "duplicate table"\n')
        result = subprocess.run(
            [str(ROOT / "bin/jj-private-commit"), "-m", "public change"],
            cwd=self.repo, env=self.env, text=True, capture_output=True,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("config", result.stderr.lower())
        self.assertNotIn("Created", result.stderr)

    def test_interactive_tool_selection_passes_through(self):
        self.private_stack()
        self.write("public", "public edit\n")
        marker = self.directory / "editor-ran"
        editor = self.directory / "select-all"
        editor.write_text(f"#!/bin/sh\ntouch '{marker}'\n")
        editor.chmod(0o755)
        with self.config.open("a") as config:
            config.write(f'\n[merge-tools.select-all]\nprogram = {json.dumps(str(editor))}\n'
                         'edit-args = ["$left", "$right"]\n')
        self.jj("c", "-i", "--tool", "select-all", "-m", "public change")
        self.assertTrue(marker.exists())
        self.assert_public_commit()

    def description_editor(self):
        marker = self.directory / "description-editor-ran"
        editor = self.directory / "describe"
        editor.write_text(
            f"#!/bin/sh\ntouch '{marker}'\nprintf '%s\\n' 'public change' > \"$1\"\n"
        )
        editor.chmod(0o755)
        self.env["JJ_EDITOR"] = str(editor)
        return marker

    def test_missing_message_opens_description_editor(self):
        self.private_stack()
        self.write("public", "public edit\n")
        marker = self.description_editor()
        self.jj("c")
        self.assertTrue(marker.exists(), "jj c must open the description editor without -m")
        self.assert_public_commit()

    def test_existing_working_copy_description_still_opens_editor(self):
        self.private_stack()
        self.jj("new", "@-", "-m", "draft description")
        self.write("public", "public edit\n")
        marker = self.description_editor()
        self.jj("c")
        self.assertTrue(marker.exists())
        self.assert_public_commit()

    def test_explicit_editor_can_accompany_message_without_duplicate_flags(self):
        self.private_stack()
        self.write("public", "public edit\n")
        marker = self.description_editor()
        self.jj("c", "--editor", "-m", "initial description")
        self.assertTrue(marker.exists())
        self.assert_public_commit()

    def test_message_looking_filename_does_not_suppress_editor(self):
        self.write("-m", "file content\n")
        marker = self.description_editor()
        self.jj("c", "--", "-m")
        self.assertTrue(marker.exists())
        self.assertEqual(self.rev("@-", "description.first_line()"), "public change")
        self.assertEqual(self.jj("file", "show", "-r", "@-", "--", "-m").stdout, "file content\n")

    def test_squash_failure_exit_status_propagates(self):
        self.write("public", "public edit\n")
        # The deliberately failing editor is supplied by this disposable fixture.
        result = self.jj("c", "--editor", check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.rev('description(exact:"public change\\n")'), "")
        self.assertEqual(self.jj("diff", "--name-only").stdout.strip(), "public")


if __name__ == "__main__":
    unittest.main()
