"""Pi pane identity/foreground policy and native, disposable tmux placement."""

import base64
from concurrent.futures import ThreadPoolExecutor
import importlib.util
import json
import os
import pty
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / "libexec/tmux/place-dashboard-pi.py"
spec = importlib.util.spec_from_file_location("dashboard_placement", HELPER)
placement = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = placement
spec.loader.exec_module(placement)


def registration(pid, session=None, cwd="/unrelated/workspace"):
    return base64.urlsafe_b64encode(json.dumps({"version": 1, "pid": pid,
        "session": session, "cwd": cwd}).encode()).decode().rstrip("=")


class IdentityTests(unittest.TestCase):
    def test_requires_live_foreground_ui_lineage_and_controlling_terminal(self):
        P = placement.Process
        # UI frontend -> Pi, detached workload owner -> worker: the latter must
        # never qualify as the pane UI even if it retains an old metadata PID.
        processes = {10: P(1, 10, 10, "pts/1", "Ss"),
                     11: P(10, 10, 10, "pts/1", "S+"),
                     20: P(1, 20, -1, "?", "Ss"),
                     21: P(20, 21, -1, "?", "S")}
        self.assertTrue(placement.foreground_pi(registration(11), 10, "/dev/pts/1", processes))
        for label, pid, proc in (
            ("background job", 11, P(10, 11, 10, "pts/1", "S")),
            ("suspended foreground UI", 11, P(10, 10, 10, "pts/1", "T")),
            ("zombie", 11, P(10, 10, 10, "pts/1", "Z+")),
            ("other pane terminal", 11, P(10, 10, 10, "pts/2", "S+")),
            ("unrelated process", 11, P(1, 10, 10, "pts/1", "S+")),
            ("detached owner", 20, processes[20]),
            ("guest worker", 21, processes[21]),
        ):
            with self.subTest(label=label):
                self.assertFalse(placement.foreground_pi(registration(pid), 10, "/dev/pts/1",
                    {**processes, pid: proc}))
        self.assertFalse(placement.foreground_pi(registration(999), 10, "/dev/pts/1", processes))
        for invalid in ("bad!", base64.b64encode(b'[]').decode(), registration(True),
                        registration(11, cwd="relative")):
            self.assertFalse(placement.foreground_pi(invalid, 10, "/dev/pts/1", processes))
        # Cwd and conversation persistence are deliberately irrelevant.
        self.assertTrue(placement.foreground_pi(registration(11, "/missing/file.jsonl"),
                                               10, "/dev/pts/1", processes))


