#!/usr/bin/env python3
"""Opt-in network feasibility probe; never starts a real sandbox session."""

import argparse
import ast
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import signal
import subprocess
import sys
import threading
import uuid


ROOT = Path(__file__).resolve().parents[1]
GUEST_PROBE = "/usr/local/share/codex-sandbox/fixture/probe.py"


def command(*args, **kwargs):
    print("+ " + repr(args), file=sys.stderr, flush=True)
    return subprocess.run(args, check=True, timeout=900, **kwargs)


def launcher_policy():
    # Until cutover, the launcher remains the sole CIDR authority. Parse the
    # literal without importing launcher code or copying its policy constants.
    tree = ast.parse((ROOT / "codex-sandbox").read_text())
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "PROHIBITED_ROUTES"
            for target in node.targets
        ):
            network = json.loads((ROOT / "lima/rootless-network.json").read_text())
            return json.dumps({"version": 2, "ipv6": "disabled", "dns": network["dns"],
                               "prohibited": ast.literal_eval(node.value)}).encode()
    raise ValueError("launcher policy owner moved; update the fixture explicitly")


def install_probe(instance, endpoint):
    def guest(*args, **kwargs):
        return command("limactl", "shell", "--workdir", "/tmp", instance, *args, **kwargs)

    result = command("limactl", "list", "--json", instance, capture_output=True, text=True)
    machine = json.loads(result.stdout)
    config = machine["config"]
    if config.get("mounts") or config["ssh"].get("forwardAgent") or config["containerd"].get("system"):
        raise ValueError("fixture must have no shares, SSH forwarding, or system containerd")
    guest("slirp4netns", "--version")
    scratch = guest("mktemp", "-d", "/tmp/sandbox-policy.XXXXXXXX", capture_output=True, text=True).stdout.strip()
    for name, content in (("public-only", (ROOT / "lima/public-only").read_bytes()),
                          ("network-policy.json", launcher_policy()),
                          ("rootless-network.json", (ROOT / "lima/rootless-network.json").read_bytes()),
                          ("pin-rootless-network.py", (ROOT / "lima/pin-rootless-network.py").read_bytes()),
                          ("dns-client.py", (ROOT / "tests/lima_dns_client.py").read_bytes()),
                          ("policy-fault", (ROOT / "tests/lima_policy_fault.py").read_bytes()),
                          ("http-relay.py", (ROOT / "tests/lima_http_relay.py").read_bytes()),
                          ("probe.py", (ROOT / "tests/lima_network_guest.py").read_bytes())):
        guest("tee", f"{scratch}/{name}", input=content, stdout=subprocess.DEVNULL)
    guest("python3", f"{scratch}/pin-rootless-network.py", f"{scratch}/rootless-network.json")
    guest("sudo", "install", "-d", "-m", "755", "/usr/local/share/codex-sandbox")
    guest("sudo", "install", "-m", "644", f"{scratch}/network-policy.json", "/usr/local/share/codex-sandbox/network-policy.json")
    guest("sudo", "install", "-m", "755", f"{scratch}/public-only", "/usr/local/libexec/cni/public-only")
    guest("sudo", "install", "-m", "755", f"{scratch}/policy-fault", "/usr/local/libexec/cni/policy-fault")
    guest("sudo", "install", "-d", "-m", "755", str(Path(GUEST_PROBE).parent))
    for name in ("probe.py", "dns-client.py", "http-relay.py"):
        guest("sudo", "install", "-m", "644", f"{scratch}/{name}", str(Path(GUEST_PROBE).with_name(name)))
    guest("python3", GUEST_PROBE, endpoint)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--keep", action="store_true", help="stop and retain the owned fixture for inspection")
    parser.add_argument("--reboot", action="store_true", help="repeat probes after a VM stop/start without reinstalling policy")
    args = parser.parse_args()
    instance = "sandbox-network-fixture-" + uuid.uuid4().hex[:12]
    print(f"Owned fixture: {instance}", flush=True)
    marker = uuid.uuid4().hex

    class Endpoint(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path != "/" + marker:
                self.send_error(404)
                return
            self.send_response(200)
            self.end_headers()
            self.wfile.write(marker.encode())

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Endpoint)
    serving = threading.Thread(target=server.serve_forever, daemon=True)
    serving.start()
    endpoint = f"http://host.lima.internal:{server.server_port}/{marker}"
    def interrupted(signum, _frame):
        raise SystemExit(128 + signum)

    previous = {signum: signal.signal(signum, interrupted)
                for signum in (signal.SIGTERM, signal.SIGHUP)}
    # Record ownership before create: it can leave an instance after failure.
    try:
        command("limactl", "create", "--tty=false", "--name=" + instance,
                str(ROOT / "lima/network-fixture.yaml"))
        command("limactl", "start", "--tty=false", instance)
        install_probe(instance, endpoint)
        if args.reboot:
            command("limactl", "stop", "--tty=false", instance)
            command("limactl", "start", "--tty=false", instance)
            command("limactl", "shell", "--workdir", "/tmp", instance, "python3", GUEST_PROBE, endpoint)
    finally:
        # Preserve the primary error if recovery itself fails. No shared VM is stopped.
        primary_failure = sys.exc_info()[0] is not None
        for signum in previous:
            signal.signal(signum, signal.SIG_IGN)
        try:
            operation = "stop" if args.keep else "delete"
            command("limactl", operation, "--force", "--tty=false", instance)
        except (OSError, subprocess.SubprocessError) as error:
            print(f"Fixture cleanup failed: {error}; inspect {instance}", file=sys.stderr)
            if not primary_failure:
                raise
        finally:
            server.shutdown()
            server.server_close()
            serving.join()
            for signum, handler in previous.items():
                signal.signal(signum, handler)


if __name__ == "__main__":
    main()
