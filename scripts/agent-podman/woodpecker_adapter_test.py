from __future__ import annotations

import importlib.machinery
import importlib.util
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest


ROOT = Path(__file__).resolve().parents[2]
LOADER = importlib.machinery.SourceFileLoader(
    "woodpecker_adapter", str(ROOT / "lib/agent-wrappers/woodpecker-cli")
)
SPEC = importlib.util.spec_from_loader(LOADER.name, LOADER)
assert SPEC is not None
MODULE = importlib.util.module_from_spec(SPEC)
LOADER.exec_module(MODULE)


class ParseExecTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.repo = Path(self.temp.name) / "repo"
        self.repo.mkdir()
        self.inside = self.repo / "pipeline.yml"
        self.inside.write_text("steps: []\n")
        self.outside = Path(self.temp.name) / "generated.yml"
        self.outside.write_text("steps: []\n")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_parses_equals_repo_path_and_inside_pipeline(self) -> None:
        repo, pipeline, indexes = MODULE.parse_exec(
            ["exec", f"--repo-path={self.repo}", "--event=manual", str(self.inside)]
        )
        self.assertEqual(repo, self.repo.resolve())
        self.assertEqual(pipeline, self.inside.resolve())
        self.assertEqual(indexes, [1, 3])

    def test_parses_separate_repo_path_and_outside_pipeline(self) -> None:
        _, pipeline, indexes = MODULE.parse_exec(
            ["exec", "--repo-path", str(self.repo), str(self.outside)]
        )
        self.assertEqual(pipeline, self.outside.resolve())
        self.assertEqual(indexes, [1, 2, 3])

    def test_rejects_unsupported_forms(self) -> None:
        cases = (
            ["lint"],
            ["exec", str(self.inside)],
            ["exec", f"--repo-path={self.repo}", "--local=false", str(self.inside)],
            ["exec", f"--repo-path={self.repo}", f"--repo-path={self.repo}", str(self.inside)],
            ["exec", f"--repo-path={self.repo}", "--secrets-file=local.yml", str(self.inside)],
            ["exec", f"--repo-path={self.repo}", "--metadata-file", "local.json", str(self.inside)],
        )
        for argv in cases:
            with self.subTest(argv=argv), self.assertRaises(MODULE.UsageError):
                MODULE.parse_exec(argv)

    def test_argument_encoding_preserves_shell_metacharacters(self) -> None:
        argv = ["exec", "space value", "quote'", "$HOME; touch nope", "line\nbreak"]
        self.assertEqual(MODULE.encode_argv(argv).split(b"\0")[:-1], [os.fsencode(x) for x in argv])

    def test_malformed_connection_port_is_a_usage_error(self) -> None:
        old_host = os.environ.get("CONTAINER_HOST")
        os.environ["CONTAINER_HOST"] = "ssh://agentbuilder@relay:not-a-port/socket"
        try:
            with self.assertRaises(MODULE.UsageError):
                MODULE.ssh_target()
        finally:
            if old_host is None:
                os.environ.pop("CONTAINER_HOST", None)
            else:
                os.environ["CONTAINER_HOST"] = old_host

    def test_ssh_requires_the_pinned_host_alias(self) -> None:
        key = Path(self.temp.name) / "key"
        known_hosts = Path(self.temp.name) / "known_hosts"
        key.touch()
        known_hosts.write_text("agent-podman ssh-ed25519 AAAA\n")
        names = ("CONTAINER_HOST", "CONTAINER_SSHKEY", "AGENT_PODMAN_KNOWN_HOSTS")
        previous = {name: os.environ.get(name) for name in names}
        os.environ.update(
            {
                "CONTAINER_HOST": "ssh://agentbuilder@192.0.2.1:2222/socket",
                "CONTAINER_SSHKEY": str(key),
                "AGENT_PODMAN_KNOWN_HOSTS": str(known_hosts),
            }
        )
        try:
            command, user = MODULE.ssh_target()
        finally:
            for name, value in previous.items():
                if value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value
        self.assertEqual(user, "agentbuilder")
        self.assertIn("StrictHostKeyChecking=yes", command)
        self.assertIn(f"UserKnownHostsFile={known_hosts}", command)
        self.assertIn("HostKeyAlias=agent-podman", command)