@unittest.skipUnless(shutil.which("tmux") and os.name == "posix", "requires native tmux and POSIX PTYs")
class TmuxTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="pi-placement-")
        self.root = Path(self.directory.name)
        self.socket = str(self.root / "tmux.sock")
        self.env = {k: v for k, v in os.environ.items()
                    if k not in ("TMUX", "TMUX_PANE", "PI_DASHBOARD_SPAWN_TOKEN")}
        self.env["TERM"] = "xterm-256color"
        self.clients = []
        self.fixture = self.root / "job.py"
        self.fixture.write_text('''import base64, json, os, signal, subprocess, sys, time
mode, ready = sys.argv[1:]
child = os.fork()
if child == 0:
    if mode in ("background", "stopped"):
        os.setpgid(0, 0)
    while True: time.sleep(1)
time.sleep(.05)
value = {"version": 1, "pid": child, "session": None, "cwd": "/different/workspace"}
if mode == "stale":
    os.kill(child, signal.SIGTERM)
    os.waitpid(child, 0)
elif mode == "stopped":
    os.kill(child, signal.SIGSTOP)
subprocess.run(["tmux", "set-option", "-p", "-t", os.environ["TMUX_PANE"],
                "@resurrect_pi_session", base64.urlsafe_b64encode(json.dumps(value).encode()).decode()], check=True)
with open(ready, "w") as out: out.write(str(child))
while True: time.sleep(1)
''')
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.launcher = self.bin / "codex-sandbox"
        self.launcher.write_text("#!/usr/bin/env python3\nimport json, os, sys, time\n"
            "with open(sys.argv[1], 'w') as out: json.dump({'pid': os.getpid(), 'token': os.environ.get('PI_DASHBOARD_SPAWN_TOKEN')}, out)\n"
            "while True: time.sleep(1)\n")
        self.launcher.chmod(0o700)

    def tearDown(self):
        self.tmux("kill-server", check=False)
        for client, terminal in self.clients:
            client.terminate()
            client.wait(timeout=5)
            os.close(terminal)
        self.directory.cleanup()

    def tmux(self, *args, check=True):
        result = subprocess.run(["tmux", "-S", self.socket, *args], env=self.env,
                                capture_output=True, text=True, timeout=10)
        if check:
            self.assertEqual(result.returncode, 0, f"{args}: {result.stderr}")
        return result.stdout.rstrip("\n")

    def wait_file(self, path):
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            if path.exists() and path.stat().st_size:
                return path.read_text()
            time.sleep(.03)
        self.fail(f"timed out waiting for {path}; panes: " + self.tmux("list-panes", "-a", "-F", "#{pane_id} #{pane_dead} #{pane_current_command}"))

    def session(self, name, mode="foreground"):
        ready = self.root / (name + ".ready")
        pane = self.tmux("-f", "/dev/null", "new-session", "-d", "-s", name, "-P", "-F", "#{pane_id}",
            shlex.join([sys.executable, str(self.fixture), mode, str(ready)]))
        self.wait_file(ready)
        return pane

    def windows(self, session):
        return self.tmux("list-windows", "-t", "=" + session, "-F", "#{window_id}").splitlines()

    def selections(self):
        return self.tmux("list-sessions", "-F", "#{session_id}:#{window_id}:#{pane_id}")

    def spawn(self, token="browser-token", browser=True, session="pi-dashboard"):
        record = self.root / (token + ".json")
        arguments = ["new-window", "-d", "-t", "=" + session, "-P", "-F", "#{pane_id}|#{window_id}"]
        command = ["env", "PATH=" + str(self.bin) + ":" + os.environ["PATH"]]
        if browser:
            command += ["PI_DASHBOARD_SPAWN_TOKEN=" + token]
        command += [str(ROOT / "bin/pi"), str(record)]
        output = self.tmux(*arguments, shlex.join(command))
        self.assertIn("|", output, repr(output))
        pane, window = output.split("|")
        data = json.loads(self.wait_file(record))
        return pane, window, data

    def test_links_same_window_and_process_to_mru_without_changing_selection(self):
        self.session("work")
        self.session("pi-dashboard-prefix")  # eligible despite backing-name prefix
        self.session("work-created-last")
        self.session("pi-dashboard")
        time.sleep(1.1)  # session_activity is native, integer-second tmux state.
        master, slave = pty.openpty()
        client = subprocess.Popen(["tmux", "-S", self.socket, "attach-session", "-t", "=pi-dashboard-prefix"],
            stdin=slave, stdout=slave, stderr=slave, env=self.env)
        os.close(slave)
        self.clients.append((client, master))
        deadline = time.monotonic() + 5
        while not self.tmux("list-clients", "-F", "#{session_id}"):
            self.assertLess(time.monotonic(), deadline)
            time.sleep(.03)
        os.write(master, b"x")  # native client activity, not mocked tmux timestamps
        time.sleep(.1)
        activities = dict(line.split("|") for line in self.tmux("list-sessions", "-F",
            "#{session_name}|#{session_activity}").splitlines())
        self.assertGreater(int(activities["pi-dashboard-prefix"]), int(activities["work-created-last"]))
        before = self.selections()
        clients_before = self.tmux("list-clients", "-F", "#{client_name}:#{session_id}:#{window_id}:#{pane_id}")
        pane, window, data = self.spawn()
        self.assertEqual(before, self.selections())
        self.assertEqual(clients_before, self.tmux("list-clients", "-F", "#{client_name}:#{session_id}:#{window_id}:#{pane_id}"))
        self.assertIn(window, self.windows("pi-dashboard-prefix"))
        self.assertIn(window, self.windows("pi-dashboard"))
        self.assertNotIn(window, self.windows("work-created-last"))
        self.assertNotIn(window, self.windows("work"))
        self.assertEqual(str(data["pid"]), self.tmux("display-message", "-p", "-t", pane, "#{pane_pid}"))
        self.assertEqual("browser-token", data["token"])  # bridge still needs it
        self.assertEqual(pane, self.tmux("list-panes", "-t", window, "-F", "#{pane_id}"))
        self.assertEqual(2, self.tmux("list-windows", "-a", "-F", "#{window_id}").splitlines().count(window))
        # A later CLI descendant cannot re-place a pane after the first choice.
        self.tmux("unlink-window", "-t", self.tmux("display-message", "-p", "-t", "=pi-dashboard-prefix", "#{session_id}") + ":" +
                  self.tmux("display-message", "-p", "-t", "=pi-dashboard-prefix:" + window, "#{window_index}"))
        subprocess.run([sys.executable, str(HELPER)], env={**self.env, "TMUX": self.socket + ",0,0",
            "TMUX_PANE": pane, "PI_DASHBOARD_SPAWN_TOKEN": "browser-token"}, check=True)
        self.assertNotIn(window, self.windows("pi-dashboard-prefix"))

    def test_ignores_more_recent_background_stopped_and_stale_markers(self):
        self.session("eligible")
        time.sleep(1.1)
        for mode in ("background", "stopped", "stale"):
            self.session(mode, mode)
        self.session("pi-dashboard")
        before = self.selections()
        _, window, _ = self.spawn()
        self.assertEqual(before, self.selections())
        self.assertIn(window, self.windows("eligible"))
        for mode in ("background", "stopped", "stale"):
            self.assertNotIn(window, self.windows(mode))

    def test_actual_host_owner_frontend_is_eligible_but_detached_worker_is_not(self):
        session = self.root / "selected.jsonl"
        session.write_text("fixture")
        cleaned = self.root / "owner-cleaned"
        worker_file = self.root / "worker-pid"
        fixture = ROOT / "tools/codex-sandbox/tests/host_pi_owner_fixture.py"
        pane = self.tmux("-f", "/dev/null", "new-session", "-d", "-s", "real-owner", "-c", str(self.root),
            "-P", "-F", "#{pane_id}", shlex.join([sys.executable, str(fixture), "launcher",
                str(session), str(cleaned), str(worker_file)]))
        ui = json.loads(self.wait_file(session.with_suffix(".ready")))
        root_pid = int(self.tmux("display-message", "-p", "-t", pane, "#{pane_pid}"))
        tty = self.tmux("display-message", "-p", "-t", pane, "#{pane_tty}")
        processes = placement.process_table(subprocess.run(
            ["ps", "-ax", "-o", "pid=,ppid=,pgid=,tpgid=,tty=,stat="],
            check=True, capture_output=True, text=True).stdout)
        self.assertNotEqual(root_pid, ui["pid"])
        self.assertTrue(placement.foreground_pi(registration(ui["pid"]), root_pid, tty, processes))
        worker = int(self.wait_file(worker_file))
        self.assertFalse(placement.foreground_pi(registration(worker), root_pid, tty, processes))
        self.tmux("set-option", "-p", "-t", pane, "@resurrect_pi_session", registration(ui["pid"]))
        self.session("pi-dashboard")
        _, window, _ = self.spawn()
        self.assertIn(window, self.windows("real-owner"))
        # Closing the original frontend goes through the real owner's cleanup.
        self.tmux("kill-pane", "-t", pane)
        self.assertEqual("cleaned", self.wait_file(cleaned))

    def test_concurrent_spawns_link_distinct_original_windows_with_bridge_tokens_intact(self):
        self.session("eligible")
        self.session("pi-dashboard")
        before = self.selections()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(self.spawn, ("first", "second")))
        self.assertEqual(before, self.selections())
        self.assertNotEqual(results[0][1], results[1][1])
        self.assertNotEqual(results[0][2]["pid"], results[1][2]["pid"])
        for token, (pane, window, data) in zip(("first", "second"), results):
            self.assertEqual(token, data["token"])
            self.assertIn(window, self.windows("eligible"))
            self.assertIn(window, self.windows("pi-dashboard"))
            self.assertEqual(str(data["pid"]), self.tmux("display-message", "-p", "-t", pane, "#{pane_pid}"))

    def test_no_eligible_destination_leaves_backing_only_and_cli_does_not_relocate(self):
        self.session("background", "background")
        self.session("pi-dashboard")
        _, window, _ = self.spawn()
        self.assertEqual(1, self.tmux("list-windows", "-a", "-F", "#{window_id}").splitlines().count(window))
        self.session("eligible")
        _, cli_window, _ = self.spawn(token="cli", browser=False)
        self.assertNotIn(cli_window, self.windows("eligible"))
        _, outside_window, _ = self.spawn(token="outside", session="background")
        self.assertNotIn(outside_window, self.windows("eligible"))


if __name__ == "__main__":
    unittest.main()
