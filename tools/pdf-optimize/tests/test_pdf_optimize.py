from __future__ import annotations

import os
import shutil
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
            "PYTHONIOENCODING": "utf-8:strict",
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
        self.assertIn(f"INFO: Using input file: {self.source}\n".encode(), result.stdout)
        self.assertIn(f"INFO: Using output file: {destination}\n".encode(), result.stdout)
        calls = self.calls.read_text()
        self.assertIn(f"file <--brief> <--dereference> <--> <{self.source}>", calls)
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
    @unittest.skipIf(sys.platform == "darwin", "macOS requires UTF-8 filenames")
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
        self.assertIn(b"INFO: Using input file: " + source + b"\n", result.stdout)
        self.assertIn(b"INFO: Using output file: " + destination + b"\n", result.stdout)
        self.assertEqual(b"%PDF-1.4\nsource\n", Path(os.fsdecode(destination)).read_bytes())


@unittest.skipUnless(
    all(shutil.which(command) for command in ("file", "gs", "du")),
    "native PDF checks require file, Ghostscript, and du",
)
class NativePdfInputTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.source = self.directory / "document.pdf"
        shutil.copyfile(Path(__file__).parent / "fixtures/one-page.pdf", self.source)
        self.link = self.directory / "current.pdf"
        self.link.symlink_to(self.source.name)

    def run_command(self, *arguments: Path) -> subprocess.CompletedProcess[bytes]:
        return subprocess.run(
            [COMMAND, *arguments],
            cwd=self.directory,
            env=os.environ | {"TMPDIR": str(self.directory)},
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

    def test_direct_and_symlink_inputs_produce_readable_pdfs(self) -> None:
        original = self.source.read_bytes()
        for source in (self.source, self.link):
            with self.subTest(source=source.name):
                result = self.run_command(source)
                destination = Path(f"{source}-optimized.pdf")
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertTrue(destination.is_file())
                parsed = subprocess.run(
                    ["gs", "-q", "-dBATCH", "-dNOPAUSE", "-sDEVICE=nullpage", destination],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    check=False,
                )
                self.assertEqual(0, parsed.returncode, parsed.stderr)
        self.assertEqual(original, self.source.read_bytes())
        self.assertTrue(self.link.is_symlink())
        self.assertEqual(self.source.name, os.readlink(self.link))

    def test_symlink_to_non_pdf_is_rejected_before_optimization(self) -> None:
        self.source.write_text("not a PDF document\n")
        result = self.run_command(self.link)

        self.assertEqual(1, result.returncode)
        self.assertIn(b"does not seem to be a PDF", result.stderr)
        self.assertFalse(Path(f"{self.link}-optimized.pdf").exists())
        self.assertEqual([], list(self.directory.glob("pdf-optimize-*.log")))

    def test_symlink_input_does_not_allow_overwriting_a_destination_symlink(self) -> None:
        destination = self.directory / "output.pdf"
        destination.symlink_to("absent.pdf")
        result = self.run_command(self.link, destination)

        self.assertEqual(1, result.returncode)
        self.assertIn(b"output file already exists", result.stderr)
        self.assertTrue(destination.is_symlink())
        self.assertEqual("absent.pdf", os.readlink(destination))
        self.assertFalse((self.directory / "absent.pdf").exists())
        self.assertEqual([], list(self.directory.glob("pdf-optimize-*.log")))


if __name__ == "__main__":
    unittest.main()
