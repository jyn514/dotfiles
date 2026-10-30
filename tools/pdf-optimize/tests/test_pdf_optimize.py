from __future__ import annotations

import os
import re
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
        classified = re.search(r"file <--brief> <--dereference> <--> <(.*?)>gs", calls)
        self.assertIsNotNone(classified, calls)
        self.assertIn(f" <{classified.group(1)}>du", calls)
        self.assertIn("gs <-sDEVICE=pdfwrite> <-dDetectDuplicateImages=true>", calls)
        self.assertIn(" <-o> ", calls)
        self.assertIn(f"du <-h> <{destination}>", calls)
        self.assertEqual([], list(self.directory.glob(".output file.pdf.*.tmp")))

    def test_one_argument_uses_documented_default_output(self) -> None:
        self.successful_ghostscript()
        result = self.run_command(self.source)

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertTrue(Path(f"{self.source}-optimized.pdf").is_file())

    def test_source_path_components_are_resolved_by_the_filesystem(self) -> None:
        self.successful_ghostscript()
        actual = self.directory / "actual"
        (actual / "child").mkdir(parents=True)
        (self.directory / "link").symlink_to(actual / "child")
        selected = actual / self.source.name
        selected.write_bytes(b"%PDF-1.4\nselected through symlink parent\n")
        for absolute in (False, True):
            with self.subTest(absolute=absolute):
                source = f"link/../{self.source.name}"
                if absolute:
                    source = str(self.directory / source)
                destination = self.directory / f"selected-{absolute}.pdf"
                result = self.run_command(source, destination)
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertEqual(selected.read_bytes(), destination.read_bytes())
        self.assertEqual(b"%PDF-1.4\nsource\n", self.source.read_bytes())

    def test_missing_or_non_directory_source_component_is_not_normalized_away(self) -> None:
        self.successful_ghostscript()
        for component in ("missing", self.source.name):
            with self.subTest(component=component):
                destination = self.directory / "not-created.pdf"
                result = self.run_command(f"{component}/../{self.source.name}", destination)
                self.assertEqual(1, result.returncode, result.stderr)
                self.assertFalse(destination.exists())
                self.assertFalse(self.calls.exists())

    def test_missing_destination_component_is_not_normalized_away(self) -> None:
        self.successful_ghostscript()
        result = self.run_command(self.source, "missing/../not-created.pdf")
        self.assertEqual(1, result.returncode, result.stderr)
        self.assertIn(b"could not publish output", result.stderr)
        self.assertFalse((self.directory / "not-created.pdf").exists())
        self.assertEqual([], list(self.directory.glob(".not-created.pdf.*.tmp")))

    def test_option_like_relative_paths_remain_operands(self) -> None:
        self.successful_ghostscript()
        source = self.directory / "-input.pdf"
        source.write_bytes(self.source.read_bytes())
        result = self.run_command(source.name, "-output.pdf")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(source.read_bytes(), (self.directory / "-output.pdf").read_bytes())
        calls = self.calls.read_text()
        self.assertIn(f"du <-h> <{source}>", calls)
        self.assertIn(f"du <-h> <{self.directory / '-output.pdf'}>", calls)

    def test_input_size_failure_stops_before_snapshot_or_transformation(self) -> None:
        self.successful_ghostscript()
        self.make_executable("du", "printf 'cannot measure input\\n' >&2\nexit 44\n")
        destination = self.directory / "failed.pdf"
        result = self.run_command(self.source, destination)

        self.assertEqual(44, result.returncode)
        self.assertIn(b"cannot measure input\n", result.stderr)
        self.assertFalse(destination.exists())
        self.assertFalse(self.calls.exists())
        self.assertEqual([], list(self.directory.glob("pdf-optimize.*")))
        self.assertEqual([], list(self.directory.glob("pdf-optimize-*.log")))

    def test_missing_du_stops_before_transformation_or_publication(self) -> None:
        self.successful_ghostscript()
        (self.bin / "du").unlink()
        (self.bin / "python3").symlink_to(sys.executable)
        environment = self.environment() | {"PATH": str(self.bin)}
        destination = self.directory / "failed.pdf"
        result = subprocess.run(
            [COMMAND, self.source, destination], cwd=self.directory, env=environment,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
        )

        self.assertEqual(127, result.returncode)
        self.assertIn(b"du was not found", result.stderr)
        self.assertFalse(destination.exists())
        self.assertFalse(self.calls.exists())
        self.assertEqual([], list(self.directory.glob("pdf-optimize.*")))
        self.assertEqual([], list(self.directory.glob("pdf-optimize-*.log")))

    def test_output_size_failure_preserves_native_status_after_publication(self) -> None:
        self.successful_ghostscript()
        self.make_executable(
            "du",
            'if [ "$2" = "$SELECTED_SOURCE" ]; then printf "7.0K\\t%s\\n" "$2"; '
            'else printf "cannot measure output\\n" >&2; exit 45; fi\n',
        )
        destination = self.directory / "output.pdf"
        result = subprocess.run(
            [COMMAND, self.source, destination], cwd=self.directory,
            env=self.environment() | {"SELECTED_SOURCE": str(self.source)},
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
        )

        self.assertEqual(45, result.returncode)
        self.assertIn(b"cannot measure output\n", result.stderr)
        self.assertEqual(self.source.read_bytes(), destination.read_bytes())

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

    def test_classification_failure_preserves_status_and_cleans_snapshot(self) -> None:
        self.make_executable("file", "printf 'classification failed\\n' >&2\nexit 43\n")
        self.make_executable("gs", "exit 99\n")
        result = self.run_command(self.source)

        self.assertEqual(43, result.returncode)
        self.assertIn(b"classification failed\n", result.stderr)
        self.assertFalse(Path(f"{self.source}-optimized.pdf").exists())
        self.assertEqual([], list(self.directory.glob("pdf-optimize.*")))
        self.assertEqual([], list(self.directory.glob("pdf-optimize-*.log")))

    @unittest.skipUnless(os.name == "posix" and os.geteuid() != 0, "requires unprivileged POSIX permissions")
    def test_unreadable_input_fails_without_traceback_or_leaked_snapshot(self) -> None:
        self.successful_ghostscript()
        self.source.chmod(0)
        try:
            result = self.run_command(self.source)
        finally:
            self.source.chmod(0o600)

        self.assertEqual(1, result.returncode)
        self.assertIn(b"could not copy input", result.stderr)
        self.assertNotIn(b"Traceback", result.stderr)
        self.assertFalse(Path(f"{self.source}-optimized.pdf").exists())
        self.assertEqual([], list(self.directory.glob("pdf-optimize.*")))
        self.assertEqual([], list(self.directory.glob("pdf-optimize-*.log")))

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

    def test_regular_symlink_and_sparse_inputs_keep_native_disk_usage(self) -> None:
        original = self.source.read_bytes()
        sparse = self.directory / "sparse.pdf"
        sparse.write_bytes(original)
        with sparse.open("ab") as stream:
            stream.truncate(8 * 1024 * 1024)
        for source in (self.source, self.link, sparse):
            with self.subTest(source=source.name):
                measured = subprocess.run(
                    ["du", "-h", source], stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE, check=False,
                )
                self.assertEqual(0, measured.returncode, measured.stderr)
                expected_size = measured.stdout.split(b"\t", 1)[0]
                result = self.run_command(source)
                destination = Path(f"{source}-optimized.pdf")
                self.assertIn(b"Input file size: " + expected_size + b"\n", result.stdout)
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertTrue(destination.is_file())
                output_usage = subprocess.run(
                    ["du", "-h", destination], stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE, check=False,
                )
                self.assertEqual(0, output_usage.returncode, output_usage.stderr)
                expected_output = output_usage.stdout.split(b"\t", 1)[0]
                self.assertIn(b"Output file size: " + expected_output + b"\n", result.stdout)
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

    def test_percent_tmpdir_parents_produce_one_readable_page_and_clean_snapshot(self) -> None:
        original = self.source.read_bytes()
        for index, name in enumerate(
            ("ordinary", "literal-%d", "literal-%%", "literal-%x", "literal-%plain")
        ):
            with self.subTest(tmpdir=name):
                temporary_root = self.directory / name
                temporary_root.mkdir()
                destination = self.directory / f"optimized-{index}.pdf"
                result = subprocess.run(
                    [COMMAND, self.source, destination],
                    cwd=self.directory,
                    env=os.environ | {"TMPDIR": str(temporary_root)},
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
                )
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertTrue(destination.is_file())
                pages = self.directory / f"pages-{index}"
                pages.mkdir()
                parsed = subprocess.run(
                    ["gs", "-q", "-dBATCH", "-dNOPAUSE", "-sDEVICE=pnggray", "-r10",
                     f"-sOutputFile={pages}/page-%d.png", str(destination)],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
                )
                self.assertEqual(0, parsed.returncode, parsed.stderr)
                self.assertEqual(1, len(list(pages.glob("page-*.png"))))
                logs = list(temporary_root.glob("pdf-optimize-*.log"))
                self.assertEqual(1, len(logs))
                self.assertEqual(logs, list(temporary_root.iterdir()))
                self.assertEqual([], list(self.directory.glob(f".{destination.name}.*.tmp")))
                self.assertEqual(original, self.source.read_bytes())

    def test_symlink_parent_source_selects_the_native_document(self) -> None:
        actual = self.directory / "actual"
        (actual / "child").mkdir(parents=True)
        (self.directory / "link").symlink_to(actual / "child")
        selected = actual / "document.pdf"
        generated = subprocess.run(
            ["gs", "-q", "-dBATCH", "-dNOPAUSE", "-sDEVICE=pdfwrite",
             f"-sOutputFile={selected}", "-c", "showpage showpage"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
        )
        self.assertEqual(0, generated.returncode, generated.stderr)
        destination = self.directory / "selected.pdf"
        result = self.run_command(Path("link/../document.pdf"), destination)
        self.assertEqual(0, result.returncode, result.stderr)
        for index, (path, expected) in enumerate(
            ((self.source, 1), (selected, 2), (destination, 2))
        ):
            pages = self.directory / f"rendered-{index}"
            pages.mkdir()
            parsed = subprocess.run(
                ["gs", "-q", "-dBATCH", "-dNOPAUSE", "-sDEVICE=pnggray", "-r10",
                 f"-sOutputFile={pages}/page-%d.png", str(path)],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
            )
            self.assertEqual(0, parsed.returncode, parsed.stderr)
            self.assertEqual(expected, len(list(pages.glob("page-*.png"))))

    def test_destination_parent_components_and_existing_entries_keep_os_meaning(self) -> None:
        actual = self.directory / "actual"
        (actual / "child").mkdir(parents=True)
        (self.directory / "link").symlink_to(actual / "child")
        requested = Path("link/../output.pdf")
        destination = actual / "output.pdf"
        lexical = self.directory / "output.pdf"
        result = self.run_command(self.source, requested)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertTrue(destination.is_file())
        self.assertFalse(lexical.exists())
        original = destination.read_bytes()
        result = self.run_command(self.source, requested)
        self.assertEqual(1, result.returncode)
        self.assertIn(b"output file already exists", result.stderr)
        self.assertEqual(original, destination.read_bytes())
        self.assertFalse(lexical.exists())
        destination.unlink()
        destination.symlink_to("absent.pdf")
        result = self.run_command(self.source, requested)
        self.assertEqual(1, result.returncode)
        self.assertIn(b"output file already exists", result.stderr)
        self.assertEqual("absent.pdf", os.readlink(destination))
        self.assertFalse((actual / "absent.pdf").exists())
        self.assertFalse(lexical.exists())
        self.assertEqual([], list(actual.glob(".output.pdf.*.tmp")))

    def test_ghostscript_consumes_the_classified_snapshot_after_source_replacement(self) -> None:
        original = self.source.read_bytes()
        native_bin = self.directory / "bin"
        native_bin.mkdir()
        helper = Path(__file__).parent / "fixtures/replace-after-classification.py"
        for command in ("file", "gs"):
            wrapper = native_bin / command
            shutil.copyfile(helper, wrapper)
            wrapper.chmod(0o755)
        # Native Ghostscript accepts this non-PDF input, so success alone is
        # not an oracle for which document was validated and consumed.
        replacement_document = self.directory / "replacement.ps"
        replacement_document.write_bytes(b"%!PS\nshowpage\n%" + b"x" * (2 * 1024 * 1024))
        environment = os.environ | {
            "PATH": f"{native_bin}:{os.environ['PATH']}",
            "TMPDIR": str(self.directory),
            "NATIVE_FILE": shutil.which("file"),
            "NATIVE_GS": shutil.which("gs"),
        }
        for source in (self.source, self.link):
            with self.subTest(source=source.name):
                self.source.write_bytes(original)
                replacement = self.directory / "replacement"
                if source == self.link:
                    replacement.symlink_to(replacement_document.name)
                else:
                    shutil.copyfile(replacement_document, replacement)
                consumed = self.directory / "consumed.pdf"
                measured = subprocess.run(
                    ["du", "-h", source], stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE, check=False,
                )
                self.assertEqual(0, measured.returncode, measured.stderr)
                expected_size = measured.stdout.split(b"\t", 1)[0]
                result = subprocess.run(
                    [COMMAND, source],
                    cwd=self.directory,
                    env=environment | {
                        "SELECTED_SOURCE": str(source),
                        "REPLACEMENT": str(replacement),
                        "CONSUMED_INPUT": str(consumed),
                    },
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    check=False,
                )
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertIn(b"Input file size: " + expected_size + b"\n", result.stdout)
                self.assertEqual(replacement_document.read_bytes(), source.read_bytes())
                self.assertEqual(original, consumed.read_bytes())
                destination = Path(f"{source}-optimized.pdf")
                parsed = subprocess.run(
                    [environment["NATIVE_GS"], "-q", "-dBATCH", "-dNOPAUSE",
                     "-dPDFSTOPONERROR", "-sDEVICE=nullpage", destination],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    check=False,
                )
                self.assertEqual(0, parsed.returncode, parsed.stderr)
                self.assertEqual(source == self.link, source.is_symlink())
                # A separate invocation must classify the current source, not
                # reuse the preceding operation's accepted snapshot.
                next_destination = self.directory / "next-output.pdf"
                next_result = self.run_command(source, next_destination)
                self.assertEqual(1, next_result.returncode)
                self.assertIn(b"does not seem to be a PDF", next_result.stderr)
                self.assertFalse(next_destination.exists())

    def test_native_du_failure_stops_before_transformation_or_publication(self) -> None:
        native_du = shutil.which("du")
        native_bin = self.directory / "bin"
        native_bin.mkdir()
        failing_du = native_bin / "du"
        failing_du.write_text(
            '#!/bin/sh\nrm -- "$SELECTED_SOURCE"\nexec "$NATIVE_DU" "$@"\n'
        )
        failing_du.chmod(0o755)
        destination = self.directory / "output.pdf"
        result = subprocess.run(
            [COMMAND, self.source, destination], cwd=self.directory,
            env=os.environ | {
                "PATH": f"{native_bin}:{os.environ['PATH']}",
                "TMPDIR": str(self.directory), "NATIVE_DU": native_du,
                "SELECTED_SOURCE": str(self.source),
            },
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
        )
        native_failure = subprocess.run(
            [native_du, "-h", self.source], stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, check=False,
        )
        self.assertNotEqual(0, native_failure.returncode)
        self.assertEqual(native_failure.returncode, result.returncode)
        self.assertEqual(native_failure.stderr, result.stderr)
        self.assertFalse(destination.exists())
        self.assertEqual([], list(self.directory.glob("pdf-optimize.*")))
        self.assertEqual([], list(self.directory.glob("pdf-optimize-*.log")))

    def test_source_removal_after_classification_keeps_published_success(self) -> None:
        original = self.source.read_bytes()
        native_bin = self.directory / "bin"
        native_bin.mkdir()
        helper = Path(__file__).parent / "fixtures/replace-after-classification.py"
        for command in ("file", "gs"):
            wrapper = native_bin / command
            shutil.copyfile(helper, wrapper)
            wrapper.chmod(0o755)
        environment = os.environ | {
            "PATH": f"{native_bin}:{os.environ['PATH']}",
            "TMPDIR": str(self.directory),
            "NATIVE_FILE": shutil.which("file"),
            "NATIVE_GS": shutil.which("gs"),
            "REMOVE_SELECTED_SOURCE": "1",
        }
        for source in (self.source, self.link):
            with self.subTest(source=source.name):
                self.source.write_bytes(original)
                measured = subprocess.run(
                    ["du", "-h", source], stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE, check=False,
                )
                self.assertEqual(0, measured.returncode, measured.stderr)
                expected_size = measured.stdout.split(b"\t", 1)[0]
                consumed = self.directory / "consumed.pdf"
                result = subprocess.run(
                    [COMMAND, source], cwd=self.directory,
                    env=environment | {"SELECTED_SOURCE": str(source), "CONSUMED_INPUT": str(consumed)},
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
                )
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertFalse(source.exists())
                self.assertEqual(original, consumed.read_bytes())
                self.assertIn(b"Input file size: " + expected_size + b"\n", result.stdout)
                destination = Path(f"{source}-optimized.pdf")
                parsed = subprocess.run(
                    [environment["NATIVE_GS"], "-q", "-dBATCH", "-dNOPAUSE",
                     "-dPDFSTOPONERROR", "-sDEVICE=nullpage", destination],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
                )
                self.assertEqual(0, parsed.returncode, parsed.stderr)
                self.assertEqual([], list(self.directory.glob("pdf-optimize.*")))
                self.assertEqual([], list(self.directory.glob(f".{destination.name}.*.tmp")))

    def test_symlink_to_non_pdf_is_rejected_before_optimization(self) -> None:
        self.source.write_text("not a PDF document\n")
        result = self.run_command(self.link)

        self.assertEqual(1, result.returncode)
        self.assertIn(b"does not seem to be a PDF", result.stderr)
        self.assertFalse(Path(f"{self.link}-optimized.pdf").exists())
        self.assertEqual([], list(self.directory.glob("pdf-optimize-*.log")))
        self.assertEqual([], list(self.directory.glob("pdf-optimize.*")))

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
