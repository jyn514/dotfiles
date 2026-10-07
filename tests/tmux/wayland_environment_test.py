"""Exercise Wayland refresh with real tmux clients on a disposable server."""

import os
from pathlib import Path
import selectors
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
import uuid


ROOT = Path(__file__).resolve().parents[2]


@unittest.skipUnless(shutil.which("tmux"), "tmux is required")
class WaylandEnvironmentTest(unittest.TestCase):
    def setUp(self) -> None:
        self.socket = f"wayland-test-{uuid.uuid4().hex}"
        self.environment = os.environ | {"TERM": "xterm-256color"}
        self.environment.pop("TMUX", None)
        self.environment.pop("WAYLAND_DISPLAY", None)
        self.addCleanup(self.tmux, "kill-server", check=False)
        with tempfile.NamedTemporaryFile(mode="w", suffix=".conf") as config:
            refresh = next(
                line for line in (ROOT / "config/tmux/tmux.conf").read_text().splitlines()
                if line.startswith("set-option -g update-environment ")
            )
            config.write(refresh + "\n")
            config.flush()
            self.tmux("-f", config.name, "new-session", "-d", "-s", "test")
        self.assertEqual(refresh.rsplit(" ", 1)[1].split(","), self.tmux(
            "show-options", "-gv", "update-environment"
        ).stdout.splitlines())

    def tmux(self, *arguments: str, check: bool = True, environment=None):
        return subprocess.run(
            ["tmux", "-L", self.socket, *arguments],
            env=self.environment if environment is None else environment,
            check=check, capture_output=True, text=True, timeout=10,
        )

    def attach(self, display: str | None) -> None:
        environment = self.environment.copy()
        if display is not None:
            environment["WAYLAND_DISPLAY"] = display
        client = subprocess.Popen(
            ["tmux", "-L", self.socket, "-C", "attach-session", "-t", "test"],
            env=environment, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        try:
            # Read raw chunks: buffered readline can hide already-read messages
            # from select, making attachment depend on timing.
            with selectors.DefaultSelector() as selector:
                selector.register(client.stdout, selectors.EVENT_READ)
                output = b""
                deadline = time.monotonic() + 10
                while b"%session-changed " not in output:
                    self.assertGreater(deadline - time.monotonic(), 0, output)
                    if selector.select(max(0, deadline - time.monotonic())):
                        chunk = os.read(client.stdout.fileno(), 65536)
                        self.assertTrue(chunk, output)
                        output += chunk
            self.tmux("detach-client", "-s", "test")
            client.communicate(timeout=10)
            self.assertEqual(client.returncode, 0)
        finally:
            if client.poll() is None:
                client.kill()
                client.communicate()

    def assert_new_pane_display(self, expected: str) -> None:
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory) / "environment.py"
            result = Path(directory) / "display"
            script.write_text(
                "import os, pathlib, subprocess, sys, time\n"
                "pathlib.Path(sys.argv[1]).write_text(os.environ.get('WAYLAND_DISPLAY', 'unset'))\n"
                "subprocess.run(['tmux', 'wait-for', '-S', 'environment-ready'], check=True)\n"
                "time.sleep(30)\n"
            )
            self.tmux("new-window", "-d", "-t", "test", sys.executable,
                      str(script), str(result))
            self.tmux("wait-for", "environment-ready")
            self.assertEqual(expected, result.read_text())

    def test_reattach_refreshes_display_and_ssh_preserves_latest_value(self) -> None:
        self.tmux("set-environment", "-g", "WAYLAND_DISPLAY", "wayland-0")
        self.tmux("set-environment", "-t", "test", "WAYLAND_DISPLAY", "wayland-0")
        self.attach("wayland-1")
        self.assert_new_pane_display("wayland-1")
        self.attach(None)
        self.assert_new_pane_display("wayland-1")
        self.attach("wayland-2")
        self.assert_new_pane_display("wayland-2")

    def test_ssh_preserves_global_display_without_a_session_override(self) -> None:
        self.tmux("set-environment", "-g", "WAYLAND_DISPLAY", "wayland-0")
        self.attach(None)
        self.assert_new_pane_display("wayland-0")

    def test_new_session_receives_display_even_when_server_started_without_it(self) -> None:
        self.tmux("new-session", "-d", "-s", "desktop",
                  environment=self.environment | {"WAYLAND_DISPLAY": "wayland-1"})
        self.assertEqual("WAYLAND_DISPLAY=wayland-1\n", self.tmux(
            "show-environment", "-t", "desktop", "WAYLAND_DISPLAY"
        ).stdout)


if __name__ == "__main__":
    unittest.main()
