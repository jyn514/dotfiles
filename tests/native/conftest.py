"""Native suites use pytest scheduling and the standard test isolation wrapper."""

import os
from pathlib import Path
import subprocess
import time

import fcntl

import pytest


ROOT = Path(__file__).resolve().parents[2]


def configured_native_jobs() -> int:
    value = os.environ.get("TEST_NATIVE_JOBS", "2")
    try:
        jobs = int(value)
    except ValueError as error:
        raise pytest.UsageError(f"TEST_NATIVE_JOBS must be a positive integer, got {value!r}") from error
    if jobs < 1:
        raise pytest.UsageError(f"TEST_NATIVE_JOBS must be a positive integer, got {value!r}")
    return jobs


@pytest.fixture(scope="session")
def native_slots(tmp_path_factory):
    """Return run-private lock files shared by every xdist worker."""
    base = tmp_path_factory.getbasetemp()
    shared = base.parent if os.environ.get("PYTEST_XDIST_WORKER") else base
    directory = shared / "native-slots"
    directory.mkdir(exist_ok=True)
    return tuple(directory / str(index) for index in range(configured_native_jobs()))


@pytest.fixture
def run_native_suite(native_slots):
    """Launch one native suite, preserving its output for pytest capture."""
    def run(command: list[str], *, env: dict[str, str] | None = None) -> None:
        command = list(command)
        if command[0] == "bb":
            command[0] = os.environ.get("DOTFILES_TEST_BB_REAL") or "bb"
        # Apply native overrides after isolation: the wrapper clears JJ_REAL.
        if env:
            command = ["env", *(f"{key}={value}" for key, value in env.items()), *command]
        lock = None
        while lock is None:
            for slot in native_slots:
                candidate = slot.open("a+")
                try:
                    fcntl.flock(candidate, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    candidate.close()
                else:
                    lock = candidate
                    break
            if lock is None:
                time.sleep(0.01)
        try:
            subprocess.run([str(ROOT / "dev/test-environment"), *command], cwd=ROOT, check=True)
        finally:
            lock.close()

    return run
