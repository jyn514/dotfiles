#!/usr/bin/env python3
"""Build the disposable repository's base through the installed image helper."""

import os
from pathlib import Path

root = Path(__file__).resolve().parents[3]
builder = root / "tools/codex-sandbox/sandbox-image"
dockerfile = root / ".agents/sandbox/Dockerfile"
os.execv(builder, [
    str(builder), "build", "--file", str(dockerfile),
    "--tag", "dotfiles-sandbox-fixture:local", str(dockerfile.parent),
])
