#!/usr/bin/env python3
"""Owned file-backed clipboard for the native decode-qr tests."""

import os
from pathlib import Path
import sys

if Path(sys.argv[0]).name == "paste":
    assert sys.argv[1:] == ["--type", "image/png"]
    sys.stdout.buffer.write(Path(os.environ["QR_TEST_IMAGE"]).read_bytes())
else:
    assert sys.argv[1:] == ["--primary"]
    Path(os.environ["QR_TEST_COPIED"]).write_bytes(sys.stdin.buffer.read())
    raise SystemExit(int(os.environ.get("QR_TEST_COPY_STATUS", "0")))
