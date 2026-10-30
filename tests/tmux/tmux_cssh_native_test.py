"""Exercise target resolution from a real shell on an owned tmux server."""

import json
import os
from pathlib import Path
import pty
import select
import shlex
import shutil
import subprocess
import tempfile
import time
import unittest


ROOT = Path(__file__).resolve().parents[2]
TMUX = shutil.which("tmux")
COMMAND = Path(os.environ.get("DOTFILES_TEST_TMUX_CSSH", ROOT / "bin/tmux-cssh"))
HELPER = Path(__file__).with_name("fixtures") / "stay-alive.sh"


@unittest.skipUnless(TMUX, "native tmux is unavailable")
class NativeTargetTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="tmux-cssh-")
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.socket = self.directory / "socket"
        self.environment = {
            key: value for key, value in os.environ.items()
            if key not in {"TMUX", "TMUX_PANE", "TMUX_TMPDIR", "ENV", "BASH_ENV"}
        } | {"TERM": "xterm", "SHELL": "/bin/sh"}
        wrapper = self.directory / "tmux"
        wrapper.write_text(
            "#!/bin/sh\nexec " + shlex.join([TMUX, "-S", str(self.socket)]) + ' "$@"\n'
        )
        wrapper.chmod(0o755)
        self.environment["PATH"] = f"{self.directory}:{os.environ['PATH']}"
        self.addCleanup(self.stop_server)
        self.tmux("-f", "/dev/null", "new-session", "-d", "-s", "work", "-n", "shell",
                  "-x", "160", "-y", "60", "/bin/sh")
        self.shell = self.tmux("display-message", "-p", "-t", "work:shell", "#{pane_id}")
        self.work = self.tmux("display-message", "-p", "-t", self.shell, "#{session_id}")
        if os.environ.get("DOTFILES_TEST_TMUX_EVIDENCE"):
            pid = self.tmux("display-message", "-p", "#{pid}")
            executable = Path(f"/proc/{pid}/exe")
            self.record("runtime", [{
                "launched_executable": TMUX,
                "running_executable": str(executable.resolve()) if executable.exists() else None,
                "server_version": self.tmux("display-message", "-p", "#{version}"),
            }])
        master, slave = pty.openpty()
        self.master = master
        self.client = subprocess.Popen(
            [TMUX, "-S", str(self.socket), "attach-session", "-t", self.work],
            env=self.environment, stdin=slave, stdout=slave, stderr=slave,
        )
        os.close(slave)
        self.addCleanup(self.stop_client)

    def tmux(self, *arguments: str) -> str:
        result = subprocess.run(
            [TMUX, "-S", str(self.socket), *arguments], env=self.environment,
            text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True,
        )
        return result.stdout.strip()

    def stop_client(self) -> None:
        self.client.terminate()
        self.client.wait(timeout=5)
        os.close(self.master)

    def stop_server(self) -> None:
        subprocess.run([TMUX, "-S", str(self.socket), "kill-server"],
                       env=self.environment, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def invoke(self, *arguments: str) -> None:
        # Type the normal command into an existing shell; do not replace a pane.
        done = self.directory / "done"
        done.unlink(missing_ok=True)
        command = shlex.join([str(COMMAND), "-c", str(HELPER), *arguments])
        command += f'; printf "%s" "$?" > {shlex.quote(str(done))}'
        self.tmux("send-keys", "-t", self.shell, "-l", command)
        self.tmux("send-keys", "-t", self.shell, "Enter")
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if select.select([self.master], [], [], 0.02)[0]:
                os.read(self.master, 65536)
            if done.exists() and done.read_text():
                self.assertEqual("0", done.read_text(), self.tmux("capture-pane", "-p", "-t", self.shell))
                return
        self.fail(self.tmux("capture-pane", "-p", "-t", self.shell))

    def snapshot(self) -> list[dict]:
        rows = self.tmux("list-panes", "-a", "-F",
                         "#{session_id}|#{session_name}|#{window_id}|#{window_name}|#{pane_id}|#{pane-border-format}|#{synchronize-panes}|#{pane-border-status}|#{remain-on-exit}|#{detach-on-destroy}")
        fields = ("session", "session_name", "window", "window_name", "pane", "label", "sync", "border", "remain", "detach")
        return [dict(zip(fields, row.split("|"))) for row in rows.splitlines()]

    def record(self, name: str, rows: list[dict]) -> None:
        # Optional retained receipts for baseline/candidate comparison, never the oracle.
        destination = os.environ.get("DOTFILES_TEST_TMUX_EVIDENCE")
        if destination:
            path = Path(destination)
            path.mkdir(parents=True, exist_ok=True)
            (path / f"{name}.json").write_text(json.dumps(rows, indent=2) + "\n")

    def test_new_session_does_not_target_same_named_window_in_origin_session(self) -> None:
        self.invoke("-w", "first")
        before = self.snapshot()
        old_window = next(row["window"] for row in before if row["window_name"] == "cssh-0")
        self.tmux("select-window", "-t", self.shell)
        self.invoke("first", "second", "third")
        rows = self.snapshot()
        self.record("collision", rows)
        new_rows = [row for row in rows if row["session_name"] == "cssh-0"]
        old_rows = [row for row in rows if row["window"] == old_window]
        self.assertEqual(1, len(old_rows), rows)
        self.assertEqual(3, len(new_rows), rows)
        self.assertEqual({"first", "second", "third"}, {row["label"] for row in new_rows})
        self.assertEqual(1, len({row["window"] for row in new_rows}), rows)
        self.assertEqual({"no-detached"}, {row["detach"] for row in new_rows})
        self.assertEqual([row for row in before if row["window"] == old_window], old_rows)
        for row in new_rows:
            self.assertEqual(("1", "top", "failed"), (row["sync"], row["border"], row["remain"]))
        self.assertEqual(self.tmux("list-clients", "-F", "#{session_id}"), new_rows[0]["session"])

    def test_new_session_without_name_collision(self) -> None:
        self.invoke("first", "second", "third")
        rows = self.snapshot()
        self.record("ordinary-session", rows)
        new_rows = [row for row in rows if row["session"] != self.work]
        self.assertEqual(3, len(new_rows), rows)
        self.assertEqual(["first", "third", "second"], [row["label"] for row in new_rows])
        self.assertEqual({"1"}, {row["sync"] for row in new_rows})

    def test_outside_tmux_attaches_to_the_created_session(self) -> None:
        master, slave = pty.openpty()
        child = subprocess.Popen(
            [str(COMMAND), "-c", str(HELPER), "first", "second"],
            env=self.environment, stdin=slave, stdout=slave, stderr=slave,
        )
        os.close(slave)
        try:
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                if select.select([master], [], [], 0.02)[0]:
                    os.read(master, 65536)
                clients = self.tmux("list-clients", "-F", "#{session_name}").splitlines()
                if "cssh-0" in clients:
                    break
                self.assertIsNone(child.poll(), "command exited before attaching")
            else:
                self.fail("command did not attach to cssh-0")
            rows = self.snapshot()
            self.record("outside-attach", rows)
            new_rows = [row for row in rows if row["session_name"] == "cssh-0"]
            self.assertEqual(["first", "second"], [row["label"] for row in new_rows])
            self.assertEqual({"1"}, {row["sync"] for row in new_rows})
            self.tmux("detach-client", "-s", new_rows[0]["session"])
            self.assertEqual(0, child.wait(timeout=5))
        finally:
            if child.poll() is None:
                child.terminate()
                child.wait(timeout=5)
            os.close(master)

    def test_new_window_keeps_current_session_and_exact_dotted_name(self) -> None:
        self.invoke("-w", "-n", "cssh.", "first", "second", "third")
        rows = self.snapshot()
        self.record("ordinary-window", rows)
        new_rows = [row for row in rows if row["window_name"] == "cssh.-0"]
        self.assertEqual(3, len(new_rows), rows)
        self.assertEqual({self.work}, {row["session"] for row in rows})
        self.assertEqual(["first", "third", "second"], [row["label"] for row in new_rows])
        self.assertEqual({"1"}, {row["sync"] for row in new_rows})


if __name__ == "__main__":
    unittest.main()
