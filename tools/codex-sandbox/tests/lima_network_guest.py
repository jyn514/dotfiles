#!/usr/bin/python3
"""Run only in the disposable VM created by lima_network_integration.py."""

import hashlib
import ipaddress
import json
from pathlib import Path
import subprocess
import sys
import time


IMAGE = "docker.io/library/python@sha256:a190708a2dec1bd18b1decb539f8e8f5407abaa9bf39cacda583f7f8c11db322"
PUBLIC = "policy-public"
OTHER = "policy-other"
POLICY = Path("/usr/local/share/codex-sandbox/network-policy.json")


def command(*args, check=True, input=None):
    result = subprocess.run(args, capture_output=True, text=True, timeout=90, input=input)
    print(json.dumps({"argv": args, "status": result.returncode,
                      "stdout": result.stdout, "stderr": result.stderr}), flush=True)
    if check:
        result.check_returncode()
    return result


def nerd(*args, **kwargs):
    return command("nerdctl", *args, **kwargs)


def workload(network, *args, check=True):
    return nerd("run", "--rm", "--pull=never", "--network", network,
                "--dns", json.loads(POLICY.read_text())["dns"],
                "--mount", f"type=bind,src={Path(__file__).with_name('dns-client.py')},dst=/dns-client.py,readonly",
                "--cap-drop=ALL", "--security-opt=no-new-privileges", IMAGE,
                *args, check=check)


def require_failure(result):
    if result.returncode == 0:
        raise AssertionError("prohibited operation succeeded")


