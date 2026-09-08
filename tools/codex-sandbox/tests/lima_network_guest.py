#!/usr/bin/python3
"""Run only in the disposable VM created by lima_network_integration.py."""

import hashlib
import ipaddress
import json
import os
from pathlib import Path
import subprocess
import socket
import sys
import time
from urllib.parse import urlsplit
from urllib.request import ProxyHandler, build_opener


IMAGE = "docker.io/library/python@sha256:a190708a2dec1bd18b1decb539f8e8f5407abaa9bf39cacda583f7f8c11db322"
PUBLIC = "policy-public"
OTHER = "policy-other"
LINK = "policy-link"
EGRESS = "policy-egress"
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


def workload(network, *args, check=True, proxy=False, dns=None):
    restrictions = ["--user", "65534:65534", "--read-only", "--pids-limit", "32", "--memory", "128m"] if proxy else []
    return nerd("run", "--rm", "--pull=never", "--network", network,
                "--dns", dns if dns is not None else json.loads(POLICY.read_text())["dns"],
                "--mount", f"type=bind,src={Path(__file__).with_name('dns-client.py')},dst=/dns-client.py,readonly",
                "--cap-drop=ALL", "--security-opt=no-new-privileges", *restrictions, IMAGE,
                *args, check=check)


def require_failure(result):
    if result.returncode == 0:
        raise AssertionError("prohibited operation succeeded")


def partial_policy_probes(config_path, config):
    evidence_path = Path("/tmp/codex-sandbox-policy-fault.json")
    original = dict(config["plugins"][-1])

    def allocations():
        listing = command("containerd-rootless-setuptool.sh", "nsenter", "--", "ls", "-1",
                          f"/var/lib/cni/networks/{PUBLIC}").stdout.splitlines()
        addresses = set()
        for name in listing:
            try:
                addresses.add(str(ipaddress.ip_address(name)))
            except ValueError:
                pass  # host-local also keeps a lock and last-reserved cursor.
        if not addresses:
            raise AssertionError("IPAM inspection did not find the running peer")
        return addresses

    def links():
        # The setup tool deliberately skips RootlessKit's detached netns.
        # Enter it explicitly and require the live bridge as a positive control.
        netns = Path(os.environ["XDG_RUNTIME_DIR"]) / "containerd-rootless/netns"
        output = command("containerd-rootless-setuptool.sh", "nsenter", "--",
                         "nsenter", f"--net={netns}", "--", "ip", "-j", "link", "show").stdout
        names = {link["ifname"] for link in json.loads(output)}
        bridge = next(plugin["bridge"] for plugin in config["plugins"] if plugin["type"] == "bridge")
        if bridge not in names:
            raise AssertionError("network inspection did not find the running peer's bridge")
        return names

    try:
        for mode in ("route-error", "route-kill", "dns-error", "dns-kill"):
            before_containers = set(nerd("ps", "-aq").stdout.split())
            before_allocations = allocations()
            before_links = links()
            evidence_path.unlink(missing_ok=True)
            config["plugins"][-1] = {**original, "type": "policy-fault", "fixtureFailure": mode}
            config_path.write_text(json.dumps(config))
            result = workload(PUBLIC, "echo", "UNRESTRICTED-PROCESS-STARTED", check=False)
            require_failure(result)
            if "UNRESTRICTED-PROCESS-STARTED" in result.stdout:
                raise AssertionError("process ran with partial policy")
            evidence = json.loads(evidence_path.read_text())
            if evidence["mode"] != mode or not evidence["routes"]:
                raise AssertionError("fault did not follow a real route mutation")
            if mode.startswith("dns-") and not any(
                rule.get("ipproto") == "tcp" and rule.get("dport") == 53
                for rule in evidence["rules"]
            ):
                raise AssertionError("fault did not follow a real DNS rule mutation")
            namespace = command("containerd-rootless-setuptool.sh", "nsenter", "--", "test", "!", "-e",
                                evidence["namespace"], check=False)
            if namespace.returncode != 0:
                raise AssertionError("failed startup leaked its network namespace")
            if set(nerd("ps", "-aq").stdout.split()) != before_containers:
                raise AssertionError("failed startup leaked container metadata")
            if allocations() != before_allocations:
                raise AssertionError("failed startup leaked an IPAM allocation")
            if links() != before_links:
                raise AssertionError("failed startup leaked a network interface")
            # Recovery must work without recreating the network or restarting the VM.
            config["plugins"][-1] = original
            config_path.write_text(json.dumps(config))
            workload(PUBLIC, "true")
            print(json.dumps({"probe": mode, "passed": True, "evidence": evidence}), flush=True)
    finally:
        config["plugins"][-1] = original
        config_path.write_text(json.dumps(config))
        evidence_path.unlink(missing_ok=True)


