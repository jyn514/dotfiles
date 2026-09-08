#!/usr/bin/python3
"""Pin the existing RootlessKit CIDR in an owned, idle Lima VM."""

import ipaddress
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import time


def run(*args):
    return subprocess.run(args, check=True, capture_output=True, text=True, timeout=30).stdout


def daemon_state():
    for _ in range(100):
        pid = int(run("systemctl", "--user", "show", "containerd.service", "--property=MainPID", "--value"))
        if pid:
            arguments = (Path("/proc") / str(pid) / "cmdline").read_bytes().decode().rstrip("\0").split("\0")
            if Path(arguments[0]).name == "rootlesskit":
                environment = dict(entry.split("=", 1) for entry in
                                   (Path("/proc") / str(pid) / "environ").read_bytes().decode().split("\0")
                                   if "=" in entry)
                return arguments, environment
        time.sleep(0.1)
    raise RuntimeError("containerd did not start through RootlessKit")


def main():
    network = json.loads(Path(sys.argv[1]).read_text())
    subnet = ipaddress.IPv4Network(network["cidr"])
    # This change pins the existing default; it must not select another network.
    if str(subnet) != "10.0.2.0/24" or str(subnet.network_address + 3) != network["dns"]:
        raise ValueError("setup must preserve the existing slirp4netns subnet and DNS")
    if "--cidr" not in run("rootlesskit", "--help"):
        raise RuntimeError("installed RootlessKit lacks explicit CIDR configuration")
    before, environment = daemon_state()
    cidr_flag = "--cidr=" + str(subnet)
    if "--net=slirp4netns" not in before or "--disable-host-loopback" not in before:
        raise RuntimeError("unexpected RootlessKit network configuration")
    if any(arg.startswith("--cidr") and arg != cidr_flag for arg in before):
        raise RuntimeError("refusing to change an existing RootlessKit subnet")
    flags = shlex.split(environment.get("CONTAINERD_ROOTLESS_ROOTLESSKIT_FLAGS", ""))
    if any(flag not in ("--detach-netns", cidr_flag) for flag in flags):
        raise RuntimeError("refusing to replace custom RootlessKit flags")
    state_dirs = [arg.removeprefix("--state-dir=") for arg in before if arg.startswith("--state-dir=")]
    if len(state_dirs) != 1:
        raise RuntimeError("RootlessKit state directory is ambiguous")
    socket_path = str(Path(state_dirs[0]) / "api.sock")
    effective = json.loads(run("rootlessctl", "--socket", socket_path, "info", "--json"))["networkDriver"]
    if effective.get("driver") != "slirp4netns" or effective.get("dns") != [network["dns"]] or effective.get("childIP") != str(subnet.network_address + 100):
        raise RuntimeError("effective RootlessKit network differs from the existing default")
    dropin = Path.home() / ".config/systemd/user/containerd.service.d/sandbox-dns.conf"
    content = '[Service]\nEnvironment="CONTAINERD_ROOTLESS_ROOTLESSKIT_FLAGS=' + cidr_flag + '"\n'
    if dropin.exists() and dropin.read_text() != content:
        raise RuntimeError("refusing to overwrite a different DNS pin")
    if dropin.exists() and before.count(cidr_flag) == 1:
        # Repeated provisioning must not bounce a matching daemon or trip
        # systemd's restart limit. Effective state was checked above.
        print(json.dumps({"rootlesskit_arguments": before, "dns": network["dns"]}), flush=True)
        return
    dropin.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(dir=dropin.parent, prefix=".sandbox-dns-")
    try:
        with os.fdopen(descriptor, "w") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, dropin)
    finally:
        Path(temporary).unlink(missing_ok=True)
    run("systemctl", "--user", "daemon-reload")
    run("systemctl", "--user", "restart", "containerd.service")
    after, _ = daemon_state()
    if after.count(cidr_flag) != 1 or [arg for arg in after if arg != cidr_flag] != [arg for arg in before if arg != cidr_flag]:
        raise RuntimeError("RootlessKit arguments changed beyond the explicit CIDR pin")
    print(json.dumps({"rootlesskit_arguments": after, "dns": network["dns"]}), flush=True)


if __name__ == "__main__":
    main()
