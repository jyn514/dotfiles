"""Disposable PTY/browser harness; invoked by native_dashboard_queue.mjs, not directly by pytest.

No launcher or daemon lifecycle claim: InteractiveMode is the public installed
SDK entrypoint. The real bridge and real dotfiles question extension are loaded
unchanged. Only the model's offline responses and human inputs are fixtures.
"""

from __future__ import annotations

import fcntl
import importlib.util
import json
import os
from pathlib import Path
import pty
import re
import shutil
import signal
import socket
import struct
import subprocess
import sys
import tempfile
import termios
import threading
import time
import urllib.request


HERE = Path(__file__).resolve().parent
REPOSITORY = HERE.parents[2]


def unused_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    # Writers append whole newline-terminated records. Ignore an in-progress
    # tail instead of turning concurrent log observation into a parse race.
    return [json.loads(line) for line in path.read_text().splitlines(keepends=True) if line.endswith("\n")]


def wait_until(predicate, seconds: int, label: str, child=None):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if predicate():
            return
        if child and child.poll() is not None:
            raise RuntimeError(f"{label}: process exited {child.returncode}")
        time.sleep(0.05)
    raise TimeoutError(label)


def interrupted(_signal, _frame):
    raise TimeoutError("Dashboard queue harness interrupted; stopping owned children")


