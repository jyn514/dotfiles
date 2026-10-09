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
            project.mkdir()
            home = root / "home"
            home.mkdir()
            saved = root / "sdk-selected.jsonl"
            saved.write_text(json.dumps({"type": "session", "version": 3,
                "id": str(uuid.uuid4()), "timestamp": "2026-10-09T00:00:00.000Z",
                "cwd": str(project)}) + "\n")
            original = saved.read_bytes()
            environment = {**os.environ, "HOME": str(home), "PI_CODING_AGENT_DIR": str(home / ".pi/agent"),
                "XDG_CONFIG_HOME": str(home / ".config"), "XDG_DATA_HOME": str(home / ".local/share"),
                "XDG_CACHE_HOME": str(home / ".cache"), "PI_OFFLINE": "1", "TERM": "xterm-256color"}
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
                return json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))

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
                expected = {**pending, "session": str(saved), "cwd": str(project)}
                command = shlex.join(["env", f"CODEX_SANDBOX_PI_OWNER={owner_socket}",
                    "CODEX_SANDBOX_PI_ATTACHMENT=hook-attachment", node, str(cli), "--offline",
                    "--no-extensions", "--no-skills", "--no-prompt-templates", "--no-context-files",
                    "--no-approve", "--extension", str(ROOT / "config/pi-agent/pi-extensions/session-side.ts"),
                    "--session", str(saved)])
                tmux("respawn-pane", "-k", "-t", pane, "-c", str(project), command)
                wait_for(lambda: registration(pane) == expected, "startup publication", pane)
                self.assertEqual(requests, [{"op": "ready", "attachment": "hook-attachment", "session": str(saved)}])
                encoded = base64.urlsafe_b64encode(json.dumps(pending).encode()).decode()
                tmux("set-option", "-p", "-t", pane, "@codex_sandbox_restart", encoded)
                tmux("send-keys", "-t", pane, "-l", "/reload")
                tmux("send-keys", "-t", pane, "Enter")
                wait_for(lambda: len(requests) >= 2 and registration(pane) == expected, "reload publication", pane)
                self.assertEqual(requests, [requests[0], requests[0]])
                # The real SDK may persist startup settings (e.g. thinking level).
                # Assert session identity/header, not a no-write guarantee for Pi itself.
                self.assertEqual(saved.read_bytes().splitlines()[0], original.splitlines()[0])
                self.assertEqual(errors, [])
                print(f"Actual installed Pi {manifest['version']} TUI: startup and /reload ready acknowledgements "
                    "each published exact SDK file/cwd; launcher generation and session header retained.")
            finally:
                tmux("kill-server", check=False)
                stopped.set()
                owner.close()
                worker.join(timeout=3)


if __name__ == "__main__":
    unittest.main()
