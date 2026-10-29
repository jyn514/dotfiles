import os
from pathlib import Path
import shutil
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

    def run_command(
        self, environment: dict[str, str] | None = None, *, identity: str | None = None,
    ) -> subprocess.CompletedProcess[bytes]:
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
                *(["--identity", identity] if identity is not None else []),
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

    def test_identity_changes_regenerate_old_dependencies_at_same_destination(self) -> None:
        first = self.run_command(identity="old selected path")
        self.assertEqual(0, first.returncode, first.stderr)
        before = self.cache.read_bytes()
        second = self.run_command(
            {"PRODUCER_OUTPUT": "set -gx TEA changed\n"}, identity="new selected path",
        )
        self.assertEqual(0, second.returncode, second.stderr)
        self.assertNotEqual(before, self.cache.read_bytes())
        self.assertEqual(
            b"# refresh-fish-cache identity: new selected path\nset -gx TEA changed\n",
            self.cache.read_bytes(),
        )
        third = self.run_command(identity="new selected path")
        self.assertEqual(0, third.returncode, third.stderr)
        self.assertEqual("2", self.count.read_text())

    def test_identity_migration_and_failed_transition_keep_last_good_artifact(self) -> None:
        self.assertEqual(0, self.run_command().returncode)
        before = (self.cache.read_bytes(), self.cache.stat().st_mtime_ns)
        failed = self.run_command(
            {"PRODUCER_OUTPUT": "partial\n", "PRODUCER_STATUS": "23"}, identity="new",
        )
        self.assertEqual(75, failed.returncode, failed.stderr)
        self.assertEqual(before, (self.cache.read_bytes(), self.cache.stat().st_mtime_ns))
        self.assertFalse(shell_cache.fresh(self.cache, [self.dependency], "new"))
        self.assertEqual([], self.pending_files())
        retry = self.run_command(identity="new")
        self.assertEqual(0, retry.returncode, retry.stderr)
        self.assertTrue(shell_cache.fresh(self.cache, [self.dependency], "new"))
        self.assertEqual("3", self.count.read_text())

    def test_identity_is_opaque_and_cannot_inject_header_lines(self) -> None:
        identity = "'spaces and quotes' \\n $(touch sentinel); # \\r"
        result = self.run_command(identity=identity)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(
            ("# refresh-fish-cache identity: " + identity + "\nset -gx TEA new\n").encode(),
            self.cache.read_bytes(),
        )
        before = (self.cache.read_bytes(), self.cache.stat().st_mtime_ns)
        for invalid in ("line\nbreak", "line\rbreak"):
            with self.subTest(identity=invalid):
                result = self.run_command(identity=invalid)
                self.assertEqual(2, result.returncode, result.stderr)
                self.assertEqual(before, (self.cache.read_bytes(), self.cache.stat().st_mtime_ns))
        self.assertEqual("1", self.count.read_text())

    def test_empty_identity_is_not_the_same_as_omitted_identity(self) -> None:
        self.assertEqual(0, self.run_command(identity="").returncode)
        self.assertTrue(self.cache.read_bytes().startswith(b"# refresh-fish-cache identity: \n"))
        self.assertTrue(shell_cache.fresh(self.cache, [self.dependency], ""))
        self.assertFalse(shell_cache.fresh(self.cache, [self.dependency], "other"))
        # Existing callers still use only dependency mtimes, even if the
        # artifact happens to have been generated by an identity-aware caller.
        self.assertTrue(shell_cache.fresh(self.cache, [self.dependency]))
        self.dependency.unlink()
        self.assertFalse(shell_cache.fresh(self.cache, [self.dependency], ""))

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
        for identity in (None, "new"):
            with self.subTest(identity=identity):
                result = self.run_command({"PRODUCER_STATUS": "24"}, identity=identity)
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


@unittest.skipUnless(shutil.which("fish"), "Fish is required")
class FishCacheFastPathTest(unittest.TestCase):
    def test_native_fast_path_agrees_with_python_without_launching_refresher(self) -> None:
        source = (ROOT / "config/config.fish").read_text()
        function = "function refresh-fish-cache\n" + source.split(
            "function refresh-fish-cache\n", 1,
        )[1].split("\nif [ -f ~/.local/profile.fish ]", 1)[0]
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            cache = temporary / "cached hook.fish"
            dependency = temporary / "selected tool"
            forwarded = temporary / "forwarded"
            refresher = temporary / "refresh-fish-cache"
            refresher.write_text(
                f"#!{sys.executable}\n"
                "import os, pathlib, sys\n"
                "pathlib.Path(os.environ['FORWARDED']).write_text(repr(sys.argv[1:]))\n"
                "raise SystemExit(23)\n"
            )
            refresher.chmod(0o755)
            identity = "'spaces' \\n \\r $() ; # café"
            header = shell_cache.identity_header(identity)
            cases = (
                ("matching", header, identity, "old", True),
                ("matching-empty", shell_cache.identity_header(""), "", "old", True),
                ("changed", header, "other", "old", False),
                ("legacy", b"", identity, "old", False),
                ("no-identity", b"", None, "old", True),
                ("missing", header, identity, "missing", False),
                ("newer", header, identity, "newer", False),
                ("equal-time", header, identity, "equal", True),
            )
            for name, first_line, expected_identity, state, expected in cases:
                with self.subTest(name=name):
                    forwarded.unlink(missing_ok=True)
                    cache.write_bytes(first_line + b"set -g MARKER last-good\n")
                    dependency.write_text("dependency")
                    os.utime(cache, ns=(2_000_000_000, 2_000_000_000))
                    timestamp = {"old": 1_000_000_000, "equal": 2_000_000_000}.get(
                        state, 3_000_000_000,
                    )
                    os.utime(dependency, ns=(timestamp, timestamp))
                    if state == "missing":
                        dependency.unlink()
                    arguments = ["--destination", str(cache), "--dependency", str(dependency)]
                    if expected_identity is not None:
                        arguments += ["--identity", expected_identity]
                    arguments += ["--", "producer"]
                    native = subprocess.run(
                        [shutil.which("fish"), "--no-config", "-c",
                         function + "\nrefresh-fish-cache $argv", "--", *arguments],
                        env=os.environ | {"PATH": str(temporary), "FORWARDED": str(forwarded)},
                        text=True, capture_output=True, timeout=10,
                    )
                    self.assertEqual(0 if expected else 23, native.returncode, native.stderr)
                    self.assertEqual(not expected, forwarded.exists())
                    self.assertEqual(
                        expected, shell_cache.fresh(cache, [dependency], expected_identity),
                    )
                    if not expected:
                        self.assertEqual(repr(arguments), forwarded.read_text())


if __name__ == "__main__":
    unittest.main()
