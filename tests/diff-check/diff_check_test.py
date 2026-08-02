#!/usr/bin/env python3

import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DIFF_CHECK = ROOT / "libexec" / "agent-wrappers" / "diff-check"


class DiffCheckTest(unittest.TestCase):
    def run_diff_check(
        self, diff: bytes, *arguments: str, jj_exit_code: int = 0
    ) -> subprocess.CompletedProcess[bytes]:
        with tempfile.TemporaryDirectory() as directory:
            temp_dir = Path(directory)
            fixture = temp_dir / "diff"
            fixture.write_bytes(diff)
            arguments_file = temp_dir / "arguments"
            jj = temp_dir / "jj"
            jj.write_text(
                "#!/bin/sh\n"
                'printf "%s\\n" "$@" >"$JJ_ARGUMENTS_FILE"\n'
                'cat "$JJ_DIFF_FILE"\n'
                'exit "$JJ_EXIT_CODE"\n'
            )
            jj.chmod(0o755)
            env = os.environ | {
                "JJ_ARGUMENTS_FILE": str(arguments_file),
                "JJ_DIFF_FILE": str(fixture),
                "JJ_EXIT_CODE": str(jj_exit_code),
                "PATH": f"{temp_dir}{os.pathsep}{os.environ['PATH']}",
            }
            result = subprocess.run(
                [DIFF_CHECK, *arguments],
                env=env,
                capture_output=True,
                check=False,
            )
            result.arguments = arguments_file.read_text().splitlines()
            return result

    def test_allows_clean_added_line(self) -> None:
        result = self.run_diff_check(
            b"+++ b/code.txt\n"
            b"@@ -0,0 +1 @@\n"
            b"+foo();\n"
        )

        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, b"")

    def test_rejects_trailing_space(self) -> None:
        result = self.run_diff_check(
            b"+++ b/code.txt\n"
            b"@@ -0,0 +1 @@\n"
            b"+foo(); \n"
        )

        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, b"+foo(); \n")

    def test_rejects_trailing_tab(self) -> None:
        result = self.run_diff_check(b"+++ b/code.txt\n+foo();\t\n")

        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, b"+foo();\t\n")

    def test_rejects_cr_at_eol(self) -> None:
        result = self.run_diff_check(b"+++ b/code.txt\n+foo();\r\n")

        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, b"+foo();\r\n")

    def test_rejects_cr_without_final_newline(self) -> None:
        result = self.run_diff_check(b"+++ b/code.txt\n+foo();\r")

        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, b"+foo();\r")

    def test_rejects_other_ascii_trailing_whitespace_used_by_git(self) -> None:
        result = self.run_diff_check(
            b"+++ b/code.txt\n"
            b"+vertical tab\v\n"
            b"+form feed\f\n"
        )

        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, b"+vertical tab\v\n+form feed\f\n")

    def test_allows_internal_whitespace(self) -> None:
        result = self.run_diff_check(b"+++ b/code.txt\n+foo bar\tbaz\n")

        self.assertEqual(result.returncode, 0)

    def test_ignores_context_and_removed_lines(self) -> None:
        result = self.run_diff_check(
            b"+++ b/code.txt\n"
            b" context \n"
            b"-removed \n"
            b"+clean\n"
        )

        self.assertEqual(result.returncode, 0)

    def test_does_not_treat_file_header_as_added_content(self) -> None:
        result = self.run_diff_check(b"+++ b/path with space \n")

        self.assertEqual(result.returncode, 0)

    def test_reports_every_bad_added_line(self) -> None:
        result = self.run_diff_check(
            b"+++ b/code.txt\n"
            b"+one \n"
            b"+clean\n"
            b"+two\t\n"
        )

        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, b"+one \n+two\t\n")

    def test_handles_invalid_utf8_as_bytes(self) -> None:
        result = self.run_diff_check(b"+++ b/data.txt\n+\xff\xfe \n")

        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, b"+\xff\xfe \n")

    def test_allows_added_empty_line(self) -> None:
        result = self.run_diff_check(b"+++ b/code.txt\n+\n")

        self.assertEqual(result.returncode, 0)

    def test_allows_space_before_tab_in_indent(self) -> None:
        result = self.run_diff_check(b"+++ b/code.txt\n+ \tfoo();\n")

        self.assertEqual(result.returncode, 0)

    def test_allows_blank_context_line_in_patch_file(self) -> None:
        result = self.run_diff_check(
            b"+++ b/change.patch\n"
            b"@@ -0,0 +1,2 @@\n"
            b"+ context\n"
            b"+ \n"
        )

        self.assertEqual(result.returncode, 0)

    def test_allows_blank_context_line_in_diff_file(self) -> None:
        result = self.run_diff_check(b"+++ b/change.diff\n+ \n")

        self.assertEqual(result.returncode, 0)

    def test_allows_blank_context_line_in_quoted_patch_path(self) -> None:
        result = self.run_diff_check(b'+++ "b/change.patch"\n+ \n')

        self.assertEqual(result.returncode, 0)

    def test_rejects_other_trailing_whitespace_in_patch_file(self) -> None:
        result = self.run_diff_check(b"+++ b/change.patch\n++added \n")

        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, b"++added \n")

    def test_skips_pdf_case_insensitively(self) -> None:
        result = self.run_diff_check(
            b"+++ b/document.PdF\n"
            b"+\xff\xfe \r\n"
        )

        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, b"")

    def test_skips_pdf_with_quoted_path(self) -> None:
        result = self.run_diff_check(b'+++ "b/a document.pdf"\n+bad \n')

        self.assertEqual(result.returncode, 0)

    def test_resumes_checking_after_pdf(self) -> None:
        result = self.run_diff_check(
            b"+++ b/document.pdf\n"
            b"+ignored \n"
            b"+++ b/code.txt\n"
            b"+reported \n"
        )

        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, b"+reported \n")

    def test_forwards_arguments_to_jj_diff_git(self) -> None:
        result = self.run_diff_check(b"", "-r", "@-", "--", "file.txt")

        self.assertEqual(
            result.arguments,
            ["diff", "--git", "-r", "@-", "--", "file.txt"],
        )

    def test_propagates_jj_failure(self) -> None:
        result = self.run_diff_check(b"", jj_exit_code=7)

        self.assertEqual(result.returncode, 7)


if __name__ == "__main__":
    unittest.main()
