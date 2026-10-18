"""Native suites use pytest scheduling and the standard test isolation wrapper."""

import os
from pathlib import Path
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def run_native_suite():
    """Launch one native suite, preserving its output for pytest capture."""
    def run(command: list[str], *, env: dict[str, str] | None = None) -> None:
        command = list(command)
        if command[0] == "bb":
            command[0] = os.environ.get("DOTFILES_TEST_BB_REAL") or "bb"
        # Apply native overrides after isolation: the wrapper clears JJ_REAL.
        if env:
            command = ["env", *(f"{key}={value}" for key, value in env.items()), *command]
        subprocess.run([str(ROOT / "dev/test-environment"), *command], cwd=ROOT, check=True)

    return run
