from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import contextlib
import fcntl
import io
import os
from pathlib import Path
import runpy
import subprocess
import tempfile
import threading
import unittest
from unittest import mock


LAUNCHER = Path(__file__).resolve().parents[1] / "codex-sandbox"


class StartupValidationTest(unittest.TestCase):
    def test_existing_metadata_does_not_discover_or_lock_session_resources(self):
        initialize = runpy.run_path(str(LAUNCHER))["initialize_dotfiles"]
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            repository = home / "repo"
            repository.mkdir()
            for kind in ("directory", "file", "dangling symlink"):
                with self.subTest(kind=kind):
                    entry = repository / ".jj"
                    if kind == "directory":
                        entry.mkdir()
                    elif kind == "file":
                        entry.touch()
                    else:
                        entry.symlink_to(repository / "missing")
                    try:
                        # Existing malformed metadata belongs to validation,
                        # never to reinitialization or the service session lock.
                        with mock.patch.object(Path, "home", return_value=home), mock.patch.dict(
                            initialize.__globals__,
                            proxy_module=mock.Mock(side_effect=AssertionError("session resources queried")),
                            run=mock.Mock(side_effect=AssertionError("existing metadata replaced")),
                        ):
                            initialize(repository)
                    finally:
                        if kind == "directory":
                            entry.rmdir()
                        else:
                            entry.unlink()

    def test_initializer_waits_for_partial_tree_and_initializes_only_once(self):
        initialize = runpy.run_path(str(LAUNCHER))["initialize_dotfiles"]
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            repository = home / "repo"
            repository.mkdir()
            runtime = home / "runtime"
            runtime.mkdir()
            partial = threading.Event()
            finish = threading.Event()
            second_lock_attempt = threading.Event()
            caller = threading.local()
            native_flock = fcntl.flock
            calls = []

            def flock(fd, operation):
                if getattr(caller, "second", False):
                    second_lock_attempt.set()
                return native_flock(fd, operation)

            def run(arguments, **kwargs):
                if arguments[0] == "git":
                    return subprocess.CompletedProcess(arguments, 0, stdout=str(repository))
                calls.append(arguments)
                (repository / ".jj").mkdir()
                partial.set()
                self.assertTrue(finish.wait(5), "test did not release initializer")
                (repository / ".jj/complete").touch()

            def second():
                caller.second = True
                initialize(repository)
                self.assertTrue((repository / ".jj/complete").exists())

            with mock.patch.object(Path, "home", return_value=home), mock.patch.dict(
                initialize.__globals__, run=run,
                proxy_module=lambda: mock.Mock(runtime_directory=lambda repo: runtime),
            ), mock.patch.object(fcntl, "flock", side_effect=flock), \
                    ThreadPoolExecutor(max_workers=2) as executor:
                first = executor.submit(initialize, repository)
                try:
                    self.assertTrue(partial.wait(5))
                    other = executor.submit(second)
                    self.assertTrue(second_lock_attempt.wait(5))
                    # The first initializer still owns the initialization lock.
                    self.assertFalse(other.done())
                finally:
                    finish.set()
                first.result(timeout=5)
                other.result(timeout=5)
            self.assertEqual(1, len(calls))

    def test_missing_metadata_still_waits_for_service_coordination(self):
        initialize = runpy.run_path(str(LAUNCHER))["initialize_dotfiles"]
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            repository = home / "repo"
            repository.mkdir()
            runtime = home / "runtime"
            runtime.mkdir()
            coordination_attempted = threading.Event()
            initialization_started = threading.Event()
            native_flock = fcntl.flock

            def run_command(arguments, **kwargs):
                initialization_started.set()
                return subprocess.CompletedProcess(arguments, 0, stdout=str(repository))

            run = mock.Mock(side_effect=run_command)
            with (runtime / "coordination.lock").open("a+b") as lock:
                coordination_identity = os.fstat(lock.fileno())

                def observe_flock(fd, operation):
                    metadata = os.fstat(fd if isinstance(fd, int) else fd.fileno())
                    if (metadata.st_dev, metadata.st_ino) == (
                        coordination_identity.st_dev, coordination_identity.st_ino,
                    ):
                        coordination_attempted.set()
                    return native_flock(fd, operation)

                native_flock(lock, fcntl.LOCK_EX)
                with mock.patch.object(Path, "home", return_value=home), mock.patch.dict(
                    initialize.__globals__, run=run,
                    proxy_module=lambda: mock.Mock(runtime_directory=lambda repo: runtime),
                ), mock.patch.object(fcntl, "flock", side_effect=observe_flock), \
                        ThreadPoolExecutor(max_workers=1) as executor:
                    task = executor.submit(initialize, repository)
                    try:
                        self.assertTrue(coordination_attempted.wait(5), "worker did not attempt coordination flock")
                        # Keep the real competing lock held after observing the
                        # worker's actual flock call. An immediate assertion can
                        # pass solely because the worker has not been scheduled;
                        # give a no-op acquisition time to reach initialization.
                        self.assertFalse(initialization_started.wait(0.2),
                                         "initialization ran while coordination was held")
                        run.assert_not_called()
                    finally:
                        native_flock(lock, fcntl.LOCK_UN)
                    task.result(timeout=5)
                    self.assertTrue(initialization_started.is_set())
                    self.assertEqual(["jj", "git", "init", "--colocate", str(repository)],
                                     run.call_args.args[0])

    def test_validation_timing_is_opt_in_and_reports_failed_substeps(self):
        timing = runpy.run_path(str(LAUNCHER))["validation_timing"]
        for enabled in (False, True):
            with self.subTest(enabled=enabled), mock.patch.dict(os.environ, {}, clear=True):
                if enabled:
                    os.environ["CODEX_SANDBOX_TIMING"] = "1"
                output = io.StringIO()
                with contextlib.redirect_stderr(output), self.assertRaisesRegex(ValueError, "rejected"):
                    with timing("workspace discovery"):
                        raise ValueError("rejected")
                if enabled:
                    self.assertRegex(output.getvalue(), r"Sandbox validation: workspace discovery=\d+\.\d{2}s")
                else:
                    self.assertEqual("", output.getvalue())


if __name__ == "__main__":
    unittest.main()