def main():
    policy = POLICY.read_bytes()
    digest = hashlib.sha256(policy).hexdigest()
    nerd("version")
    # This is an owned, credential-free fixture image, not a sandbox image builder.
    nerd("pull", IMAGE)
    networks = []
    containers = []
    failures = []

    def probe(label, network, *args, succeeds=True):
        result = workload(network, *args, check=False)
        passed = (result.returncode == 0) == succeeds
        print(json.dumps({"probe": label, "passed": passed}), flush=True)
        if not passed:
            failures.append(label)
        return result

    try:
        for name, subnet in ((PUBLIC, "10.233.81.0/24"), (OTHER, "10.233.82.0/24")):
            networks.append(name)
            nerd("network", "create", "--subnet", subnet, name)
        config_path = Path.home() / ".config/cni/net.d/default" / f"nerdctl-{PUBLIC}.conflist"
        config = json.loads(config_path.read_text())
        if not any(plugin.get("type") == "firewall" and plugin.get("ingressPolicy") == "same-bridge"
                   for plugin in config["plugins"]):
            raise AssertionError("fixture requires cross-bridge firewall isolation")
        config["plugins"].append({"type": "public-only", "policyDigest": digest})
        config_path.write_text(json.dumps(config))
        print(json.dumps({"policyDigest": digest, "cni": config}), flush=True)

        for name, network in (("policy-peer", PUBLIC), ("policy-stranger", OTHER)):
            containers.append(name)
            nerd("run", "-d", "--name", name, "--pull=never", "--network", network,
                 "--dns", json.loads(policy)["dns"],
                 "--cap-drop=ALL", "--security-opt=no-new-privileges", IMAGE,
                 "python3", "-m", "http.server", "18080", "--directory", "/etc")
        time.sleep(1)
        for name in containers:
            nerd("inspect", name)
            nerd("logs", name)
        workload(PUBLIC, "ip", "route")
        workload(PUBLIC, "wget", "-T", "5", "-O", "/dev/null", "http://policy-peer:18080/alpine-release")
        probe("public DNS", PUBLIC, "nslookup", "example.com")
        dns = json.loads(policy)["dns"]
        for mode in ("tcp", "udp", "denied"):
            probe("DNS " + mode, PUBLIC, "python3", "/dns-client.py", mode, dns)
        probe("public HTTP", PUBLIC, "wget", "-T", "10", "-O", "/dev/null", "http://example.com/")
        foreign = json.loads(nerd("inspect", "policy-stranger").stdout)[0]["NetworkSettings"]["IPAddress"]
        require_failure(workload(PUBLIC, "wget", "-T", "2", "-O", "/dev/null",
                                 f"http://{foreign}:18080/alpine-release", check=False))
        # The reverse direction has no prohibited route. It isolates the CNI
        # firewall check from the public-only plugin's independent route policy.
        local = json.loads(nerd("inspect", "policy-peer").stdout)[0]["NetworkSettings"]["IPAddress"]
        workload(OTHER, "wget", "-T", "5", "-O", "/dev/null", f"http://{foreign}:18080/alpine-release")
        probe("cross-bridge firewall", OTHER, "wget", "-T", "2", "-O", "/dev/null",
              f"http://{local}:18080/alpine-release", succeeds=False)
        # Query routing without sending packets to addresses we do not own.
        for cidr in json.loads(policy)["prohibited"]:
            address = str(ipaddress.IPv4Network(cidr).network_address + 1)
            if address == "127.0.0.1":
                continue  # Loopback's local table intentionally wins over main.
            require_failure(workload(PUBLIC, "ip", "route", "get", address, check=False))
        require_failure(workload(PUBLIC, "ip", "route", "del", "prohibit", "10.0.0.0/8", check=False))
        require_failure(workload(PUBLIC, "sysctl", "-w", "net.ipv6.conf.all.disable_ipv6=0", check=False))
        if workload(PUBLIC, "cat", "/proc/sys/net/ipv6/conf/all/disable_ipv6").stdout.strip() != "1":
            raise AssertionError("IPv6 remains enabled")

        # Stale policy must fail before the process can print its marker.
        config["plugins"][-1]["policyDigest"] = "0" * 64
        config_path.write_text(json.dumps(config))
        result = workload(PUBLIC, "echo", "UNRESTRICTED-PROCESS-STARTED", check=False)
        require_failure(result)
        if "UNRESTRICTED-PROCESS-STARTED" in result.stdout or "stale network policy" not in result.stderr:
            raise AssertionError("process ran after policy failure")
        config["plugins"][-1]["policyDigest"] = digest
        config_path.write_text(json.dumps(config))
        # A correctly hashed but incompatible DNS policy must still fail before
        # startup. Only this disposable fixture deliberately mutates trusted state.
        incompatible = json.dumps({**json.loads(policy), "dns": "10.0.2.4"})
        try:
            command("sudo", "tee", str(POLICY), input=incompatible)
            config["plugins"][-1]["policyDigest"] = hashlib.sha256(incompatible.encode()).hexdigest()
            config_path.write_text(json.dumps(config))
            result = workload(PUBLIC, "echo", "UNRESTRICTED-PROCESS-STARTED", check=False)
            require_failure(result)
            if result.stdout or "resolver differs" not in result.stderr:
                raise AssertionError("DNS mismatch did not reject process startup")
        finally:
            command("sudo", "tee", str(POLICY), input=policy.decode())
            config["plugins"][-1]["policyDigest"] = digest
            config_path.write_text(json.dumps(config))
        workload(PUBLIC, "true")
        if failures:
            raise AssertionError("network gate failed: " + ", ".join(failures))
        print("Basic network and DNS probes passed; full relay and interruption gates remain.", flush=True)
    finally:
        primary_failure = sys.exc_info()[0] is not None
        cleanup_errors = []
        for args in (["rm", "-f", name] for name in reversed(containers)):
            try:
                nerd(*args)
            except (OSError, subprocess.SubprocessError) as error:
                cleanup_errors.append(str(error))
        for name in reversed(networks):
            try:
                nerd("network", "rm", name)
            except (OSError, subprocess.SubprocessError) as error:
                cleanup_errors.append(str(error))
        if cleanup_errors:
            print(json.dumps({"cleanup_errors": cleanup_errors}), file=sys.stderr)
            if not primary_failure:
                raise RuntimeError("fixture resource cleanup failed")


if __name__ == "__main__":
    main()
