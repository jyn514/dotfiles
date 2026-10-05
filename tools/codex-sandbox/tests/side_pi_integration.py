#!/usr/bin/env python3
"""Opt-in real Pi /side UI + disposable tmux + real LOCAL tool-worker acceptance.

Run: python3 tools/codex-sandbox/tests/side_pi_integration.py --pi /path/to/cli.js
No Docker/VM/network/model acceptance: the guest is a distinct local directory.
Likely regressions covered: /side loses completed context, replays user prompts,
launches host tools, or source exit incorrectly destroys the sibling's worker.
Also overlaps native /model-selected user_bash calls through the actual JJ shim:
A waits, B publishes stale legacy metadata, then A must retain its call identity.
Only temporary HOME/config/session/socket/server resources are used.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shlex
import shutil
import signal
import subprocess
import tempfile
import time
import uuid

HERE = Path(__file__).resolve().parent


def wait_for(description, check, timeout=25):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = check()
        if value:
            return value
        time.sleep(.1)
    raise AssertionError(f"timed out waiting for {description}")


def load(path):
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def entries(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line]


def alive(pid):
    try:
        os.kill(pid, 0)
        # Linux containers may leave a terminated detached owner as a zombie.
        stat = Path(f"/proc/{pid}/stat")
        return not (stat.exists() and stat.read_text().split(") ", 1)[1].startswith("Z"))
    except ProcessLookupError:
        return False


def public_sdk(package):
    metadata = json.loads((package / "package.json").read_text())
    if metadata.get("name") != "@earendil-works/pi-coding-agent":
        raise ValueError("--pi package must be @earendil-works/pi-coding-agent")
    exported = metadata["exports"]["."]["import"]
    if not isinstance(exported, str) or not exported.startswith("./"):
        raise ValueError("Pi package must publish its root ESM import")
    module = (package / exported).resolve(strict=True)
    if not module.is_relative_to(package.resolve()) or not module.is_file():
        raise ValueError("Pi public SDK export must be a file inside its package")
    return module


def seed(path, cwd):
    """Valid v3 native JSONL: a completed source turn, no model invocation."""
    timestamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    now = int(time.time() * 1000)
    usage = {key: 0 for key in ("input", "output", "cacheRead", "cacheWrite", "totalTokens")}
    usage["cost"] = {key: 0 for key in ("input", "output", "cacheRead", "cacheWrite", "total")}
    messages = [
        {"role": "user", "content": [{"type": "text", "text": "source-completed-context-7a918"}], "timestamp": now},
        {"role": "assistant", "content": [{"type": "text", "text": "completed-answer-62d07"}],
         "api": "anthropic-messages", "provider": "anthropic", "model": "claude-sonnet-4-5",
         "usage": usage, "stopReason": "stop", "timestamp": now + 1},
    ]
    data = [{"type": "session", "version": 3, "id": str(uuid.uuid4()),
             "timestamp": timestamp, "cwd": str(cwd)}]
    parent = None
    for message in messages:
        ident = uuid.uuid4().hex[:8]
        data.append({"type": "message", "id": ident, "parentId": parent,
                     "timestamp": timestamp, "message": message})
        parent = ident
    path.write_text("".join(json.dumps(item) + "\n" for item in data))
    return data


def run_case(root, pi, package, close_source_first):
    order = "source-first" if close_source_first else "side-first"
    runtime = root / order
    runtime.mkdir()
    home, host, guest, sessions = (runtime / name for name in ("home", "host", "local-guest", "sessions"))
    for directory in (home, host, guest, sessions):
        directory.mkdir()
    agent = home / ".pi/agent"
    agent.mkdir(parents=True)
    (agent / "settings.json").write_text(json.dumps({"quietStartup": True, "checkForUpdates": False}))
    (agent / "auth.json").write_text(json.dumps({"side-attribution": {
        "type": "api_key", "key": "owned-test-key-not-a-credential"}}))
    extensions = agent / "extensions"
    extensions.mkdir()
    shutil.copyfile(HERE / "side_pi_attribution_fixture.ts", extensions / "attribution.ts")
    fake_jj = runtime / "fake-jj"
    fake_jj.write_text("#!/bin/sh\nexec " + shlex.join([
        "python3", str(HERE / "side_pi_fixture.py"), "jj-real"]) + ' "$@"\n')
    fake_jj.chmod(0o700)
    installed = home / ".local/share/pi/node/node_modules/.bin/pi"
    installed.parent.mkdir(parents=True)
    installed.symlink_to(pi)
    source = sessions / "source.jsonl"
    source_data = seed(source, host)
    marker = "local-guest-only-53f4e"
    (guest / "guest-only-marker").write_text(marker + "\n")
    assert not (host / "guest-only-marker").exists()
    environment = {"PATH": os.environ.get("PATH", os.defpath), "TERM": "xterm-256color",
                   "HOME": str(home), "PI_CODING_AGENT_DIR": str(agent),
                   "PI_CODING_AGENT_SESSION_DIR": str(sessions), "PI_PACKAGE_DIR": str(package),
                   "PI_OFFLINE": "1", "PI_SKIP_VERSION_CHECK": "1", "PI_TELEMETRY": "0"}
    # Both native panes discover the same test provider from owned HOME; /side
    # intentionally drops original extra CLI flags. No auth or project resources.
    arguments = ["--session", str(source), "--session-dir", str(sessions), "--offline",
                 "--no-skills", "--no-prompt-templates", "--no-context-files", "--no-approve"]
    (runtime / "config.json").write_text(json.dumps({
        "guest_cwd": str(guest), "tool_module": str(public_sdk(package)),
        "arguments": arguments, "identity_environment": {
            "PI_MODEL_FILE": str(runtime / "shared-legacy-model.json"),
            "PI_MODEL_SESSION_ID": "owned-shared-legacy-session", "JJ_AGENT": "pi",
            "JJ_REAL": str(fake_jj), "JJ_ROUTE_HELPER": str(HERE / "side_pi_fixture.py"),
            "SANDBOX_PROXY_DEFAULT_DIR": str(runtime / "nonexistent-proxy-directory")}}))
    server = "side-pi-" + uuid.uuid4().hex
    tmux_base = ["tmux", "-L", server, "-f", "/dev/null"]

    def tmux(*args, check=True):
        return subprocess.run([*tmux_base, *args], env=environment, text=True,
                              capture_output=True, timeout=5, check=check)

    def receipt():
        return load(runtime / "receipt.json") or {}

    def capture(pane):
        return tmux("capture-pane", "-p", "-S", "-", "-t", pane, check=False).stdout

    def input_line(pane, text):
        tmux("send-keys", "-l", "-t", pane, text)
        tmux("send-keys", "-t", pane, "Enter")

    def ready(count):
        peers = receipt().get("attachments", [])
        return peers if len(peers) == count and all(peer["ready"] for peer in peers) else None

    def tool_probe(pane, label, session):
        before = len(entries(session))
        input_line(pane, f"!pwd; cat guest-only-marker; printf '{label}\\n'")
        def completed():
            messages = [item["message"] for item in entries(session)[before:]
                        if item.get("type") == "message"]
            return next((message for message in messages if message.get("role") == "bashExecution"
                         and label in message.get("output", "")), None)
        message = wait_for(f"{label} real Pi user_bash", completed)
        assert message["exitCode"] == 0, message
        assert str(guest) in message["output"] and marker in message["output"], message
        assert str(host) not in message["output"], message
        assert alive(receipt()["worker_pid"]), receipt()
        return message["output"].strip()

    def switch_model(pane, model_id):
        expected = {"provider": "side-attribution", "modelId": model_id}
        model_path = runtime / f"ctx-model-{pane}.json"
        before = load(model_path)
        tmux("send-keys", "-l", "-t", pane, f"/model side-attribution/{model_id}")
        # Model-argument autocomplete consumes Enter to accept the matching item.
        # Cancel only the completion menu, then submit the actual built-in command.
        time.sleep(.15)
        tmux("send-keys", "-t", pane, "Escape")
        time.sleep(.15)
        tmux("send-keys", "-t", pane, "Enter")
        def changed():
            value = load(model_path)
            return value and value != before and value.get("event") == "model_select" and all(
                value.get(key) == wanted for key, wanted in expected.items())
        wait_for(f"native ctx.model selects {model_id}", changed)
        wait_for(f"actual runtimeIdentity publishes {model_id}",
                 lambda: (load(runtime / "shared-legacy-model.json") or {}).get("modelId") == model_id)
        return expected

    def completed_consumer(session, label):
        return next((item["message"] for item in entries(session)
                     if item.get("type") == "message"
                     and item["message"].get("role") == "bashExecution"
                     and f"consumer {label}" in item["message"].get("command", "")), None)

    def call_receipt(label):
        return next((request for path in (runtime / "calls").glob("*.json")
                     if (request := load(path)) and f"consumer {label}" in
                     request.get("params", {}).get("command", "")), None)

    def sdk_attribution_overlap():
        sdk_environment = dict(environment)
        config = load(runtime / "config.json")
        sdk_environment.update(config["identity_environment"])
        sdk_environment.update(SIDE_PI_RUNTIME=str(runtime),
                               CODEX_SANDBOX_TOOL_CONNECT=str(HERE / "side_pi_fixture.py"),
                               CODEX_SANDBOX_TOOL_CONTAINER="local-test-worker-not-container",
                               CODEX_SANDBOX_TOOL_SOCKET=str(runtime / "worker.sock"),
                               CODEX_SANDBOX_GUEST_CWD=str(guest))
        source_extensions = HERE.parents[2] / "config/pi-agent/pi-extensions"
        result = subprocess.run([
            "node", str(HERE / "side_pi_sdk_fixture.mjs"), str(public_sdk(package)),
            str(source_extensions / "guest-tools.ts"), str(source_extensions / "runtime-identity.ts"),
            str(HERE / "side_pi_fixture.py")], cwd=host, env=sdk_environment,
            text=True, capture_output=True, timeout=45)
        assert result.returncode == 0, (result.stdout, result.stderr)
        proof = load(runtime / "sdk-attribution.json")
        assert proof, "native SDK did not publish registered bash attribution evidence"
        producer_models = {}
        for label, model_id in (("SDK_A", "fixture-model-A-raw"), ("SDK_B", "fixture-model-B-raw")):
            frame = call_receipt(label)
            assert {"tool", "params", "model"} <= frame.keys() <= {"tool", "params", "model", "id"}, frame
            assert frame["tool"] == "bash" and frame["model"] == {
                "provider": "side-attribution", "modelId": model_id}, frame
            producer_models[label] = frame["model"]
        proof["producer_models"] = producer_models
        return proof

    def attribution_overlap():
        model_a, model_b = "fixture-model-A-raw", "fixture-model-B-raw"
        consumer_command = shlex.join(["python3", str(HERE / "side_pi_fixture.py"), "consumer"])
        # A's model is captured by real guest-tools before the shell blocks.
        input_line(source_pane, f"!{consumer_command} A --pause")
        started_a = wait_for("A guest shell paused", lambda: load(runtime / "A.started.json"))
        assert started_a["call_model"] == model_a, started_a
        ctx_b = switch_model(side_pane, model_b)
        assert not (runtime / "A.jj.json").exists(), "A was not overlapped with B's publication"
        input_line(side_pane, f"!{consumer_command} B")
        result_b = wait_for("actual JJ consumer B", lambda: load(runtime / "B.jj.json"))
        wait_for("native B command persisted", lambda: completed_consumer(side_session, "B"))
        assert result_b["jj_user"] == f"Pi {model_b}" and result_b["call_model"] == model_b, result_b
        assert result_b["cwd"] == str(guest), result_b
        # The actual shared legacy publisher now says B for both panes/workers.
        assert result_b["legacy"]["modelId"] == model_b, result_b
        (runtime / "A.release").touch()
        result_a = wait_for("actual JJ consumer A after B publication", lambda: load(runtime / "A.jj.json"))
        wait_for("native A command persisted", lambda: completed_consumer(source, "A"))
        assert result_a["jj_user"] == f"Pi {model_a}" and result_a["call_model"] == model_a, result_a
        assert result_a["legacy"]["modelId"] == model_b and result_a["cwd"] == str(guest), result_a
        # Demonstrate the old race through the actual unmodified consumer parser.
        # Only this throwaway subprocess omits PI_CALL_MODEL; standalone fallback
        # necessarily misattributes A to the shared stale B file.
        input_line(source_pane, f"!{consumer_command} OLD_A --legacy")
        old_a = wait_for("counterfactual legacy consumer", lambda: load(runtime / "OLD_A.jj.json"))
        wait_for("native legacy counterfactual persisted", lambda: completed_consumer(source, "OLD_A"))
        assert old_a["call_model"] is None and old_a["jj_user"] == f"Pi {model_b}", old_a
        assert old_a["jj_user"] != result_a["jj_user"], (old_a, result_a)
        frames = {label: call_receipt(label) for label in ("A", "B", "OLD_A")}
        for label, model_id in (("A", model_a), ("B", model_b), ("OLD_A", model_a)):
            assert {"tool", "params", "model"} <= frames[label].keys() <= {"tool", "params", "model", "id"}, frames
            assert frames[label]["tool"] == "user_bash", frames
            assert frames[label]["model"] == {"provider": "side-attribution", "modelId": model_id}, frames
        assert not (runtime / "inference-attempted").exists(), "provider inference unexpectedly invoked"
        return {"ctx_model_a": load(runtime / f"ctx-model-{source_pane}.json"),
                "ctx_model_b": ctx_b, "a": result_a, "b": result_b,
                "legacy_counterfactual": old_a,
                "producer_models": {label: frame["model"] for label, frame in frames.items()}}

    source_pane = side_pane = None
    failed = False
    try:
        command = shlex.join(["python3", str(HERE / "side_pi_fixture.py"), "owner", str(runtime)])
        source_pane = tmux("new-session", "-d", "-P", "-F", "#{pane_id}", "-s", "integration",
                           "-x", "180", "-y", "70", "-c", str(host), command).stdout.strip()
        # Preserve exited panes for diagnostics, not as lifetime attachments.
        tmux("set-option", "-g", "remain-on-exit", "on")
        wait_for("real source Pi extension readiness", lambda: ready(1))
        metadata = receipt()
        assert metadata["source_pane"] == source_pane
        assert metadata["tmux"].split(",")[0].endswith("/" + server), metadata
        worker_pid = metadata["worker_pid"]
        assert alive(worker_pid)
        # session_start readiness precedes the native editor's initial key binding.
        wait_for("native source editor rendered", lambda: "fixture-model-A-raw" in capture(source_pane))
        time.sleep(.5)
        # Startup defaults to A; change away and back so native model_select is
        # observable (Pi intentionally omits that event for a same-model choice).
        switch_model(source_pane, "fixture-model-B-raw")
        switch_model(source_pane, "fixture-model-A-raw")
        first_output = tool_probe(source_pane, "SOURCE_GUEST_OK", source)
        before_side = entries(source)
        input_line(source_pane, "/side")
        peers = wait_for("actual /side command opens ready real sibling", lambda: ready(2))
        side_info = next(peer for peer in peers if peer["pane"] != source_pane)
        side_pane = side_info["pane"]
        side_session = Path(side_info["session"])
        assert side_session != source and side_session.parent == sessions, side_info
        side_data = entries(side_session)
        assert side_data[0]["type"] == "session" and side_data[0]["id"] != source_data[0]["id"]
        assert side_data[0]["cwd"] == str(host), side_data[0]
        assert side_data[0].get("parentSession") == str(source), side_data[0]
        source_messages = [item["message"] for item in before_side if item["type"] == "message"]
        side_messages = [item["message"] for item in side_data if item["type"] == "message"]
        assert side_messages == source_messages, (side_messages, source_messages)
        # Give startup/replay regressions a bounded chance to become observable.
        time.sleep(.5)
        assert [item["message"] for item in entries(side_session) if item["type"] == "message"] == source_messages
        assert receipt()["worker_pid"] == worker_pid and alive(worker_pid)
        second_output = tool_probe(side_pane, "SIDE_GUEST_OK", side_session)
        attribution = attribution_overlap() if close_source_first else None
        if attribution:
            attribution["registered_bash"] = sdk_attribution_overlap()
        assert not (runtime / "inference-attempted").exists(), "provider inference unexpectedly invoked"
        first, survivor = (source_pane, side_pane) if close_source_first else (side_pane, source_pane)
        surviving_session = side_session if close_source_first else source
        input_line(first, "/quit")
        wait_for("first attachment released while sibling remains", lambda: ready(1))
        assert not (runtime / "cleanup.json").exists(), "workload cleaned up before final attachment exit"
        survivor_output = tool_probe(survivor, "SURVIVOR_GUEST_OK", surviving_session)
        assert receipt()["worker_pid"] == worker_pid
        input_line(survivor, "/quit")
        cleanup = wait_for("final attachment real worker cleanup", lambda: load(runtime / "cleanup.json"))
        assert cleanup["succeeded"] and cleanup["worker_pid"] == worker_pid, cleanup
        wait_for("real local tool-worker terminated", lambda: not alive(worker_pid))
        wait_for("detached owner terminated", lambda: not alive(metadata["owner_pid"]))
        # No model request was made: the only assistant remains the seeded completion.
        for session in (source, side_session):
            assistants = [item["message"] for item in entries(session)
                          if item.get("type") == "message" and item["message"]["role"] == "assistant"]
            assert assistants == [source_data[-1]["message"]], assistants
        evidence = {"close_order": order, "source_session_id": source_data[0]["id"],
                    "side_session_id": side_data[0]["id"], "source_pane": source_pane,
                    "side_pane": side_pane, "worker_pid": worker_pid,
                    "source_output": first_output, "side_output": second_output,
                    "survivor_output": survivor_output, "cleanup": cleanup,
                    "attribution": attribution, "public_sdk_module": str(public_sdk(package))}
        print(json.dumps(evidence, sort_keys=True), flush=True)
    except BaseException:
        failed = True
        for pane in (source_pane, side_pane):
            if pane:
                print(f"FAIL {order} {pane}:\n{capture(pane)}", flush=True)
        for name in ("receipt.json", "worker.log", "cleanup.json", "shared-legacy-model.json",
                     f"ctx-model-{source_pane}.json", f"ctx-model-{side_pane}.json"):
            path = runtime / name
            if path.exists():
                print(f"{name}: {path.read_text()}", flush=True)
        raise
    finally:
        tmux("kill-server", check=False)
        metadata = receipt()
        owner_pid = metadata.get("owner_pid")
        worker_pid = metadata.get("worker_pid")
        if owner_pid and alive(owner_pid):
            try:
                wait_for("owned emergency cleanup", lambda: not alive(owner_pid), timeout=3)
            except AssertionError:
                os.kill(owner_pid, signal.SIGTERM)
                try:
                    wait_for("owned owner termination", lambda: not alive(owner_pid), timeout=7)
                except AssertionError:
                    os.kill(owner_pid, signal.SIGKILL)
        if worker_pid and alive(worker_pid):
            os.kill(worker_pid, signal.SIGKILL)
            wait_for("owned worker emergency termination", lambda: not alive(worker_pid), timeout=5)
        if failed:
            print("FAILURE_CLEANUP " + json.dumps({
                "close_order": order, "cleanup": load(runtime / "cleanup.json"),
                "owner_running": bool(owner_pid and alive(owner_pid)),
                "worker_running": bool(worker_pid and alive(worker_pid)),
            }, sort_keys=True), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pi", required=True, type=Path, help="Explicit opt-in: real installed native Pi CLI executable")
    parser.add_argument("--source-first-only", action="store_true", help="Skip the cheap reverse-order case")
    args = parser.parse_args()
    pi = args.pi.resolve(strict=True)
    package = pi.parent.parent.parent
    try:
        public_sdk(package)
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.error(f"--pi must belong to an installed Pi package with its public SDK export: {error}")
    for program in ("tmux", "node", "python3", "jq"):
        if not shutil.which(program):
            parser.error(f"missing prerequisite: {program}")
    with tempfile.TemporaryDirectory(prefix="side-pi-integration-") as temporary:
        root = Path(temporary)
        run_case(root, pi, package, True)
        if not args.source_first_only:
            run_case(root, pi, package, False)
    print("PASS: real Pi /side UI, saved completed-context clone, local guest routing, shared worker lifetime, native ctx.model per-call JJ attribution; NOT container/VM/inference acceptance")


if __name__ == "__main__":
    main()
