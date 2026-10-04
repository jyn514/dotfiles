#!/usr/bin/env python3
"""Opt-in Linux real Pi/AgentManager abrupt-parent-loss regression.

Run with explicit --pi /installed/package/dist/bundle/cli.js and
--subagent-core /checkout/packages/pi-codex-subagents/core.ts.
Uses the existing LOCAL worker fixture, disposable tmux and temporary HOME.
No model request, Docker/VM acceptance, or new process supervisor.
"""
import argparse
import json
import os
from pathlib import Path
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import uuid

from side_pi_integration import alive, entries, load, public_sdk, seed, wait_for

HERE = Path(__file__).resolve().parent
WRAPPER = HERE.parent / "sandbox-host-pi"


def run_case(root, pi, package, subagent_core):
    home, host, guest, sessions = (root / name for name in ("home", "host", "guest", "sessions"))
    for directory in (home, host, guest, sessions):
        directory.mkdir()
    agent = home / ".pi/agent"
    agent.mkdir(parents=True)
    (agent / "settings.json").write_text(json.dumps({"quietStartup": True, "checkForUpdates": False}))
    (agent / "auth.json").write_text(json.dumps({"side-attribution": {
        "type": "api_key", "key": "owned-test-key-not-a-credential"}}))
    extensions = agent / "extensions"
    extensions.mkdir()
    provider = extensions / "attribution.ts"
    shutil.copyfile(HERE / "side_pi_attribution_fixture.ts", provider)
    # Ordinary children disable discovery; their manager explicitly loads this
    # same inference-prohibiting provider through its existing extension setting.
    child_config = agent / "pi-codex-subagents/config.json"
    child_config.parent.mkdir()
    child_config.write_text(json.dumps({"defaults": {"extensions": [str(provider)]}}))
    fake_jj = root / "fake-jj"
    fake_jj.write_text("#!/bin/sh\nexec " + shlex.join([
        "python3", str(HERE / "side_pi_fixture.py"), "jj-real"]) + ' "$@"\n')
    fake_jj.chmod(0o700)
    installed = home / ".local/share/pi/node/node_modules/.bin/pi"
    installed.parent.mkdir(parents=True)
    installed.symlink_to(pi)
    source = sessions / "source.jsonl"
    seed(source, host)
    (guest / "guest-only-marker").write_text("ordinary-peer-worker-marker\n")
    environment = {
        "PATH": os.environ.get("PATH", os.defpath), "TERM": "xterm-256color",
        "HOME": str(home), "PI_CODING_AGENT_DIR": str(agent),
        "PI_CODING_AGENT_SESSION_DIR": str(sessions), "PI_PACKAGE_DIR": str(package),
        "PI_OFFLINE": "1", "PI_SKIP_VERSION_CHECK": "1", "PI_TELEMETRY": "0",
        "PI_SUBAGENT_TEMP_DIR": str(root / "subagent-temp"),
        "PI_SUBAGENT_PI_BIN": str(WRAPPER), "SIDE_TEST_SUBAGENT_CORE": str(subagent_core),
        "SIDE_TEST_ORDINARY_RECEIPT": str(root / "ordinary.json"),
        "SIDE_TEST_CONSUMER": str(HERE / "side_pi_fixture.py"),
    }
    arguments = ["--session", str(source), "--session-dir", str(sessions), "--offline",
                 "--provider", "side-attribution", "--model", "fixture-model-A-raw",
                 "--no-skills", "--no-prompt-templates",
                 "--no-context-files", "--no-approve", "--extension",
                 str(HERE / "fixtures/side_ordinary_parent.ts")]
    (root / "config.json").write_text(json.dumps({
        "guest_cwd": str(guest), "tool_module": str(public_sdk(package)),
        "arguments": arguments, "identity_environment": {
            "PI_MODEL_FILE": str(root / "shared-legacy-model.json"),
            "PI_MODEL_SESSION_ID": "owned-shared-legacy-session", "JJ_AGENT": "pi",
            "JJ_REAL": str(fake_jj), "JJ_ROUTE_HELPER": str(HERE / "side_pi_fixture.py"),
            "SANDBOX_PROXY_DEFAULT_DIR": str(root / "nonexistent-proxy-directory")},
    }))
    server = "side-ordinary-" + uuid.uuid4().hex
    tmux_base = ["tmux", "-L", server, "-f", "/dev/null"]

    def tmux(*args, check=True):
        return subprocess.run([*tmux_base, *args], env=environment, text=True,
                              capture_output=True, timeout=5, check=check)

    def receipt():
        return load(root / "receipt.json") or {}

    def ready(count):
        peers = receipt().get("attachments", [])
        return peers if len(peers) == count and all(peer["ready"] for peer in peers) else None

    def input_line(pane, text):
        tmux("send-keys", "-l", "-t", pane, text)
        tmux("send-keys", "-t", pane, "Enter")

    source_pane = side_pane = None
    ordinary = {}
    try:
        command = shlex.join(["python3", str(HERE / "side_pi_fixture.py"), "owner", str(root)])
        source_pane = tmux("new-session", "-d", "-P", "-F", "#{pane_id}", "-s", "integration",
                           "-x", "180", "-y", "70", "-c", str(host), command).stdout.strip()
        tmux("set-option", "-g", "remain-on-exit", "on")
        wait_for("source readiness", lambda: ready(1))
        ordinary = wait_for("real AgentManager child", lambda: load(root / "ordinary.json"))
        assert ordinary["parentModel"] == {"provider": "side-attribution", "modelId": "fixture-model-A-raw"}, ordinary
        assert ordinary["childModel"] == {"provider": "side-attribution", "modelId": "fixture-model-B-raw"}, ordinary
        input_line(source_pane, "/ordinary-start")
        attribution = wait_for("ordinary child JJ attribution", lambda: load(root / "ORDINARY.jj.json"))
        assert attribution["jj_user"] == "Pi fixture-model-B-raw", attribution
        assert attribution["call_model"] == "fixture-model-B-raw" and attribution["cwd"] == str(guest), attribution
        assert attribution["legacy"]["modelId"] == ordinary["parentModel"]["modelId"], attribution
        frames = [load(path) for path in (root / "calls").glob("*.json")]
        frame = next(frame for frame in frames if "consumer ORDINARY" in frame["params"].get("command", ""))
        assert frame["tool"] == "user_bash" and frame["model"] == ordinary["childModel"], frame
        wait_for("ordinary child guest operation", lambda: (guest / "ordinary-started").exists())
        assert not (host / "ordinary-started").exists(), "ordinary child ran host-local bash"
        assert alive(ordinary["parentPid"]) and alive(ordinary["childPid"]), ordinary
        child_env = dict(item.split(b"=", 1) for item in
                         Path(f"/proc/{ordinary['childPid']}/environ").read_bytes().split(b"\0") if b"=" in item)
        assert b"PI_SUBAGENT_OWNER_TOKEN" in child_env, "not a manager-owned native child"
        forbidden = (b"CODEX_SANDBOX_PI_OWNER", b"CODEX_SANDBOX_PI_ATTACHMENT", b"CODEX_SANDBOX_CD_REQUEST")
        assert not any(key in child_env for key in forbidden), "ordinary child inherited pane control"
        input_line(source_pane, "/side")
        peers = wait_for("real side peer", lambda: ready(2))
        side = next(peer for peer in peers if peer["pane"] != source_pane)
        side_pane, side_session = side["pane"], Path(side["session"])
        worker_pid = receipt()["worker_pid"]
        assert alive(ordinary["childPid"]) and not (guest / "ordinary-late").exists(), \
            "ordinary operation must still be active before source loss"
        wrapper_pid = int(tmux("display-message", "-p", "-t", source_pane, "#{pane_pid}").stdout)
        started = time.monotonic()
        os.kill(wrapper_pid, signal.SIGKILL)
        wait_for("source native Pi death", lambda: not alive(ordinary["parentPid"]), timeout=5)
        wait_for("ordinary RPC child EOF shutdown", lambda: not alive(ordinary["childPid"]), timeout=5)
        wait_for("source attachment released", lambda: ready(1), timeout=5)
        assert ready(1)[0]["pane"] == side_pane
        assert not (root / "cleanup.json").exists(), "source loss cleaned peer workload"
        assert alive(worker_pid), "peer worker died with source"
        # Observe beyond the ordinary operation's delayed effect; merely dropping
        # its Pi process is insufficient evidence of guest-call cancellation.
        time.sleep(max(0, 8.5 - (time.monotonic() - started)))
        assert not (guest / "ordinary-late").exists(), "ordinary child guest work survived parent loss"
        before = len(entries(side_session))
        input_line(side_pane, "!cat guest-only-marker; printf PEER_STILL_GUEST_OK")
        def peer_result():
            return next((entry["message"] for entry in entries(side_session)[before:]
                         if entry.get("type") == "message"
                         and entry["message"].get("role") == "bashExecution"
                         and "PEER_STILL_GUEST_OK" in entry["message"].get("output", "")), None)
        result = wait_for("surviving peer guest bash", peer_result)
        assert result["exitCode"] == 0 and "ordinary-peer-worker-marker" in result["output"], result
        assert receipt()["worker_pid"] == worker_pid
        input_line(side_pane, "/quit")
        cleanup = wait_for("final cleanup", lambda: load(root / "cleanup.json"))
        assert cleanup["succeeded"] and cleanup["worker_pid"] == worker_pid, cleanup
        wait_for("worker termination", lambda: not alive(worker_pid))
        wait_for("owner termination", lambda: not alive(receipt()["owner_pid"]))
        assert not (root / "inference-attempted").exists(), "unexpected provider invocation"
        print(json.dumps({"source_wrapper_pid": wrapper_pid, **ordinary,
                          "child_attribution": attribution, "child_call_model": frame["model"],
                          "ordinary_stopped": not alive(ordinary["childPid"]),
                          "late_guest_write": False, "worker_pid": worker_pid,
                          "peer_output": result["output"].strip(), "cleanup": cleanup}, sort_keys=True))
    except BaseException:
        for pane in (source_pane, side_pane):
            if pane:
                print(f"FAIL {pane}:\n" + tmux("capture-pane", "-p", "-S", "-", "-t", pane, check=False).stdout)
        for name in ("receipt.json", "ordinary.json", "shared-legacy-model.json", "worker.log", "cleanup.json"):
            path = root / name
            if path.exists():
                print(f"{name}: {path.read_text()}")
        raise
    finally:
        tmux("kill-server", check=False)
        # A failing EOF mutation can leave the manager's detached ordinary child;
        # kill only the PID/group published by our owned fixture.
        child_pid = ordinary.get("childPid")
        if child_pid and alive(child_pid):
            try:
                os.killpg(child_pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        for name in ("owner_pid", "worker_pid"):
            pid = receipt().get(name)
            if pid and alive(pid):
                try:
                    wait_for("owned emergency cleanup", lambda: not alive(pid), timeout=3)
                except AssertionError:
                    os.kill(pid, signal.SIGTERM)
                    try:
                        wait_for("owned termination", lambda: not alive(pid), timeout=5)
                    except AssertionError:
                        os.kill(pid, signal.SIGKILL)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pi", required=True, type=Path)
    parser.add_argument("--subagent-core", required=True, type=Path)
    args = parser.parse_args()
    if sys.platform != "linux":
        parser.error("Linux required: wrapper SIGKILL/pdeath and /proc child environment acceptance")
    pi = args.pi.resolve(strict=True)
    core = args.subagent_core.resolve(strict=True)
    package = pi.parent.parent.parent
    try:
        public_sdk(package)
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.error(f"--pi must belong to an installed Pi package with its public SDK export: {error}")
    for program in ("tmux", "node", "python3", "jq"):
        if not shutil.which(program):
            parser.error(f"missing prerequisite: {program}")
    with tempfile.TemporaryDirectory(prefix="side-ordinary-integration-") as temporary:
        run_case(Path(temporary), pi, package, core)
    print("PASS: real AgentManager/RPC child model attribution, EOF shutdown, guest cancellation and surviving /side peer; NOT Docker/VM/inference acceptance")


if __name__ == "__main__":
    main()