class SupervisorTest(unittest.TestCase):
    RUN_ID = "1234567890abcdef1234567890abcdef"

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.home = Path(self.temp.name)
        self.bin = self.home / "fake-bin"
        self.bin.mkdir()
        podman = self.bin / "podman"
        podman.write_text("#!/bin/sh\nexit 0\n")
        podman.chmod(0o755)
        setsid = self.bin / "setsid"
        setsid.write_text(
            f"#!{sys.executable}\n"
            "import os, sys\n"
            "os.setsid()\n"
            "os.execvp(sys.argv[1], sys.argv[1:])\n"
        )
        setsid.chmod(0o755)
        self.cli = self.home / ".local/bin/woodpecker-cli"
        self.cli.parent.mkdir(parents=True)
        self.env = os.environ.copy()
        self.env["HOME"] = str(self.home)
        self.env["PATH"] = f"{self.bin}:{self.env['PATH']}"
        self.supervisor = ROOT / "lib/agent-podman/woodpecker-supervisor.sh"
        self.run_dir = self.home / ".local/state/agent-podman/woodpecker-runs" / self.RUN_ID
        self.command("prepare")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def command(self, operation: str, *, input: bytes | None = None) -> subprocess.CompletedProcess[bytes]:
        return subprocess.run(
            [self.supervisor, operation, self.RUN_ID],
            input=input,
            env=self.env,
            check=True,
            capture_output=True,
        )

    def test_run_preserves_arguments_exactly(self) -> None:
        self.cli.write_text(
            f"#!{sys.executable}\n"
            "import os, sys\n"
            "assert os.environ['WOODPECKER_BACKEND_DOCKER_HOST'].endswith('/podman/podman.sock')\n"
            "sys.stdout.buffer.write(b'\\0'.join(os.fsencode(x) for x in sys.argv[1:]) + b'\\0')\n"
        )
        self.cli.chmod(0o755)
        argv = ["exec", "--commit-message", "space; $HOME ' quote\nline", "pipeline.yml"]
        result = self.command("run", input=MODULE.encode_argv(argv))
        self.assertEqual(result.stdout.split(b"\0")[:-1], [os.fsencode(x) for x in argv])
        self.assertFalse(self.run_dir.exists())

    def test_signal_waits_for_child_before_cleanup(self) -> None:
        ready = self.home / "ready"
        self.cli.write_text(
            f"#!{sys.executable}\n"
            "import os, signal, sys, time\n"
            f"ready = {str(ready)!r}\n"
            "def stop(_signum, _frame):\n"
            "    time.sleep(0.4)\n"
            "    sys.exit(42)\n"
            "signal.signal(signal.SIGTERM, stop)\n"
            "open(ready, 'w').close()\n"
            "while True: time.sleep(1)\n"
        )
        self.cli.chmod(0o755)
        process = subprocess.Popen(
            [self.supervisor, "run", self.RUN_ID],
            stdin=subprocess.PIPE,
            env=self.env,
        )
        assert process.stdin is not None
        process.stdin.write(MODULE.encode_argv(["exec", "pipeline.yml"]))
        process.stdin.close()
        deadline = time.monotonic() + 3
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertTrue(ready.exists())
        process.send_signal(signal.SIGTERM)
        time.sleep(0.1)
        self.assertTrue(self.run_dir.exists())
        self.assertEqual(process.wait(timeout=3), 42)
        self.assertFalse(self.run_dir.exists())

    def test_reaper_removes_only_old_abandoned_runs(self) -> None:
        root = self.run_dir.parent
        old_run = root / "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        young_run = root / "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
        live_run = root / "cccccccccccccccccccccccccccccccc"
        old_run.mkdir()
        young_run.mkdir()
        live_run.mkdir()
        (live_run / "pid").write_text(f"{os.getpid()}\n")
        old_time = time.time() - 25 * 60 * 60
        os.utime(old_run, (old_time, old_time))
        os.utime(live_run, (old_time, old_time))
        subprocess.run(
            [self.supervisor, "reap", "0" * 32],
            env=self.env,
            check=True,
            capture_output=True,
        )
        self.assertFalse(old_run.exists())
        self.assertTrue(young_run.exists())
        self.assertTrue(live_run.exists())
        self.assertTrue(self.run_dir.exists())


if __name__ == "__main__":
    unittest.main()
