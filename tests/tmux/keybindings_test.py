import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import unittest


ROOT = Path(__file__).resolve().parents[2]


@unittest.skipUnless(shutil.which("tmux"), "tmux is unavailable")
class KeybindingTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.socket = str(self.directory / "tmux.sock")
        self.input_log = self.directory / "input"
        self.copy_log = self.directory / "copies"
        self.addCleanup(self.stop_server)

        # A real terminal application lets the test observe forwarded keys and
        # enter/leave the alternate screen without depending on an editor.
        application = self.directory / "application.py"
        application.write_text(
            "import os, sys, tty\n"
            "tty.setraw(0)\n"
            "for i in range(150):\n"
            "    os.write(1, f'line {i}\\r\\n'.encode())\n"
            f"with open({str(self.input_log)!r}, 'ab', buffering=0) as log:\n"
            "    while True:\n"
            "        data = os.read(0, 1024)\n"
            "        if not data:\n"
            "            break\n"
            "        log.write(data)\n"
            "        if data == b'a':\n"
            "            os.write(1, b'\\x1b[?1049h')\n"
            "        elif data == b'n':\n"
            "            os.write(1, b'\\x1b[?1049l')\n"
        )
        copy = self.directory / "copy-terminal-selection"
        copy.write_text(
            "#!/usr/bin/env python3\n"
            "import subprocess, sys\n"
            "data = sys.stdin.buffer.read()\n"
            f"with open({str(self.copy_log)!r}, 'ab') as log:\n"
            "    log.write(data + b'\\n')\n"
            f"subprocess.run(['tmux', '-S', {self.socket!r}, 'load-buffer', '-'], input=b'CLEAN:' + data, check=True)\n"
        )
        copy.chmod(0o755)
        command = shlex.join([sys.executable, str(application)])
        self.tmux("-f", "/dev/null", "new-session", "-d", "-s", "review", command)
        self.tmux("set-environment", "-t", "review", "PATH", f"{self.directory}:{os.environ['PATH']}")

        source = (ROOT / "config/tmux/tmux.conf").read_text()
        # Load the real keybinding blocks, but not startup hooks, TPM or
        # environment scripts. They are unrelated and can have side effects.
        config = "set -g prefix " + source.split("set -g prefix ", 1)[1].splitlines()[0] + "\n"
        config += "set-window-option -g mode-keys vi\n"
        for start, end in (
            ("bind-key -T copy-mode-vi v ", "# https://stackoverflow.com/a/53745309/7669110"),
            ('bind-key t new-window -c ', "# like ctrl+o in vscode"),
            ("# Plain Page Up scrolls tmux history", "# keep emacs bindings in vi mode"),
        ):
            config += source[source.index(start):source.index(end)] + "\n"
        file = self.directory / "bindings.conf"
        file.write_text(config)
        # Seed the replaced root bindings to verify removal on config reload.
        self.tmux("bind-key", "-T", "root", "C-PPage", "previous-window")
        self.tmux("bind-key", "-T", "root", "C-NPage", "next-window")
        self.tmux("source-file", str(file))

        # -K injects through client key tables, unlike ordinary send-keys.
        commands = self.tmux("list-commands")
        send_keys = next(line for line in commands.splitlines() if line.startswith("send-keys "))
        if "K" not in send_keys.split("]", 1)[0]:
            self.skipTest("tmux send-keys -K is unavailable")
        output = open(self.directory / "client-output", "wb")
        self.addCleanup(output.close)
        self.client_process = subprocess.Popen(
            ["tmux", "-S", self.socket, "-C", "attach-session", "-t", "review"],
            stdin=subprocess.PIPE, stdout=output, stderr=output,
        )
        self.addCleanup(self.stop_client)
        self.wait_for(lambda: bool(self.tmux("list-clients", "-F", "#{client_name}")))
        self.client = self.tmux("list-clients", "-F", "#{client_name}").splitlines()[0]
        self.wait_for(lambda: int(self.value("#{history_size}")) > 50)

    def stop_client(self):
        self.client_process.terminate()
        self.client_process.wait(timeout=5)
        if self.client_process.stdin:
            self.client_process.stdin.close()

    def stop_server(self):
        subprocess.run(["tmux", "-S", self.socket, "kill-server"], capture_output=True)

    def tmux(self, *args):
        result = subprocess.run(
            ["tmux", "-S", self.socket, *args],
            capture_output=True, text=True, timeout=5,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.strip()

    def value(self, format):
        return self.tmux("display-message", "-p", "-t", "review", format)

    def wait_for(self, predicate):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if predicate():
                return
            time.sleep(0.02)
        received = self.input_log.read_bytes() if self.input_log.exists() else b""
        self.fail(f"Timed out waiting for tmux state; application input: {received!r}")

    def press(self, *keys):
        self.tmux("send-keys", "-K", "-c", self.client, *keys)

    def test_page_up_enters_history_and_page_down_pages_in_copy_mode(self):
        self.press("PPage")
        self.wait_for(lambda: self.value("#{pane_in_mode}") == "1")
        offset = int(self.value("#{scroll_position}"))
        self.assertGreater(offset, 0)
        self.press("PPage")
        self.wait_for(lambda: int(self.value("#{scroll_position}")) > offset)
        self.press("NPage")
        self.wait_for(lambda: int(self.value("#{scroll_position}")) == offset)

    def test_alt_page_keys_switch_sessions_on_normal_screen(self):
        self.tmux("new-session", "-d", "-s", "a-before", "sleep 90")
        self.tmux("new-session", "-d", "-s", "z-after", "sleep 90")
        for key, session in (
            ("M-NPage", "z-after"),
            ("M-PPage", "review"),
            ("M-PPage", "a-before"),
            ("M-NPage", "review"),
        ):
            self.press(key)
            self.wait_for(lambda: self.tmux("list-clients", "-F", "#{client_session}") == session)

    def test_old_ctrl_page_bindings_are_removed_on_reload(self):
        for key in ("C-PPage", "C-NPage"):
            result = subprocess.run(
                ["tmux", "-S", self.socket, "list-keys", "-T", "root", key],
                capture_output=True,
            )
            self.assertNotEqual(result.returncode, 0, key)

    def test_page_up_is_forwarded_but_alt_page_switches_sessions_in_alternate_screen(self):
        self.tmux("new-session", "-d", "-s", "z-after", "sleep 90")
        self.tmux("send-keys", "-t", "review", "a")
        self.wait_for(lambda: self.value("#{alternate_on}") == "1")
        self.press("PPage")
        self.wait_for(lambda: self.input_log.read_bytes() == b'a\x1b[5~')
        self.assertEqual(self.value("#{pane_in_mode}"), "0")
        self.press("M-NPage")
        self.wait_for(lambda: self.tmux("list-clients", "-F", "#{client_session}") == "z-after")
        self.press("M-PPage")
        self.wait_for(lambda: self.tmux("list-clients", "-F", "#{client_session}") == "review")
        self.assertEqual(self.value("#{alternate_on}"), "1")
        self.tmux("send-keys", "-t", "review", "n")
        self.wait_for(lambda: self.value("#{alternate_on}") == "0")
        self.press("PPage")
        self.wait_for(lambda: self.value("#{pane_in_mode}") == "1")

    def test_alt_page_keys_do_not_switch_sessions_in_copy_mode(self):
        self.tmux("new-session", "-d", "-s", "other", "sleep 90")
        self.press("PPage")
        self.wait_for(lambda: self.value("#{pane_in_mode}") == "1")
        self.press("M-PPage", "M-NPage")
        self.assertEqual(self.tmux("list-clients", "-F", "#{client_session}"), "review")
        self.assertEqual(self.value("#{pane_in_mode}"), "1")

    def test_prefix_backspace_toggles_previous_active_window(self):
        first = self.value("#{window_id}")
        self.tmux("new-window", "-n", "other", "sleep 90")
        other = self.value("#{window_id}")
        self.press("C-k", "BSpace")
        self.wait_for(lambda: self.value("#{window_id}") == first)
        self.press("C-k", "BSpace")
        self.wait_for(lambda: self.value("#{window_id}") == other)

    def test_enter_matches_y_cleanup_in_both_copy_mode_tables(self):
        vi_y = self.tmux("list-keys", "-T", "copy-mode-vi", "y")
        action = vi_y[vi_y.index("send-keys"):]
        for table in ("copy-mode", "copy-mode-vi"):
            with self.subTest(table=table):
                enter = self.tmux("list-keys", "-T", table, "Enter")
                self.assertEqual(enter[enter.index("send-keys"):], action)

    def test_enter_calls_cleanup_and_publishes_cleaned_selection(self):
        version = re.match(r"tmux (\d+)\.(\d+)", self.tmux("-V"))
        if version and tuple(map(int, version.groups())) < (3, 6):
            self.skipTest("existing copy-mode -CP flags require tmux 3.6")
        for table in ("copy-mode", "copy-mode-vi"):
            with self.subTest(table=table):
                self.tmux("set-window-option", "mode-keys", "vi" if table.endswith("-vi") else "emacs")
                self.tmux("copy-mode")
                self.tmux("send-keys", "-X", "history-top")
                self.tmux("send-keys", "-X", "select-line")
                self.press("Enter")
                self.wait_for(lambda: self.value("#{pane_in_mode}") == "0")
                self.wait_for(lambda: self.copy_log.exists() and bool(self.copy_log.read_bytes()))
                self.wait_for(lambda: self.tmux("show-buffer").startswith("CLEAN:"))
                self.copy_log.unlink()


if __name__ == "__main__":
    unittest.main()