def main() -> int:
    signal.signal(signal.SIGTERM, interrupted)
    scratch = REPOSITORY / "work"
    scratch.mkdir(exist_ok=True)
    children: list[subprocess.Popen] = []
    report = {"status": "failed", "scope": "public installed Pi SDK InteractiveMode on real PTY; not bin/pi or HostPiOwner"}
    with tempfile.TemporaryDirectory(prefix="dashboard-queue-", dir=scratch) as temporary:
        run = Path(temporary)
        home, workspace = run / "home", run / "workspace"
        agent, dashboard = home / ".pi/agent", home / ".pi/dashboard"
        for directory in (workspace, agent, dashboard):
            directory.mkdir(parents=True, exist_ok=True)
        http_port, pi_port = unused_port(), unused_port()
        while http_port == pi_port:
            pi_port = unused_port()
        origin = f"http://127.0.0.1:{http_port}"
        configuration = {
            "port": http_port, "piPort": pi_port, "bindHost": "127.0.0.1", "autoStart": False,
            "autoShutdown": False, "autoNameSessions": False, "registerAskUserTool": False,
            "tunnel": {"provider": "none", "mode": "private"},
            "pairing": {"acceptLanRequests": False}, "mdns": {"enabled": False},
        }
        env = {key: os.environ[key] for key in ("PATH", "LANG", "LC_ALL", "SHELL", "PI_PACKAGE_DIR") if key in os.environ}
        for name in ("DASHBOARD_TEST_CLI", "DASHBOARD_TEST_CORE", "DASHBOARD_TEST_INSTALL", "DASHBOARD_TEST_PLAYWRIGHT", "DASHBOARD_TEST_CHROMIUM", "DASHBOARD_TEST_NODE"):
            env[name] = os.environ[name]
        env.update({
            "HOME": str(home), "USERPROFILE": str(home), "XDG_CONFIG_HOME": str(home / ".config"),
            "XDG_DATA_HOME": str(home / ".local/share"), "XDG_CACHE_HOME": str(home / ".cache"),
            "PI_CODING_AGENT_DIR": str(agent), "PI_DASHBOARD_PORT": str(http_port),
            "PI_DASHBOARD_PI_PORT": str(pi_port), "PI_DASHBOARD_HOST": "127.0.0.1",
            "PI_DASHBOARD_DISABLE_PLUGIN_BRIDGE_PACKAGES_WRITE": "1",
            "TERM": "xterm-256color", "COLORTERM": "truecolor",
            "PROBE_WORKSPACE": str(workspace), "PROBE_EVENTS": str(run / "events.jsonl"),
            "PROBE_INFO": str(run / "native-info.json"),
            "PROBE_EXTENSION": str(REPOSITORY / "config/pi-agent/pi-extensions/ask-user.ts"),
            "PROBE_ORIGIN": origin, "PROBE_URL": origin,
            "PROBE_BROWSER_RESULT": str(run / "browser.json"),
            "PROBE_TERMINAL_READY": str(run / "terminal-ready"), "PROBE_TERMINAL_DONE": str(run / "terminal-done"),
            "PROBE_MULTILINE": "FREE_TEXT_FIRST_LINE\nFREE_TEXT_SECOND_LINE",
        })
        events = lambda: read_jsonl(run / "events.jsonl")
        master = None
        drain_thread = None
        try:
            core = Path(env["DASHBOARD_TEST_CORE"]).resolve()
            install = Path(env["DASHBOARD_TEST_INSTALL"]).resolve()
            receipt = json.loads((install / ".dotfiles-dashboard-patch.json").read_text())
            report["installation"] = {"core": str(core), "install": str(install),
                                      "version": receipt["version"], "patch_sha256": receipt["patch_sha256"]}
            # Match the real persisted declaration and machine-local link. The
            # queue extension is the only other extension in this offline fixture.
            declaration = {"source": "./pi-dashboard", "skills": []}
            settings_source = run / "declarative-pi-settings.json"
            settings_source.write_text(json.dumps({
                "packages": [declaration], "extensions": [env["PROBE_EXTENSION"]],
                "compaction": {"enabled": False}, "retry": {"enabled": False},
                "quietStartup": True, "enableInstallTelemetry": False,
            }))
            settings = agent / "settings.json"
            settings.symlink_to(settings_source)
            package_link = agent / "pi-dashboard"
            package_link.symlink_to(core, target_is_directory=True)
            baseline_env = env | {
                "PROBE_INFO": str(run / "core-package-load.json"),
                "PROBE_EVENTS": str(run / "core-package-observations.jsonl"),
            }
            baseline = subprocess.run([
                env["DASHBOARD_TEST_NODE"], str(HERE / "native-tui.mjs"), "--probe-core-package",
            ], cwd=workspace, env=baseline_env, capture_output=True, text=True, timeout=35)
            (run / "core-package-load.log").write_text(baseline.stdout + baseline.stderr)
            assert baseline.returncode == 0, "core package compatibility probe must complete"
            report["corePackageBaseline"] = json.loads((run / "core-package-load.json").read_text())

            # Exercise the real setup owner rather than choosing an extension
            # path in the test. This only reconciles this fixture's private HOME;
            # it does not install packages, contact Tailscale or activate services.
            spec = importlib.util.spec_from_file_location("dashboard_setup", REPOSITORY / "libexec/setup/setup_dashboard.py")
            setup = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(setup)
            setup.configure(core, install, home, bind_host="100.64.0.1")
            assert settings.is_symlink(), "setup must preserve declarative settings ownership"
            assert json.loads(settings.read_text())["packages"] == [declaration]
            linked_root = package_link.resolve()
            package_manifest = json.loads((linked_root / "package.json").read_text())
            assert package_manifest["name"] == "@blackbelt-technology/pi-dashboard-extension", "setup must select the public split extension package"
            assert package_manifest.get("pi", {}).get("extensions"), "Pi discovers the bridge from its public package manifest"
            report["registration"] = {
                "owner": "libexec/setup/setup_dashboard.py:configure",
                "declaration": declaration, "packageLinkTarget": str(linked_root),
                "packageName": package_manifest["name"], "publicExtensions": package_manifest["pi"]["extensions"],
            }
            # Production setup deliberately chooses a Tailnet address. The test
            # is not network activation: start only a private loopback server.
            configured = json.loads((dashboard / "config.json").read_text())
            assert configured["agentPathGate"] == {"enabled": False}, "setup must apply the declarative path-gate policy"
            configured.update(configuration)
            (dashboard / "config.json").write_text(json.dumps(configured))
            report["fixturePolicy"] = {"agentPathGate": configured["agentPathGate"], "bindHost": configured["bindHost"]}
            with (run / "server.log").open("wb") as server_log:
                server = subprocess.Popen([
                    env["DASHBOARD_TEST_CLI"], "--host", "127.0.0.1", "--port", str(http_port),
                    "--pi-port", str(pi_port), "--no-tunnel",
                ], cwd=workspace, env=env, stdout=server_log, stderr=subprocess.STDOUT, start_new_session=True)
            children.append(server)

            def http_ready():
                try:
                    with urllib.request.urlopen(origin, timeout=1) as response:
                        return response.status == 200
                except OSError:
                    return False

            wait_until(http_ready, 30, "Dashboard HTTP readiness", server)
            assert settings.is_symlink(), "real Dashboard registrar must preserve the declarative settings symlink"
            assert json.loads(settings.read_text())["packages"] == [declaration], "real registrar must retain the relative declaration"
            assert package_link.resolve() == linked_root
            master, slave = pty.openpty()
            fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 40, 160, 0, 0))
            native = subprocess.Popen([
                env["DASHBOARD_TEST_NODE"], str(HERE / "native-tui.mjs"),
            ], cwd=workspace, env=env, stdin=slave, stdout=slave, stderr=slave, start_new_session=True)
            os.close(slave)
            children.append(native)

            def drain():
                try:
                    with (run / "tui.log").open("wb") as output:
                        while True:
                            block = os.read(master, 65536)
                            if not block:
                                return
                            output.write(block)
                            output.flush()
                except OSError:
                    pass

            drain_thread = threading.Thread(target=drain, daemon=True)
            drain_thread.start()
            wait_until(lambda: any(
                entry["type"] == "pi-event" and entry["event"]["type"] == "message_end"
                and "INDEPENDENT_WORK_COMPLETED_WITH_PENDING_QUESTIONS" in json.dumps(entry["event"])
                for entry in events()
            ), 35, "independent model work while real questions remain pending", native)
            ids = next(entry["ids"] for entry in events() if entry["type"] == "queue-ids")
            env["PROBE_QUESTION_IDS"] = json.dumps(ids)
            native_info = json.loads((run / "native-info.json").read_text())
            session_path = Path(native_info["sessionFile"])
            env["PROBE_SESSION_ID"] = native_info["sessionId"]
            snapshots = lambda: [entry["data"]["questions"] for entry in read_jsonl(session_path)
                                 if entry.get("type") == "custom" and entry.get("customType") == "dotfiles-ask-user"]
            assert [question["id"] for question in snapshots()[-1]] == ids[:3], "real cancellation removed only the obsolete question"
            assert not any(entry.get("type") == "message" and entry.get("message", {}).get("role") == "user"
                           and "Answer to ask_user" in json.dumps(entry["message"]) for entry in read_jsonl(session_path))
            report["continuedBeforeAnswer"] = True
            shutil.copyfile(run / "events.jsonl", run / "before-browser.jsonl")
            authorized = subprocess.run([
                env["DASHBOARD_TEST_CLI"], "open", "--print", "--url", origin,
            ], cwd=workspace, env=env, capture_output=True, text=True, timeout=15, check=True)
            proof_urls = [line for line in authorized.stdout.splitlines() if line.startswith(origin + "/auth/local-proof?")]
            assert len(proof_urls) == 1, "normal CLI must return one local browser authorization proof"
            env["PROBE_URL"] = proof_urls[0]
            with (run / "browser.log").open("wb") as browser_log:
                browser = subprocess.Popen([
                    env["DASHBOARD_TEST_NODE"], str(HERE / "browser.mjs"),
                ], cwd=workspace, env=env, stdout=browser_log, stderr=subprocess.STDOUT, start_new_session=True)
            children.append(browser)
            wait_until(lambda: (run / "terminal-ready").exists(), 55, "browser completed literal and multiline answers", browser)
            wait_until(lambda: len(snapshots()[-1]) == 1, 10, "only terminal question remains", native)
            assert snapshots()[-1][0]["id"] == ids[2]
            os.write(master, b"\x1ba")  # Alt+A: the real existing shortcut, not a test-only API.
            wait_until(lambda: "Question 1 of 1" in (run / "tui.log").read_text(errors="replace"), 10, "native question panel opened", native)
            terminal_answer = "NATIVE_TERMINAL_ANSWER"
            os.write(master, terminal_answer.encode() + b"\r")
            wait_until(lambda: snapshots()[-1] == [], 10, "native answer persisted queue removal", native)
            (run / "terminal-done").write_text("done\n")
            browser.wait(timeout=25)
            assert browser.returncode == 0, "browser assertions failed; inspect browser evidence"
            wait_until(lambda: any(entry["type"] == "provider-request" and entry["index"] == 6 for entry in events()), 10, "all three answers reach model context", native)
            entries = read_jsonl(session_path)
            steering = [entry["message"] for entry in entries if entry.get("type") == "message"
                        and entry.get("message", {}).get("role") == "user" and "Answer to ask_user" in json.dumps(entry["message"])]
            expected_answers = ["Cancel", env["PROBE_MULTILINE"], terminal_answer]
            questions = snapshots()[0]
            for index, answer in enumerate(expected_answers):
                body = "\n".join("> " + line for line in questions[index]["question"].split("\n")) + "\n\n" + answer
                expected = f"Answer to ask_user {ids[index]}\nTitle: {json.dumps(questions[index]['title'])}\n\n{body}"
                matches = [message for message in steering if any(block.get("text") == expected for block in message["content"])]
                assert len(matches) == 1, f"exact real steering message must persist once: {ids[index]}"
            assert len(steering) == 3, "model cancellation must not send an answer; no duplicate browser/terminal sends"
            last_context = [entry for entry in events() if entry["type"] == "provider-request"][-1]["messages"]
            for question_id in ids[:3]:
                assert sum(message.get("role") == "user" and f"Answer to ask_user {question_id}" in json.dumps(message)
                           for message in last_context) == 1, "each queued answer enters actual model context exactly once"
            assert [len(value) for value in snapshots()] == [4, 3, 2, 1, 0]
            assert not any(entry["type"] in ("uncaught", "unhandled") for entry in events())
            browser_result = json.loads((run / "browser.json").read_text())
            assert browser_result["status"] == "passed"
            report.update({
                "status": "passed", "configuration": configuration,
                "sdk": native_info["sdk"], "loadedRegistration": native_info["registration"],
                "snapshotPendingCounts": [len(value) for value in snapshots()],
                "persistedSteeringMessages": len(steering), "modelRequests": 6,
                "browserChecks": browser_result["checks"], "pendingSessionStatus": browser_result["pendingSessionStatus"],
                "browserResponses": len(browser_result["browserResponses"]),
            })
            shutil.copyfile(session_path, run / "session.jsonl")
        except Exception as error:
            report["error"] = f"{type(error).__name__}: {error}"
            loads = [entry for entry in events() if entry.get("type") == "extension-load"]
            if loads:
                report["correctedPackageLoad"] = loads[-1]
        finally:
            for child in reversed(children):
                try:
                    os.killpg(child.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
            for child in children:
                try:
                    child.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(child.pid, signal.SIGKILL)
                    child.wait(timeout=5)
            if drain_thread:
                drain_thread.join(timeout=1)
            if master is not None:
                os.close(master)
            report["processesStopped"] = all(child.poll() is not None for child in children)
            if not report["processesStopped"]:
                report["status"] = "failed"
            (run / "result.json").write_text(json.dumps(report, indent=2) + "\n")
            info = run / "native-info.json"
            if info.exists() and not (run / "session.jsonl").exists():
                session_file = Path(json.loads(info.read_text())["sessionFile"])
                if session_file.exists():
                    shutil.copyfile(session_file, run / "session.jsonl")
            # Preserve decisive evidence only when explicitly requested. Never
            # copy the disposable HOME, auth proofs, cookies or pairing files.
            artifacts = os.environ.get("DASHBOARD_TEST_ARTIFACT_DIR")
            if artifacts:
                destination = Path(artifacts)
                destination.mkdir(parents=True, exist_ok=True)
                for name in ("result.json", "events.jsonl", "before-browser.jsonl", "session.jsonl", "browser.json", "core-package-load.json", "core-package-load.log", "server.log", "tui.log", "browser.log"):
                    if (run / name).exists():
                        shutil.copyfile(run / name, destination / name)
            if report["status"] != "passed":
                for name in ("core-package-load.log", "events.jsonl", "tui.log", "server.log", "browser.json", "browser.log"):
                    path = run / name
                    if path.exists():
                        text = re.sub(r"/auth/local-proof\?[^\s\"']+", "/auth/local-proof?[redacted]", path.read_text(errors="replace")[-18000:])
                        print(f"--- {name} ---\n{text}", file=sys.stderr)
            print(json.dumps(report, indent=2))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
