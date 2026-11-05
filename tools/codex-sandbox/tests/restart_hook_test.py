"""Exercise the installed Pi TUI's actual startup and /reload receivers offline."""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import runpy
import shlex
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
import uuid
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]


class RestartHookTest(unittest.TestCase):
    @unittest.skipUnless(shutil.which("tmux") and shutil.which("node"), "tmux and Node are required")
    def test_actual_tui_startup_and_reload_publish_sdk_session(self):
        package = Path(os.environ.get("PI_PACKAGE_DIR", "/opt/agent-pi/src/packages/coding-agent"))
        manifest = json.loads((package / "package.json").read_text())
        self.assertEqual(manifest["name"], "@earendil-works/pi-coding-agent")
        cli = package / manifest["bin"]["pi"]
        node = shutil.which("node")
        self.assertIsNotNone(node)
        with tempfile.TemporaryDirectory(prefix="pi-restart-hook-") as directory:
            root = Path(directory)
            project = root / "project"
            # Avoid config discovery in the sandbox's protected source working copy.
            subprocess.run(["jj", "git", "init", "--colocate", str(project)],
                           cwd=root, check=True, capture_output=True)
            home = root / "home"
            home.mkdir()
            (home / "src").mkdir()
            saved = root / "sdk-selected.jsonl"
            saved.write_text(json.dumps({"type": "session", "version": 3,
                "id": str(uuid.uuid4()), "timestamp": "2026-10-09T00:00:00.000Z",
                "cwd": str(project)}) + "\n")
            original = saved.read_bytes()
            # tmux's non-UTF-8 output mode replaces the resurrect snapshot's
            # tab separators with underscores. Keep this fixture's server and
            # save-hook subprocesses in UTF-8 mode regardless of caller locale.
            environment = {**os.environ, "LC_ALL": "C.UTF-8",
                "HOME": str(home), "PI_CODING_AGENT_DIR": str(home / ".pi/agent"),
                "XDG_CONFIG_HOME": str(home / ".config"), "XDG_DATA_HOME": str(home / ".local/share"),
                "XDG_CACHE_HOME": str(home / ".cache"), "PI_OFFLINE": "1", "TERM": "xterm-256color",
                "PI_TEST_RELOAD_BOUNDARY": str(root / "reload-boundary")}
            environment.pop("TMUX", None)
            environment.pop("TMUX_PANE", None)
            tmux_socket = str(root / "tmux.sock")
            owner_socket = str(root / "owner.sock")
            requests = []
            errors = []
            stopped = threading.Event()
            owner = socket.socket(socket.AF_UNIX)
            owner.bind(owner_socket)
            owner.listen()
            owner.settimeout(0.1)

            def serve():
                while not stopped.is_set():
                    try:
                        connection, _ = owner.accept()
                    except socket.timeout:
                        continue
                    except OSError:
                        return
                    try:
                        with connection:
                            connection.settimeout(2)
                            data = b""
                            while b"\n" not in data:
                                chunk = connection.recv(4096)
                                if not chunk:
                                    raise ValueError("ready connection ended before request")
                                data += chunk
                            requests.append(json.loads(data.split(b"\n", 1)[0]))
                            connection.sendall(b'{"ok":true}\n')
                    except Exception as error:
                        errors.append(str(error))

            worker = threading.Thread(target=serve, daemon=True)
            worker.start()

            def tmux(*args, check=True):
                return subprocess.run(["tmux", "-S", tmux_socket, *args], env=environment,
                    capture_output=True, text=True, timeout=5, check=check)

            def registration(pane):
                encoded = tmux("show-option", "-pqv", "-t", pane, "@codex_sandbox_restart").stdout.strip()
                return json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))) if encoded else None

            def resurrect_registration(pane):
                encoded = tmux("show-option", "-pqv", "-t", pane, "@resurrect_pi_session").stdout.strip()
                return json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))) if encoded else None

            def wait_for(predicate, label, pane):
                deadline = time.monotonic() + 20
                while time.monotonic() < deadline:
                    if predicate():
                        return
                    time.sleep(0.1)
                output = tmux("capture-pane", "-p", "-t", pane, "-S", "-200", check=False)
                status = tmux("display-message", "-p", "-t", pane,
                    "#{pane_dead} #{pane_dead_status}", check=False)
                self.fail(f"{label} timed out; requests={requests!r}; controller errors={errors!r}; "
                    f"pane status={status.stdout!r}; screen={output.stdout!r}; stderr={output.stderr!r}")

            try:
                pane = tmux("-f", "/dev/null", "new-session", "-d", "-s", "hook", "-x", "120", "-y", "40",
                    "-c", str(project), "-P", "-F", "#{pane_id}", "sleep 30").stdout.strip()
                tmux("set-option", "-p", "-t", pane, "remain-on-exit", "on")
                tmux_env = tmux("display-message", "-p", "-t", pane, "#{socket_path},#{pid},0").stdout.strip()
                launcher = runpy.run_path(str(ROOT / "tools/codex-sandbox/codex-sandbox"))
                state = SimpleNamespace(repository=project, host_working_directory=project)
                with patch.dict(os.environ, {**environment, "TMUX": tmux_env, "TMUX_PANE": pane}, clear=True):
                    launcher["register_tmux_pane"](state)
                pending = registration(pane)
                self.assertIsNone(pending["session"])
                control = root / "hook-attachment.sock"
                expected = {**pending, "version": 3, "control": str(control),
                    "session": str(saved), "cwd": str(project)}
                def pi_command(attachment, session):
                    return shlex.join(["env", f"CODEX_SANDBOX_PI_OWNER={owner_socket}",
                        f"CODEX_SANDBOX_PI_ATTACHMENT={attachment}",
                        f"CODEX_SANDBOX_PI_CONTROL={root / (attachment + '.sock')}",
                        f"CODEX_SANDBOX_CD_VALIDATE={ROOT / 'tools/codex-sandbox/codex-sandbox'}",
                        node, str(cli), "--offline", "--no-extensions", "--no-skills",
                        "--no-prompt-templates", "--no-context-files", "--no-approve",
                        "--extension", str(ROOT / "config/pi-agent/pi-extensions/session-side.ts"),
                        "--extension", str(ROOT / "tools/pi-codex-subagents/index.ts"),
                        "--extension", str(ROOT / "tools/codex-sandbox/tests/reload-boundary.ts"),
                        "--session", str(session)])
                command = pi_command("hook-attachment", saved)
                tmux("respawn-pane", "-k", "-t", pane, "-c", str(project), command)
                wait_for(lambda: registration(pane) == expected, "startup publication", pane)
                wait_for(lambda: resurrect_registration(pane) is not None, "resurrect publication", pane)
                resume = resurrect_registration(pane)
                self.assertEqual({key: resume[key] for key in ("version", "session", "cwd")},
                    {"version": 1, "session": str(saved), "cwd": str(project)})
                self.assertGreater(resume["pid"], 1)
                self.assertEqual(requests, [{"op": "ready", "attachment": "hook-attachment", "session": str(saved)}])
                encoded = base64.urlsafe_b64encode(json.dumps(pending).encode()).decode()
                tmux("set-option", "-p", "-t", pane, "@codex_sandbox_restart", encoded)
                tmux("send-keys", "-t", pane, "-l", "/reload")
                tmux("send-keys", "-t", pane, "Enter")
                wait_for(lambda: len(requests) >= 2 and registration(pane) == expected, "reload publication", pane)
                self.assertEqual(requests, [requests[0], requests[0]])
                # Exercise the real controller through Node and the installed TUI,
                # including old-server shutdown and rebinding the same socket.
                wait_for(control.is_socket, "reload controller startup", pane)
                selected = {"pane": pane, "control": str(control)}
                for reload_count in range(2):
                    launcher["request_restart_control"](selected, "reload", timeout=15)
                    self.assertEqual(len(requests), 3 + reload_count)
                    self.assertEqual(registration(pane), expected)
                    self.assertTrue(control.is_socket())
                    self.assertEqual(resurrect_registration(pane)["pid"], resume["pid"])
                # A real split starts without a launcher registration and uses
                # another session in custom storage, sharing only repository authority.
                split_saved = root / "split-selected.jsonl"
                split_saved.write_text(json.dumps({"type": "session", "version": 3,
                    "id": str(uuid.uuid4()), "timestamp": "2026-10-09T00:00:00.000Z",
                    "cwd": str(project)}) + "\n")
                side = tmux("split-window", "-P", "-F", "#{pane_id}", "-t", pane,
                    "-c", str(project), pi_command("side-attachment", split_saved)).stdout.strip()
                wait_for(lambda: tmux("show-option", "-pqv", "-t", side,
                    "@codex_sandbox_restart").stdout.strip() != "", "split registration", side)
                split_expected = {**expected, "pane": side, "session": str(split_saved),
                    "control": str(root / "side-attachment.sock"), "token": registration(side)["token"]}
                self.assertNotEqual(split_expected["token"], "side-attachment")
                wait_for(lambda: registration(side) == split_expected, "split startup publication", side)
                self.assertEqual(registration(pane), expected)
                # Existing splits from before this change acquire their missing
                # registration on /reload without replacing the accepted worker.
                tmux("set-option", "-pu", "-t", side, "@codex_sandbox_restart")
                tmux("send-keys", "-t", side, "-l", "/reload")
                tmux("send-keys", "-t", side, "Enter")
                wait_for(lambda: len(requests) >= 6 and registration(side) is not None,
                    "split reload publication", side)
                reloaded = registration(side)
                self.assertNotEqual(reloaded["token"], split_expected["token"])
                self.assertEqual({**reloaded, "token": split_expected["token"]}, split_expected)
                self.assertEqual(resurrect_registration(side)["session"], str(split_saved))
                split_pid = resurrect_registration(side)["pid"]
                reload_all = subprocess.run([str(ROOT / "tools/codex-sandbox/codex-sandbox"), "reload-all"],
                    env={**environment, "TMUX": tmux_env}, check=True, capture_output=True, text=True, timeout=20)
                self.assertIn(f"pane {pane}: reload completed", reload_all.stdout)
                self.assertIn(f"pane {side}: reload completed", reload_all.stdout)
                self.assertIn("Reloaded 2 of 2", reload_all.stdout)
                self.assertEqual(len(requests), 8)
                self.assertEqual(resurrect_registration(side)["pid"], split_pid)
                self.assertEqual(registration(pane), expected)
                self.assertEqual(registration(side), reloaded)
                self.assertEqual(resurrect_registration(pane)["pid"], resume["pid"])
                # Hold a real exclusive operation. New Pi must queue the main
                # pane while reloading the idle split, without an early reply.
                boundary = root / "reload-boundary.started"
                release = root / "reload-boundary.release"
                tmux("send-keys", "-t", pane, "-l", "/hold-reload-boundary")
                tmux("send-keys", "-t", pane, "Enter")
                wait_for(boundary.exists, "held tree navigation", pane)
                supports_queue = boundary.read_text() == "queued"
                if os.environ.get("PI_TEST_REQUIRE_QUEUED_RELOAD") == "1":
                    self.assertTrue(supports_queue, "Selected Pi build must expose ctx.requestReload")
                queued_reload = subprocess.Popen([str(ROOT / "tools/codex-sandbox/codex-sandbox"), "reload-all"],
                    env={**environment, "TMUX": tmux_env}, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                try:
                    wait_for(lambda: len(requests) >= 9, "idle split reload while main is busy", side)
                    if supports_queue:
                        self.assertIsNone(queued_reload.poll())
                        self.assertEqual(len(requests), 9)
                    else:
                        stdout, stderr = queued_reload.communicate(timeout=20)
                        self.assertEqual(queued_reload.returncode, 1, (stdout, stderr))
                        self.assertIn("busy", stderr)
                        self.assertIn("updated Pi", stderr)
                    release.touch()
                    if supports_queue:
                        stdout, stderr = queued_reload.communicate(timeout=20)
                        self.assertEqual(queued_reload.returncode, 0, (stdout, stderr))
                        self.assertIn(f"pane {pane}: reload completed", stdout)
                        self.assertIn(f"pane {side}: reload completed", stdout)
                        self.assertEqual(len(requests), 10)
                    self.assertEqual(resurrect_registration(pane)["pid"], resume["pid"])
                    self.assertEqual(resurrect_registration(side)["pid"], split_pid)
                    self.assertEqual(registration(pane), expected)
                    self.assertEqual(registration(side), reloaded)
                finally:
                    release.touch()
                    if queued_reload.poll() is None:
                        queued_reload.kill()
                    queued_reload.communicate(timeout=5)
                # Join the real SDK publisher to the actual save hook, including
                # the reporting child's ancestry within the live tmux pane.
                snapshot = root / "resurrect.txt"
                snapshot.write_text(tmux("display-message", "-p", "-t", pane,
                    "pane\t#{session_name}\t#{window_index}\t1\t:*\t#{pane_index}\tPi\t:/bad-cwd\t1\tpython3\t:old-wrapper").stdout)
                subprocess.run([sys.executable, str(ROOT / "config/tmux/resurrect-pi.py"), str(snapshot)],
                    env={**environment, "TMUX": tmux_env}, check=True, capture_output=True, text=True, timeout=10)
                fields = snapshot.read_text().strip().split("\t")
                self.assertEqual(fields[7], ":" + str(project))
                self.assertEqual(shlex.split(fields[10][1:]),
                    ["pi", "--session", str(saved), "--session-dir", str(saved.parent)])
                # The real SDK may persist startup settings (e.g. thinking level).
                # Assert session identity/header, not a no-write guarantee for Pi itself.
                self.assertEqual(saved.read_bytes().splitlines()[0], original.splitlines()[0])
                self.assertEqual(errors, [])
                busy_behavior = "queued reload completed" if supports_queue else "legacy busy rejection retained"
                print(f"Selected Pi {manifest['version']} TUI: {busy_behavior}; startup and /reload ready acknowledgements "
                    "each published exact SDK file/cwd; launcher generation and session header retained.")
            finally:
                tmux("kill-server", check=False)
                stopped.set()
                owner.close()
                worker.join(timeout=3)


if __name__ == "__main__":
    unittest.main()
