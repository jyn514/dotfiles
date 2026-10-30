import json
import os
from pathlib import Path
import signal
import shutil
import socket
import subprocess
import sys
import tempfile
import tomllib
import unittest


ROOT = Path(__file__).resolve().parents[3]


class CommandIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)

    def executable(self, name: str, contents: str) -> None:
        path = self.directory / name
        path.write_text("#!/bin/sh\n" + contents)
        path.chmod(0o755)

    def test_native_zenity_window_association(self) -> None:
        required = ("zenity", "wmctrl", "Xvfb", "openbox", "xprop", "dbus-run-session")
        missing = [name for name in required if shutil.which(name) is None]
        if missing:
            self.skipTest("native X11 probe requires " + ", ".join(missing))
        environment = os.environ.copy()
        for name in ("DISPLAY", "WAYLAND_DISPLAY", "DBUS_SESSION_BUS_ADDRESS", "DBUS_SYSTEM_BUS_ADDRESS"):
            environment.pop(name, None)
        result = subprocess.run(
            ["dbus-run-session", "--", sys.executable,
             str(Path(__file__).with_name("native_window_namespace.py")),
             str(Path(__file__).parents[1] / "take_a_break/main.py")],
            env=environment,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_take_a_break_matches_the_window_pid_field(self) -> None:
        calls = self.directory / "wmctrl-calls"
        dialog_pid = self.directory / "dialog-pid"
        self.executable("zenity", 'printf "%s\\n" "$$" > "$DIALOG_PID"\n')
        self.executable(
            "wmctrl",
            'if [ "$1" = -l ]; then\n'
            '  pid=$(cat "$DIALOG_PID")\n'
            '  printf "0xwrong 0 999 %s title-%s\\n" "$CLIENT_MACHINE" "$pid"\n'
            '  printf "0xremote 0 %s remote.example title\\n" "$pid"\n'
            '  printf "0xright 0 %s %s title\\n" "$pid" "$CLIENT_MACHINE"\n'
            "else\n"
            '  printf "%s\\n" "$*" > "$WMCTRL_CALLS"\n'
            "fi\n",
        )

        result = subprocess.run(
            [str(ROOT / "bin/take-a-break")],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=os.environ | {
                "DIALOG_PID": str(dialog_pid),
                "CLIENT_MACHINE": socket.gethostname(),
                "PATH": f"{self.directory}:{os.environ['PATH']}",
                "WMCTRL_CALLS": str(calls),
            },
        )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("-i -r 0xright -b add,above\n", calls.read_text())


if __name__ == "__main__":
    unittest.main()
