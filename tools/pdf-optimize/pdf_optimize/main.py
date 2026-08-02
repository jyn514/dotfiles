"""Optimize PDFs with explicit process and filesystem boundaries.

Copyright (c) 2016, Charles Daniels. All rights reserved.

Redistribution and use are permitted under the three-clause BSD terms in the
adjacent LICENSE file.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Sequence


GHOSTSCRIPT_OPTIONS = (
    b"-sDEVICE=pdfwrite",
    b"-dDetectDuplicateImages=true",
    b"-dPDFSETTINGS=/ebook",
    b"-dCompatibilityLevel=1.4",
    b"-dColorConversionStrategy=/LeaveColorUnchanged",
    b"-dDownsampleMonoImages=false",
    b"-dDownsampleGrayImages=false",
    b"-dDownsampleColorImages=false",
)


def executable(name: str) -> bytes | None:
    found = shutil.which(name)
    return os.fsencode(found) if found is not None else None


def exit_status(returncode: int) -> int:
    return returncode if returncode >= 0 else 128 - returncode


def run(
    arguments: Sequence[bytes], *, stdout: int | None = None, stderr: int | None = None
) -> subprocess.CompletedProcess[bytes] | None:
    try:
        return subprocess.run(
            arguments,
            check=False,
            stdout=stdout,
            stderr=stderr,
        )
    except OSError as error:
        print(
            f"pdf-optimize: could not execute {os.fsdecode(arguments[0])!r}: {error}",
            file=sys.stderr,
        )
        return None


def is_pdf(file_command: bytes, source: bytes) -> tuple[int, bool]:
    result = run(
        [file_command, b"--brief", b"--", source],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result is None:
        return 127, False
    if result.returncode:
        if result.stderr:
            sys.stderr.buffer.write(result.stderr)
        return exit_status(result.returncode), False
    return 0, b"PDF" in result.stdout


def disk_size(du_command: bytes, path: bytes) -> tuple[int, str]:
    result = run(
        [du_command, b"-h", path],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result is None:
        return 127, ""
    if result.returncode:
        if result.stderr:
            sys.stderr.buffer.write(result.stderr)
        return exit_status(result.returncode), ""
    size = result.stdout.split(b"\t", 1)[0].split(None, 1)[0] if result.stdout.strip() else b""
    if not size:
        print("pdf-optimize: malformed du output", file=sys.stderr)
        return 1, ""
    return 0, os.fsdecode(size)


def publish(source: bytes, destination: bytes) -> None:
    parent = os.path.dirname(os.path.abspath(destination))
    prefix = b"." + os.path.basename(destination) + b"."
    descriptor, pending = tempfile.mkstemp(prefix=prefix, suffix=b".tmp", dir=parent)
    try:
        with os.fdopen(descriptor, "wb") as output, open(source, "rb") as optimized:
            shutil.copyfileobj(optimized, output)
            output.flush()
            os.fsync(output.fileno())
        os.chmod(pending, os.stat(source).st_mode & 0o777)
        os.link(pending, destination)
    finally:
        try:
            os.unlink(pending)
        except FileNotFoundError:
            pass


def optimize(source: bytes, destination: bytes) -> int:
    source = os.path.abspath(source)
    destination = os.path.abspath(destination)
    ghostscript = executable("gs")
    if ghostscript is None:
        print("ERROR: ghostscript was not found on this system", file=sys.stderr)
        return 127
    file_command = executable("file")
    if file_command is None:
        print("ERROR: file was not found on this system", file=sys.stderr)
        return 127
    if not os.path.isfile(source):
        print("ERROR: input file does not exist or is not a file!", file=sys.stderr)
        return 1
    status, pdf = is_pdf(file_command, source)
    if status:
        return status
    if not pdf:
        print("ERROR: input file does not seem to be a PDF", file=sys.stderr)
        return 1
    if os.path.lexists(destination):
        print("ERROR: output file already exists!", file=sys.stderr)
        return 1

    temporary_root = os.environ.get("TMPDIR", tempfile.gettempdir())
    descriptor, log_text = tempfile.mkstemp(
        prefix="pdf-optimize-", suffix=".log", dir=temporary_root
    )
    os.close(descriptor)
    log = os.fsencode(log_text)

    print(f"INFO: Using input file: {os.fsdecode(source)}")
    print(f"INFO: Using output file: {os.fsdecode(destination)}")
    print(f"INFO: Using gs command: {os.fsdecode(ghostscript)}")
    print(
        "INFO: Using gs options: "
        + " ".join(os.fsdecode(value) for value in GHOSTSCRIPT_OPTIONS)
    )
    print(f"INFO: Log path: {log_text}")

    with tempfile.TemporaryDirectory(prefix="pdf-optimize.", dir=temporary_root) as directory_text:
        directory = os.fsencode(directory_text)
        temporary_input = os.path.join(directory, b"input.pdf")
        temporary_output = os.path.join(directory, b"output.pdf")
        shutil.copyfile(source, temporary_input)

        print("STATUS: Optimizing pdf... ", end="", flush=True)
        started = time.monotonic()
        with open(log, "wb") as output:
            result = run(
                [
                    ghostscript,
                    *GHOSTSCRIPT_OPTIONS,
                    b"-o",
                    temporary_output,
                    temporary_input,
                ],
                stdout=output.fileno(),
                stderr=output.fileno(),
            )
        if result is None:
            return 127
        if result.returncode:
            return exit_status(result.returncode)
        if not os.path.isfile(temporary_output):
            print("FAIL\npdf-optimize: ghostscript produced no output", file=sys.stderr)
            return 1
        print("done")
        print(f"INFO: optimized PDF in {int(time.monotonic() - started)} seconds")

        try:
            publish(temporary_output, destination)
        except FileExistsError:
            print("ERROR: output file already exists!", file=sys.stderr)
            return 1
        except OSError as error:
            print(f"pdf-optimize: could not publish output: {error}", file=sys.stderr)
            return 1

    print(f"INFO: GhostScript log written to: {log_text}")
    du_command = executable("du")
    if du_command is None:
        print("ERROR: du was not found on this system", file=sys.stderr)
        return 127
    input_status, input_size = disk_size(du_command, source)
    if input_status:
        return input_status
    output_status, output_size = disk_size(du_command, destination)
    if output_status:
        return output_status
    print(f"Input file size: {input_size}")
    print(f"Output file size: {output_size}")
    return 0


def main(arguments: list[str]) -> int:
    if len(arguments) not in (1, 2):
        print("Usage: pdf-optimize [input file] [output file]", file=sys.stderr)
        print("output file is optional", file=sys.stderr)
        return 1
    source = os.fsencode(arguments[0])
    destination = os.fsencode(arguments[1]) if len(arguments) == 2 else source + b"-optimized.pdf"
    return optimize(source, destination)
