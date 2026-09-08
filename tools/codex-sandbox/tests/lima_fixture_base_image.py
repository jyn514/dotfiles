#!/usr/bin/env python3
"""Delegate the disposable repository's base-image command to dotfiles."""

import os
from pathlib import Path

builder = Path(__file__).resolve().parents[3] / ".agents/sandbox/base-image"
os.execv(builder, [str(builder)])
