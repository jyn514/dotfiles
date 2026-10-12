"""Wrapper bootstrap follows script targets, but PATH cleanup follows invocation."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
WRAPPERS = ROOT / "libexec/agent-wrappers"
FIXTURES = Path(__file__).with_name("fixtures")


def copy_verified(source: Path, destination: Path) -> None:
    subprocess.run(["cp", str(source), str(destination)], check=True)
    subprocess.run(["cmp", str(source), str(destination)], check=True)
    destination.chmod(0o755)


class SourceDiscoveryTest(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="wrapper discovery ")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.private = self.root / "private"
        self.public = self.root / "opt/agent-tools/bin"
        self.backend = self.root / "backend"
        self.commands = self.root / "commands"
        for directory in (self.private, self.public / "links", self.backend, self.commands):
            directory.mkdir(parents=True)
        for command in ("realpath", "dirname"):
            executable = shutil.which(command)
            self.assertIsNotNone(executable, command)
            (self.commands / command).symlink_to(executable)
        self.realpath = shutil.which("realpath")
        for command in ("rg", "java", "bb"):
            (self.private / command).symlink_to(WRAPPERS / command)
            copy_verified(FIXTURES / "source_backend.sh", self.backend / command)
        # No real-tool overrides: every command must discover its own source
        # before resolving the recording backend on PATH.
        self.env = {
            "PATH": os.pathsep.join(map(str, (self.backend, self.commands))),
            "TMPDIR": str(self.root / "scratch"),
            "REAL_REALPATH": self.realpath,
        }

    def entry(self, command: str, mode: str) -> Path:
        if mode == "direct":
            return WRAPPERS / command
        if mode == "private":
            return self.private / command
        entry = self.public / command
        entry.unlink(missing_ok=True)
        if mode == "absolute":
            entry.symlink_to(self.private / command)
        elif mode == "relative":
            entry.symlink_to("../../../private/" + command)
        else:
            entry.symlink_to("links/" + command)
            link = self.public / "links" / command
            link.unlink(missing_ok=True)
            link.symlink_to("../../../../private/" + command)
        return entry

    def run_wrapper(
        self, command: str, mode: str, *args: str, configured_bb: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        env = dict(self.env)
        entry = self.entry(command, mode)
        env["PATH"] = str(entry.parent) + os.pathsep + env["PATH"]
        if configured_bb:
            env["BB_REAL"] = str(self.backend / "bb")
        return subprocess.run(
            [entry, *args], cwd=self.root, env=env,
            text=True, capture_output=True, check=False, timeout=5,
        )

    def test_source_discovery_through_direct_and_chained_symlink_invocations(self) -> None:
        for command in ("rg", "java", "bb"):
            for mode in ("direct", "private", "absolute", "relative", "relative-chain"):
                with self.subTest(command=command, mode=mode):
                    result = self.run_wrapper(command, mode, "--version")
                    self.assertEqual(0, result.returncode, result.stderr)
                    prefix = {
                        "rg": ["--no-config"],
                        "java": ["-Djava.io.tmpdir=" + self.env["TMPDIR"]],
                        "bb": ["-Djava.io.tmpdir=" + self.env["TMPDIR"]],
                    }[command]
                    self.assertEqual([*prefix, "--version"], result.stdout.splitlines())

    def test_bb_dispatch_discovers_source_with_or_without_configured_backend(self) -> None:
        for configured_bb in (False, True):
            for mode in ("direct", "private", "absolute", "relative", "relative-chain"):
                with self.subTest(configured_bb=configured_bb, mode=mode):
                    result = self.run_wrapper(
                        "bb", mode, "agent-split", "--help", configured_bb=configured_bb,
                    )
                    self.assertEqual(0, result.returncode, result.stderr)
                    self.assertEqual([
                        "-Djava.io.tmpdir=" + self.env["TMPDIR"],
                        str(ROOT / "tools/agent-split/src/scripts/agent-split.clj"),
                        "--help",
                    ], result.stdout.splitlines())

    def test_failed_realpath_output_never_reaches_a_backend(self) -> None:
        (self.commands / "realpath").unlink()
        copy_verified(ROOT / "tests/fixtures/wrapper_realpath_failure.sh",
                      self.commands / "realpath")
        for command in ("rg", "java", "bb"):
            for mode in ("direct", "relative-chain"):
                with self.subTest(command=command, mode=mode):
                    result = self.run_wrapper(command, mode, "--version")
                    self.assertEqual(1, result.returncode, result.stderr)
                    self.assertEqual("", result.stdout)
                    self.assertIn("fixture: realpath failed", result.stderr)
        # With BB_REAL set, source discovery happens at agent-split dispatch.
        result = self.run_wrapper("bb", "relative-chain", "agent-split", "--help",
                                  configured_bb=True)
        self.assertEqual(1, result.returncode, result.stderr)
        self.assertEqual("", result.stdout)
        self.assertIn("fixture: realpath failed", result.stderr)


if __name__ == "__main__":
    unittest.main()
