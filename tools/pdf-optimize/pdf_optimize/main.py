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


def emit(
    message: bytes, *, stderr: bool = False, end: bytes = b"\n", flush: bool = False
) -> None:
    """Write diagnostics without decoding filesystem bytes into text."""
    stream = sys.stderr.buffer if stderr else sys.stdout.buffer
    stream.write(message + end)
    if flush:
        stream.flush()


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
        emit(
            b"pdf-optimize: could not execute "
            + repr(arguments[0]).encode("ascii")
            + b": "
            + os.fsencode(str(error)),
            stderr=True,
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
            emit(result.stderr, stderr=True, end=b"")
        return exit_status(result.returncode), False
    return 0, b"PDF" in result.stdout


def disk_size(du_command: bytes, path: bytes) -> tuple[int, bytes]:
    result = run(
        [du_command, b"-h", path],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result is None:
        return 127, b""
    if result.returncode:
        if result.stderr:
            emit(result.stderr, stderr=True, end=b"")
        return exit_status(result.returncode), b""
    size = result.stdout.split(b"\t", 1)[0].split(None, 1)[0] if result.stdout.strip() else b""
    if not size:
        emit(b"pdf-optimize: malformed du output", stderr=True)
        return 1, b""
    return 0, size


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
        emit(b"ERROR: ghostscript was not found on this system", stderr=True)
        return 127
    file_command = executable("file")
    if file_command is None:
        emit(b"ERROR: file was not found on this system", stderr=True)
        return 127
    if not os.path.isfile(source):
        emit(b"ERROR: input file does not exist or is not a file!", stderr=True)
        return 1
    status, pdf = is_pdf(file_command, source)
    if status:
        return status
    if not pdf:
        emit(b"ERROR: input file does not seem to be a PDF", stderr=True)
        return 1
    if os.path.lexists(destination):
        emit(b"ERROR: output file already exists!", stderr=True)
        return 1

    temporary_root = os.environ.get("TMPDIR", tempfile.gettempdir())
    descriptor, log_text = tempfile.mkstemp(
        prefix="pdf-optimize-", suffix=".log", dir=temporary_root
    )
    os.close(descriptor)
    log = os.fsencode(log_text)

    emit(b"INFO: Using input file: " + source)
    emit(b"INFO: Using output file: " + destination)
    emit(b"INFO: Using gs command: " + ghostscript)
    emit(b"INFO: Using gs options: " + b" ".join(GHOSTSCRIPT_OPTIONS))
    emit(b"INFO: Log path: " + log)

    with tempfile.TemporaryDirectory(prefix="pdf-optimize.", dir=temporary_root) as directory_text:
        directory = os.fsencode(directory_text)
        temporary_input = os.path.join(directory, b"input.pdf")
        temporary_output = os.path.join(directory, b"output.pdf")
        shutil.copyfile(source, temporary_input)

        emit(b"STATUS: Optimizing pdf... ", end=b"", flush=True)
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
            emit(b"FAIL\npdf-optimize: ghostscript produced no output", stderr=True)
            return 1
        emit(b"done")
        emit(
            b"INFO: optimized PDF in "
            + str(int(time.monotonic() - started)).encode("ascii")
            + b" seconds"
        )

        try:
            publish(temporary_output, destination)
        except FileExistsError:
            emit(b"ERROR: output file already exists!", stderr=True)
            return 1
        except OSError as error:
            emit(
                b"pdf-optimize: could not publish output: " + os.fsencode(str(error)),
                stderr=True,
            )
            return 1

    emit(b"INFO: GhostScript log written to: " + log)
    du_command = executable("du")
    if du_command is None:
        emit(b"ERROR: du was not found on this system", stderr=True)
        return 127
    input_status, input_size = disk_size(du_command, source)
    if input_status:
        return input_status
    output_status, output_size = disk_size(du_command, destination)
    if output_status:
        return output_status
    emit(b"Input file size: " + input_size)
    emit(b"Output file size: " + output_size)
    return 0


def main(arguments: list[str]) -> int:
    if len(arguments) not in (1, 2):
        emit(b"Usage: pdf-optimize [input file] [output file]", stderr=True)
        emit(b"output file is optional", stderr=True)
        return 1
    source = os.fsencode(arguments[0])
    destination = os.fsencode(arguments[1]) if len(arguments) == 2 else source + b"-optimized.pdf"
    return optimize(source, destination)
