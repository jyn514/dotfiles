from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
COMMAND = ROOT / "bin/pdf-optimize"


class PdfOptimizeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name)
        self.bin = self.directory / "bin"
        self.bin.mkdir()
        self.source = self.directory / "source file.pdf"
        self.source.write_bytes(b"%PDF-1.4\nsource\n")
        self.calls = self.directory / "calls"
        self.make_executable(
            "file",
            'printf "file" >> "$CALLS"\n'
            'for value in "$@"; do printf " <%s>" "$value" >> "$CALLS"; done\n'
            'printf "\\nPDF document\\n"\n',
        )
        self.make_executable(
            "du",
            'printf "du" >> "$CALLS"\n'
            'for value in "$@"; do printf " <%s>" "$value" >> "$CALLS"; done\n'
            'printf "4.0K\\t%s\\n" "$2"\n',
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def make_executable(self, name: str, body: str) -> Path:
        path = self.bin / name
        path.write_text("#!/bin/sh\nset -eu\n" + body)
        path.chmod(0o755)
        return path

    def environment(self) -> dict[str, str]:
        return os.environ | {
            "CALLS": str(self.calls),
            "PATH": f"{self.bin}:{os.environ['PATH']}",
            "TMPDIR": str(self.directory),
        }

    def run_command(self, *arguments: Path | str) -> subprocess.CompletedProcess[bytes]:
        return subprocess.run(
            [COMMAND, *arguments],
            cwd=self.directory,
            env=self.environment(),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

    def successful_ghostscript(self) -> None:
        self.make_executable(
            "gs",
            'printf "gs" >> "$CALLS"\n'
            'for value in "$@"; do printf " <%s>" "$value" >> "$CALLS"; done\n'
            'while [ "$1" != -o ]; do shift; done\n'
            'cp "$3" "$2"\n',
        )

    def test_passes_exact_arguments_and_publishes_complete_output(self) -> None:
        self.successful_ghostscript()
        destination = self.directory / "output file.pdf"
        result = self.run_command(self.source, destination)

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(self.source.read_bytes(), destination.read_bytes())
        calls = self.calls.read_text()
        self.assertIn(f"file <--brief> <--> <{self.source}>", calls)
        self.assertIn("gs <-sDEVICE=pdfwrite> <-dDetectDuplicateImages=true>", calls)
        self.assertIn(" <-o> ", calls)
        self.assertIn(f"du <-h> <{destination}>", calls)
        self.assertEqual([], list(self.directory.glob(".output file.pdf.*.tmp")))

    def test_one_argument_uses_documented_default_output(self) -> None:
        self.successful_ghostscript()
        result = self.run_command(self.source)

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertTrue(Path(f"{self.source}-optimized.pdf").is_file())

    def test_ghostscript_failure_leaves_no_output_and_preserves_log(self) -> None:
        self.make_executable("gs", "printf 'partial log\\n'\nexit 42\n")
        destination = self.directory / "failed.pdf"
        result = self.run_command(self.source, destination)

        self.assertEqual(42, result.returncode)
        self.assertFalse(destination.exists())
        logs = list(self.directory.glob("pdf-optimize-*.log"))
        self.assertEqual(1, len(logs))
        self.assertEqual("partial log\n", logs[0].read_text())

    def test_refuses_existing_output_before_running_ghostscript(self) -> None:
        self.make_executable("gs", "exit 99\n")
        destination = self.directory / "existing.pdf"
        destination.write_text("keep\n")
        result = self.run_command(self.source, destination)

        self.assertEqual(1, result.returncode)
        self.assertEqual("keep\n", destination.read_text())

    def test_rejects_non_pdf_input(self) -> None:
        self.make_executable("file", "printf 'ASCII text\\n'\n")
        self.make_executable("gs", "exit 99\n")
        result = self.run_command(self.source)

        self.assertEqual(1, result.returncode)
        self.assertIn(b"does not seem to be a PDF", result.stderr)

    def test_missing_ghostscript_is_a_dependency_error(self) -> None:
        (self.bin / "python3").symlink_to(sys.executable)
        environment = self.environment()
        environment["PATH"] = str(self.bin)
        result = subprocess.run(
            [COMMAND, self.source],
            cwd=self.directory,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

        self.assertEqual(127, result.returncode)
        self.assertIn(b"ghostscript was not found", result.stderr)

    def test_installed_symlink_runs_from_another_directory(self) -> None:
        self.successful_ghostscript()
        installed = self.directory / "installed-pdf-optimize"
        installed.symlink_to(COMMAND)
        destination = self.directory / "linked.pdf"
        result = subprocess.run(
            [installed, self.source, destination],
            cwd="/",
            env=self.environment(),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertTrue(destination.is_file())

    @unittest.skipUnless(os.name == "posix", "byte paths require POSIX")
    def test_undecodable_input_and_output_names_round_trip(self) -> None:
        self.successful_ghostscript()
        source = os.path.join(os.fsencode(self.directory), b"source-\xff.pdf")
        destination = os.path.join(os.fsencode(self.directory), b"output-\xfe.pdf")
        os.rename(os.fsencode(self.source), source)
        result = subprocess.run(
            [os.fsencode(COMMAND), source, destination],
            cwd=b"/",
            env=self.environment(),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(b"%PDF-1.4\nsource\n", Path(os.fsdecode(destination)).read_bytes())


if __name__ == "__main__":
    unittest.main()