def main():
    endpoint = sys.argv[1]
    marker = urlsplit(endpoint).path.removeprefix("/")
    with build_opener(ProxyHandler({})).open(endpoint, timeout=5) as response:
        if response.read().decode() != marker:
            raise AssertionError("owned host endpoint control failed")
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
        for name, subnet in ((PUBLIC, "10.233.81.0/24"), (OTHER, "10.233.82.0/24"),
                             (LINK, "10.233.83.0/24"), (EGRESS, "10.233.84.0/24")):
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

        link_path = config_path.with_name(f"nerdctl-{LINK}.conflist")
        link_config = json.loads(link_path.read_text())
        bridge = next(plugin for plugin in link_config["plugins"] if plugin["type"] == "bridge")
        bridge.update(isGateway=False, isDefaultGateway=False, ipMasq=False)
        bridge["ipam"]["routes"] = []
        for ranges in bridge["ipam"]["ranges"]:
            for address_range in ranges:
                address_range.pop("gateway", None)
        tuning = next(plugin for plugin in link_config["plugins"] if plugin["type"] == "tuning")
        # Scope tuning to this attachment. Restoring namespace-wide settings on
        # DEL could undo the public policy on an attachment that remains live.
        tuning["sysctl"] = {"net.ipv6.conf.IFNAME.disable_ipv6": "1"}
        link_path.write_text(json.dumps(link_config))

        containers.append("policy-relay")
        nerd("run", "-d", "--name", "policy-relay", "--pull=never", "--network", f"{EGRESS},{LINK}",
             "--mount", f"type=bind,src={Path(__file__).with_name('http-relay.py')},dst=/relay.py,readonly",
             "--user", "65534:65534", "--read-only", "--cap-drop=ALL", "--security-opt=no-new-privileges",
             IMAGE, "python3", "/relay.py", endpoint)

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
        for proxy in (False, True):
            # An owned endpoint is live before denial is tested. Name lookup
            # failure must not be mistaken for enforcement, so use its guest IP.
            host_ip = socket.gethostbyname("host.lima.internal")
            direct = endpoint.replace("host.lima.internal", host_ip)
            result = workload(f"{PUBLIC},{LINK}", "wget", "-T", "3", "-O", "-", direct, check=False, proxy=proxy)
            require_failure(result)
            if "Permission denied" not in result.stderr:
                raise AssertionError("direct host access did not fail at the policy boundary")
            result = workload(f"{PUBLIC},{LINK}", "wget", "-T", "5", "-O", "-", "http://policy-relay:18081/", proxy=proxy)
            if result.stdout.strip() != marker:
                raise AssertionError("authorized relay returned the wrong endpoint")
            workload(PUBLIC, "nslookup", "example.com", proxy=proxy)
            workload(PUBLIC, "wget", "-T", "10", "-O", "/dev/null", "http://example.com/", proxy=proxy)
        # BusyBox ip ignores the "show default" filter and prints connected
        # routes too. Read the kernel table instead of accepting that filter.
        routes = workload(LINK, "cat", "/proc/net/route").stdout.splitlines()[1:]
        if any(route.split()[1] == "00000000" for route in routes):
            raise AssertionError("internal link has a default route")
        ipv6 = workload(LINK, "cat", "/proc/net/if_inet6").stdout.splitlines()
        if any(line.split()[-1] != "lo" for line in ipv6):
            raise AssertionError("internal link has an IPv6 address")
        require_failure(workload(LINK, "sysctl", "-w", "net.ipv6.conf.eth0.disable_ipv6=0", check=False))
        require_failure(workload(LINK, "wget", "-T", "3", "-O", "-", direct, check=False))
        result = workload(LINK, "wget", "-T", "5", "-O", "-", "http://policy-relay:18081/")
        if result.stdout.strip() != marker:
            raise AssertionError("internal-only client cannot reach authorized relay")
        print(json.dumps({"probe": "host denial and authorized internal relay", "passed": True}), flush=True)
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
        backup = POLICY.with_suffix(".fixture-backup")
        if backup.exists():
            raise AssertionError("policy backup already exists")
        command("sudo", "mv", str(POLICY), str(backup))
        try:
            result = workload(PUBLIC, "echo", "UNRESTRICTED-PROCESS-STARTED", check=False, dns=dns)
            require_failure(result)
            if result.stdout or "No such file" not in result.stderr:
                raise AssertionError("missing policy did not reject process startup")
        finally:
            command("sudo", "mv", str(backup), str(POLICY))
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
        partial_policy_probes(config_path, config)
        if failures:
            raise AssertionError("network gate failed: " + ", ".join(failures))
        print("Network, relay, and helper-failure probes passed; launcher interruption is not covered.", flush=True)
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
