"""Owned X11 acceptance probe; the foreign machine/PID metadata is a fixture."""

import importlib.util
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time


def wait_for(read, ready):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        value = read()
        if ready(value):
            return value
        time.sleep(0.02)
    raise AssertionError(f"native provider did not become ready: {value!r}")


def main(module_path):
    spec = importlib.util.spec_from_file_location("take_a_break_probe", module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    processes = []
    with tempfile.TemporaryDirectory() as directory:
        try:
            with (Path(directory) / "display").open("w+") as display:
                processes.append(subprocess.Popen(
                    ["Xvfb", "-displayfd", str(display.fileno()), "-screen", "0", "800x600x24", "-nolisten", "tcp"],
                    pass_fds=(display.fileno(),), stdout=subprocess.DEVNULL,
                ))
                def read_display():
                    display.seek(0)
                    return display.read().strip()
                number = wait_for(read_display, bool)
            # No inherited display is ever queried, even during readiness checks.
            os.environ["DISPLAY"] = ":" + number
            os.environ["GDK_BACKEND"] = "x11"
            os.environ["GSK_RENDERER"] = "cairo"
            os.environ["GTK_A11Y"] = "none"
            processes.append(subprocess.Popen(["openbox"], stdout=subprocess.DEVNULL))
            wait_for(lambda: subprocess.run(["wmctrl", "-m"], capture_output=True).returncode, lambda code: code == 0)

            def listing():
                return subprocess.check_output(["wmctrl", "-l", "-p"])

            def start_dialog():
                dialog = subprocess.Popen(module.DIALOG_ARGUMENTS)
                processes.append(dialog)
                lines = wait_for(listing, lambda data: any(
                    line.split()[2] == str(dialog.pid).encode() for line in data.splitlines()
                ))
                window = next(line.split()[0] for line in lines.splitlines() if line.split()[2] == str(dialog.pid).encode())
                return dialog, window.decode()

            older, other_window = start_dialog()
            dialog, owned_window = start_dialog()
            # A local, owned Zenity window stands in for a remote client's metadata.
            # This does not claim a real remote host or a second PID namespace.
            subprocess.run(["xprop", "-id", other_window, "-f", "_NET_WM_PID", "32c", "-set", "_NET_WM_PID", str(dialog.pid)], check=True)
            subprocess.run(["xprop", "-id", other_window, "-f", "WM_CLIENT_MACHINE", "8s", "-set", "WM_CLIENT_MACHINE", "remote.example"], check=True)
            lines = listing()
            print("client-list:", lines.decode(), flush=True)
            matches = [line.split() for line in lines.splitlines() if line.split()[2] == str(dialog.pid).encode()]
            assert matches[0][0].decode() == other_window, matches
            assert matches[1][0].decode() == owned_window, matches
            assert matches[1][3] == socket.gethostname().encode(), matches
            module.raise_dialog(dialog.pid)

            def states():
                return [subprocess.check_output(["xprop", "-id", window, "_NET_WM_STATE"]) for window in (other_window, owned_window)]
            observed = wait_for(states, lambda values: any(b"_NET_WM_STATE_ABOVE" in value for value in values))
            print("other-state:", observed[0].decode(), "owned-state:", observed[1].decode(), flush=True)
            assert b"_NET_WM_STATE_ABOVE" not in observed[0], "raised the foreign-metadata window"
            assert b"_NET_WM_STATE_ABOVE" in observed[1], "did not raise the owned dialog"
            subprocess.run(["wmctrl", "-i", "-c", owned_window], check=True)
            status = dialog.wait(timeout=3)
            print("owned-dialog-close-status:", status, flush=True)
            assert module.exit_status(status) == 1, "closing the question should preserve Zenity's cancellation status"
        finally:
            for process in reversed(processes):
                if process.poll() is None:
                    process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()


if __name__ == "__main__":
    main(Path(sys.argv[1]))
