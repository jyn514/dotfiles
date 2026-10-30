"""Exercise interrupt provenance through a private controlling terminal."""
import errno
import fcntl
import json
import os
from pathlib import Path
import pty
import select
import shlex
import signal
import sys
import tempfile
import termios
import time
import unittest

ROOT = Path(__file__).resolve().parents[3]
FIXTURE = Path(__file__).parent / "fixtures/terminal_child.py"


def terminal_scenario(
    root: Path, phase: str, *, native: bool = False, shell_wait: bool = False,
    runner_override: Path | None = None, legacy: bool = False,
) -> dict:
    with tempfile.TemporaryDirectory() as temporary:
        log = Path(temporary) / "events.jsonl"
        log.touch()
        command = shlex.join([sys.executable, str(FIXTURE), str(log), phase])
        if shell_wait:
            command += "; :"
        interval = "30" if phase == "interval" or legacy else ".2"
        invocation = (["/bin/watch", "-n", interval, command] if native else
                      [str(root / "bin/watch"), "-n", interval, "-x", "/bin/sh", command])
        environment = dict(os.environ)
        environment.pop("WATCH_RUNNER", None)
        if runner_override is not None:
            environment["WATCH_RUNNER"] = str(runner_override)
        environment.update(TERM="xterm", SHELL="/bin/sh", WATCH_TEST_OVERRIDE_LOG=str(log))
        master, slave = pty.openpty()
        original = termios.tcgetattr(slave)
        pid = os.fork()
        if pid == 0:
            os.close(master)
            os.setsid()
            fcntl.ioctl(slave, termios.TIOCSCTTY, 0)
            for fd in (0, 1, 2):
                os.dup2(slave, fd)
            if slave > 2:
                os.close(slave)
            os.execvpe(invocation[0], invocation, environment)
        reaped = False
        output = bytearray()

        def events() -> list[dict]:
            return [json.loads(line) for line in log.read_text().splitlines()]

        def drain() -> None:
            while select.select([master], [], [], 0)[0]:
                try:
                    data = os.read(master, 65536)
                except OSError as error:
                    if error.errno == errno.EIO:
                        return
                    raise
                if not data:
                    return
                output.extend(data)

        def until(predicate, timeout: float = 3) -> None:
            deadline = time.monotonic() + timeout
            while not predicate():
                drain()
                if time.monotonic() >= deadline:
                    raise AssertionError(f"terminal scenario timed out: {events()!r}, {bytes(output)!r}")
                time.sleep(.01)

        try:
            until(lambda: any(event["event"] == "start" for event in events()))
            if phase == "interval":
                until(lambda: any(event["event"] == "done" for event in events()) and b"child started" in output)
            elif phase != "override":
                os.write(master, b"ordinary input 123\n")
                until(lambda: any(event["event"] == "input" for event in events()))
            during = termios.tcgetattr(slave)
            intr = during[6][termios.VINTR]
            started = time.monotonic()
            os.write(master, bytes([intr]) if isinstance(intr, int) else intr)
            first_interrupt_restored = None
            if legacy:
                until(lambda: b"[exit 130]" in output)
                first_interrupt_restored = termios.tcgetattr(slave) == original
                waited, _ = os.waitpid(pid, os.WNOHANG)
                if waited:
                    reaped = True
                    raise AssertionError("legacy watch unexpectedly quit on the command interrupt")
                # Legacy callers keep their first-interrupt frame behavior, but
                # a second interrupt in the interval must exit and restore.
                intr = termios.tcgetattr(slave)[6][termios.VINTR]
                os.write(master, bytes([intr]) if isinstance(intr, int) else intr)
            status = None
            deadline = time.monotonic() + 1.5
            while time.monotonic() < deadline:
                drain()
                waited, raw_status = os.waitpid(pid, os.WNOHANG)
                if waited:
                    reaped = True
                    status = os.waitstatus_to_exitcode(raw_status)
                    break
                time.sleep(.01)
            drain()
            recorded = events()
            children_alive = []
            for child in {event["pid"] for event in recorded}:
                try:
                    os.kill(child, 0)
                    children_alive.append(child)
                except ProcessLookupError:
                    pass
            return dict(status=status, elapsed=time.monotonic() - started,
                        first_interrupt_restored=first_interrupt_restored,
                        original=repr(original), during=repr(during), restored=repr(termios.tcgetattr(slave)),
                        events=recorded, children_alive=children_alive, output=repr(bytes(output)))
        finally:
            # Only private process groups allocated by this scenario are owned.
            for group in {pid} | {event["pgid"] for event in events()}:
                try:
                    os.killpg(group, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            if not reaped:
                os.waitpid(pid, 0)
            os.close(master)
            os.close(slave)


@unittest.skipUnless(sys.platform.startswith("linux"), "private-terminal acceptance currently verified on Linux")
class TerminalInterruptTests(unittest.TestCase):
    def test_explicit_helper_override_keeps_legacy_interrupt_behavior(self) -> None:
        result = terminal_scenario(ROOT, "running", runner_override=ROOT / "libexec/runinpty.py", legacy=True)
        self.assertEqual(130, result["status"], result)
        self.assertTrue(result["first_interrupt_restored"], result)
        self.assertEqual(result["original"], result["restored"], result)
        self.assertEqual([], result["children_alive"], result)

    def test_arbitrary_override_keeps_shell_first_and_noncooperative_cancellation(self) -> None:
        result = terminal_scenario(ROOT, "override", runner_override=Path(__file__).parent / "fixtures/override_runner.py")
        self.assertEqual(130, result["status"], result)
        self.assertEqual(result["original"], result["restored"], result)
        self.assertEqual([], result["children_alive"], result)
        argv = result["events"][0]["argv"]
        self.assertEqual(["/bin/sh", "-c"], argv[:2], result)
        self.assertEqual(3, len(argv), result)

    def test_interrupt_drains_cooperative_final_output_before_reaping(self) -> None:
        result = terminal_scenario(ROOT, "final-output")
        self.assertEqual(130, result["status"], result)
        self.assertTrue(any(event["event"] == "output-complete" for event in result["events"]), result)
        self.assertEqual(result["original"], result["restored"], result)
        self.assertEqual([], result["children_alive"], result)
        self.assertIn("\\x1b[?1049l", result["output"], result)
        self.assertEqual(1, sum(event["event"] == "start" for event in result["events"]), result)

    def test_one_terminal_interrupt_quits_restores_and_reaps_without_losing_input(self) -> None:
        for phase, shell_wait in (("running", False), ("running", True), ("interval", False)):
            with self.subTest(phase=phase, shell_wait=shell_wait):
                result = terminal_scenario(ROOT, phase, shell_wait=shell_wait)
                self.assertEqual(130, result["status"], result)
                self.assertEqual(result["original"], result["restored"], result)
                self.assertEqual([], result["children_alive"], result)
                self.assertIn("\\x1b[?1049l", result["output"], result)
                self.assertEqual(1, sum(event["event"] == "start" for event in result["events"]), result)
                if phase == "running":
                    self.assertEqual(["ordinary input 123\n"], [event["text"] for event in result["events"] if event["event"] == "input"], result)
                    self.assertTrue(any(event["event"] == "SIGINT" for event in result["events"]), result)


if __name__ == "__main__":
    unittest.main()
