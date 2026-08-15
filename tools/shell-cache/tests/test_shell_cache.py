import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[3]
COMMAND = ROOT / "bin/refresh-fish-cache"
sys.path.insert(0, str(ROOT / "tools/shell-cache"))
from shell_cache import main as shell_cache  # noqa: E402


class ShellCacheTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.cache = self.directory / "cache/config.fish"
        self.dependency = self.directory / "brew"
        self.count = self.directory / "count"
        self.dependency.write_text("dependency")
        producer = self.directory / "producer"
        producer.write_text(
            f"#!{sys.executable}\n"
            "import os, pathlib, signal, sys, time\n"
            "count = pathlib.Path(os.environ['PRODUCER_COUNT'])\n"
            "count.write_text(str(int(count.read_text()) + 1) if count.exists() else '1')\n"
            "time.sleep(float(os.environ.get('PRODUCER_DELAY', '0')))\n"
            "sys.stdout.buffer.write(os.environ.get('PRODUCER_OUTPUT', 'set -gx TEA new\\n').encode())\n"
            "sys.stderr.write(os.environ.get('PRODUCER_STDERR', ''))\n"
            "if os.environ.get('PRODUCER_SIGNAL'):\n"
            "    os.kill(os.getpid(), signal.SIGTERM)\n"
            "raise SystemExit(int(os.environ.get('PRODUCER_STATUS', '0')))\n"
        )
        producer.chmod(0o755)
        self.producer = producer

    def run_command(self, environment: dict[str, str] | None = None) -> subprocess.CompletedProcess[bytes]:
        values = {
            "PATH": str(self.directory),
            "PRODUCER_COUNT": str(self.count),
        }
        if environment:
            values.update(environment)
        return subprocess.run(
            [
                sys.executable,
                str(COMMAND),
                "--destination",
                str(self.cache),
                "--dependency",
                str(self.dependency),
                "--",
                str(self.producer),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=values,
            check=False,
        )

    def make_stale_cache(self, contents: str = "set -gx TEA old\n") -> None:
        self.cache.parent.mkdir(parents=True, exist_ok=True)
        self.cache.write_text(contents)
        old = time.time_ns() - 2_000_000_000
        os.utime(self.cache, ns=(old, old))
        os.utime(self.dependency, None)

    def pending_files(self) -> list[Path]:
        if not self.cache.parent.exists():
            return []
        return list(self.cache.parent.glob(f".{self.cache.name}.*.pending"))

    def test_success_is_atomic_and_fresh_cache_skips_producer(self) -> None:
        first = self.run_command()
        second = self.run_command()

        self.assertEqual(0, first.returncode, first.stderr)
        self.assertEqual(0, second.returncode, second.stderr)
        self.assertEqual("set -gx TEA new\n", self.cache.read_text())
        self.assertEqual("1", self.count.read_text())
        self.assertEqual([], self.pending_files())

    def test_producer_failure_uses_old_cache_but_not_partial_output(self) -> None:
        self.make_stale_cache()

        result = self.run_command(
            {"PRODUCER_OUTPUT": "set -gx TEA partial\n", "PRODUCER_STATUS": "23"}
        )

        self.assertEqual(75, result.returncode)
        self.assertEqual("set -gx TEA old\n", self.cache.read_text())
        self.assertIn(b"producer failed with status 23", result.stderr)
        self.assertEqual([], self.pending_files())

    def test_first_run_failure_preserves_producer_status(self) -> None:
        result = self.run_command({"PRODUCER_STATUS": "24"})

        self.assertEqual(24, result.returncode)
        self.assertFalse(self.cache.exists())
        self.assertEqual([], self.pending_files())

    def test_generation_is_not_syntax_checked(self) -> None:
        self.make_stale_cache()
        result = self.run_command({"PRODUCER_OUTPUT": "INVALID\n"})

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("INVALID\n", self.cache.read_text())

    def test_interrupted_generation_leaves_cache_and_cleans_staging(self) -> None:
        self.make_stale_cache()
        interrupted = self.run_command({"PRODUCER_SIGNAL": "1"})

        self.assertEqual(75, interrupted.returncode)
        self.assertEqual("set -gx TEA old\n", self.cache.read_text())
        self.assertEqual([], self.pending_files())

    def test_abandoned_staging_is_cleaned(self) -> None:
        self.make_stale_cache()
        abandoned = self.cache.parent / f".{self.cache.name}.abandoned.pending"
        abandoned.write_text("partial")

        result = self.run_command()

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertFalse(abandoned.exists())

    def test_replace_failure_keeps_old_cache_and_cleans_staging(self) -> None:
        self.make_stale_cache()
        with (
            mock.patch.dict(os.environ, {"PRODUCER_COUNT": str(self.count)}),
            mock.patch.object(shell_cache.os, "replace", side_effect=OSError("rename failed")),
        ):
            status = shell_cache.refresh(self.cache, [self.dependency], [str(self.producer)])

        self.assertEqual(75, status)
        self.assertEqual("set -gx TEA old\n", self.cache.read_text())
        self.assertEqual([], self.pending_files())

    def test_unusable_destination_directory_fails_without_cache(self) -> None:
        parent = self.cache.parent
        parent.write_text("not a directory")

        result = self.run_command()

        self.assertEqual(1, result.returncode)
        self.assertIn(b"could not prepare cache directory", result.stderr)

    def test_concurrent_refresh_runs_producer_once(self) -> None:
        environment = os.environ | {
            "PATH": str(self.directory),
            "PRODUCER_COUNT": str(self.count),
            "PRODUCER_DELAY": "0.2",
        }
        command = [
            sys.executable,
            str(COMMAND),
            "--destination",
            str(self.cache),
            "--dependency",
            str(self.dependency),
            "--",
            str(self.producer),
        ]
        first = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=environment)
        second = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=environment)
        first_output = first.communicate(timeout=5)
        second_output = second.communicate(timeout=5)

        self.assertEqual(0, first.returncode, first_output[1])
        self.assertEqual(0, second.returncode, second_output[1])
        self.assertEqual("1", self.count.read_text())


if __name__ == "__main__":
    unittest.main()
