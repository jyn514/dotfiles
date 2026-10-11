#!/usr/bin/python3
"""Install and audit the build role in the owned Ubuntu guest."""
import hashlib
import json
import os
from pathlib import Path
import pwd
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from urllib.request import urlopen

ROOT = Path("/usr/local/share/agent-docker")
USER = "agentbuilder"
UID = 1001
HOME = Path("/home/agentbuilder")
WOODPECKER_VERSION = "3.15.0"
WOODPECKER_ARCHIVES = {
    "x86_64": ("amd64", "35adf958d616588162d1329fc805f4c2f6e3ef610653175978a0180859ea0c12"),
    "aarch64": ("arm64", "52d807e274fa4de3d48411371216f3074f241a5fb5a1aaddd84553bef969d5ee"),
}


def run(*args, **kwargs):
    return subprocess.run(args, check=True, timeout=240, **kwargs)


def enable_linger():
    try:
        run("loginctl", "enable-linger", USER, capture_output=True, text=True)
        return
    except subprocess.CalledProcessError as error:
        reason = (error.stderr or error.stdout or str(error)).strip()
    except subprocess.TimeoutExpired as error:
        reason = str(error)
    print(f"agent Docker setup: loginctl enable-linger {USER} failed: {reason}", file=sys.stderr)
    # A service can report active while spinning. Include CPU and journal evidence,
    # and bound each probe so an unresponsive D-Bus cannot hide the original failure.
    diagnostics = (
        ("systemctl", "status", "systemd-logind.service", "dbus.service", "--no-pager", "--full"),
        ("ps", "-C", "systemd-logind", "-o", "pid,pcpu,time,stat,args"),
        ("journalctl", "-u", "systemd-logind", "-u", "dbus", "--no-pager", "-n", "30"),
    )
    for command in diagnostics:
        print(f"guest diagnostic: {' '.join(command)}", file=sys.stderr)
        try:
            result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    text=True, timeout=5)
            print(result.stdout, end="", file=sys.stderr)
            if result.returncode:
                print(f"guest diagnostic exited {result.returncode}", file=sys.stderr)
        except (OSError, subprocess.TimeoutExpired) as error:
            print(f"guest diagnostic unavailable: {error}", file=sys.stderr)
    raise SystemExit("agent Docker setup: could not enable linger; inspect the guest logind/D-Bus "
                     "diagnostics, repair the guest service, then rerun the same host setup command. "
                     "VM state retained.")


def as_builder(*args, **kwargs):
    return run("sudo", "-u", USER, "env", "-i", f"HOME={HOME}", f"USER={USER}",
               f"LOGNAME={USER}", "PATH=/usr/local/bin:/usr/bin:/bin",
               f"XDG_RUNTIME_DIR=/run/user/{UID}", f"DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/{UID}/bus",
               *args, **kwargs)


def write_builder(path, content, mode="0600"):
    # Recovery must never follow build-owned paths with guest-root authority.
    as_builder("tee", "--", str(path), input=content, stdout=subprocess.DEVNULL, umask=0o077)
    as_builder("chmod", mode, str(path))


def firewall(policy):
    # Filter the guest's real network namespace by socket owner, outside the
    # build user's namespaces. RootlessKit/slirp traffic retains this UID.
    import ipaddress
    prohibited = ", ".join(str(ipaddress.IPv4Network(item)) for item in policy["prohibited"])
    return (
        "destroy table inet agent_build\n"
        "table inet agent_build {\n"
        f" set prohibited {{ type ipv4_addr; flags interval; elements = {{ {prohibited} }} }}\n"
        " chain output { type filter hook output priority -20; policy accept;\n"
        f"  meta skuid {UID} ct state established ct direction reply accept\n"
        f"  meta skuid {UID} meta nfproto ipv6 reject\n"
        f"  meta skuid {UID} ip daddr @prohibited reject\n"
        " }\n}\n"
    )


def check():
    account = pwd.getpwnam(USER)
    if account.pw_uid != UID or account.pw_dir != str(HOME):
        raise ValueError("build account identity changed")
    groups = as_builder("id", "-Gn", capture_output=True, text=True).stdout.split()
    if any(group in groups for group in ("sudo", "admin", "wheel", "docker")):
        raise ValueError("build account has an administrative group")
    sudo = subprocess.run(["sudo", "-u", USER, "sudo", "-n", "true"], capture_output=True, timeout=10)
    if sudo.returncode == 0:
        raise ValueError("build account has passwordless sudo")
    mounts = json.loads(run("findmnt", "--json", "--output", "FSTYPE", capture_output=True, text=True).stdout)
    def shared(nodes):
        return any(node["fstype"] in ("9p", "virtiofs", "fuse.sshfs")
                   or shared(node.get("children", [])) for node in nodes)
    if shared(mounts["filesystems"]):
        raise ValueError("build guest has a host sharing mount")
    policy = json.loads((ROOT / "network-policy.json").read_text())
    if Path("/etc/agent-build.nft").read_text() != firewall(policy):
        raise ValueError("build network policy file changed")
    run("systemctl", "is-active", "agent-build-policy.service")
    actual = json.loads(run("nft", "-j", "list", "table", "inet", "agent_build",
                           capture_output=True, text=True).stdout)
    expected = json.loads((ROOT / "firewall.json").read_text())
    # Handles and packet counters change across boots; neither is policy.
    def stable(value):
        if isinstance(value, dict):
            return {key: stable(item) for key, item in value.items() if key not in ("handle", "metainfo")}
        if isinstance(value, list):
            return [stable(item) for item in value if not isinstance(item, dict) or "metainfo" not in item]
        return value
    if stable(actual) != stable(expected):
        raise ValueError("running build network policy changed")
    as_builder("systemctl", "--user", "is-active", "docker")
    as_builder("test", "-S", f"/run/user/{UID}/docker.sock")
    as_builder(str(HOME / ".local/bin/woodpecker-cli"), "--version")


def install(staging, config):
    if not re.fullmatch(r"[a-f0-9]{32}", config["generation"]):
        raise ValueError("invalid build generation")
    if not re.fullmatch(r"ssh-ed25519 [A-Za-z0-9+/=]+ agent-docker", config["public_key"]):
        raise ValueError("invalid build public key")
    ROOT.mkdir(mode=0o755, parents=True, exist_ok=True)
    marker = ROOT / "generation"
    if marker.exists() and marker.read_text() != config["generation"]:
        raise ValueError("guest belongs to another build provision")
    if not marker.exists():
        try:
            pwd.getpwnam(USER)
        except KeyError:
            pass
        else:
            raise ValueError("refusing to adopt an existing build account")
        marker.write_text(config["generation"])
    try:
        pwd.getpwnam(USER)
    except KeyError:
        run("useradd", "--uid", str(UID), "--create-home", "--user-group", "--shell", "/bin/bash", USER)
    account = pwd.getpwnam(USER)
    if account.pw_uid != UID or account.pw_dir != str(HOME):
        raise ValueError("build account identity changed")
    for name in ("guest-install.py", "network-policy.json", "woodpecker-supervisor"):
        shutil.copyfile(staging / name, ROOT / name)
        (ROOT / name).chmod(0o644)
    ssh = HOME / ".ssh"
    as_builder("install", "-d", "-m", "0700", str(ssh))
    write_builder(ssh / "authorized_keys", ("restrict " + config["public_key"] + "\n").encode())
    # The build account cannot edit this filter, even with --privileged Docker.
    Path("/etc/agent-build.nft").write_text(firewall(json.loads((ROOT / "network-policy.json").read_text())))
    Path("/etc/systemd/system/agent-build-policy.service").write_text(
        "[Unit]\nDescription=Restrict build account to public IPv4 destinations\n"
        f"Before=user@{UID}.service\n[Service]\nType=oneshot\nRemainAfterExit=yes\n"
        "ExecStart=/usr/sbin/nft -f /etc/agent-build.nft\n[Install]\nWantedBy=multi-user.target\n")
    Path(f"/etc/systemd/system/user@{UID}.service.d").mkdir(exist_ok=True)
    Path(f"/etc/systemd/system/user@{UID}.service.d/build-policy.conf").write_text(
        "[Unit]\nRequires=agent-build-policy.service\nAfter=agent-build-policy.service\n")
    # Avoid Lima's host DNS listener: the build account has no loopback or LAN exception.
    resolver = Path("/etc/resolv.conf")
    resolver.unlink(missing_ok=True)
    resolver.write_text("nameserver 1.1.1.1\nnameserver 9.9.9.9\n")
    hosts = Path("/etc/hosts")
    hostname = os.uname().nodename
    if not any(hostname in line.split()[1:] for line in hosts.read_text().splitlines()):
        with hosts.open("a") as output:
            output.write(f"\n127.0.1.1 {hostname}\n")
    # Lima regenerates /etc/ssh host keys on boot. Keep the build-service pin
    # outside that directory, owned by guest root, across normal VM restarts.
    host_key = ROOT / "ssh_host_ed25519_key"
    if not host_key.exists():
        run("ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(host_key))
    Path("/etc/ssh/sshd_config.d/00-agent-build.conf").write_text(
        f"MaxSessions 20\nHostKey {host_key}\n")
    run("sshd", "-t")
    run("systemctl", "reload", "ssh")
    run("systemctl", "daemon-reload")
    run("systemctl", "enable", "--now", "agent-build-policy.service")
    run("systemctl", "restart", "agent-build-policy.service")
    actual = run("nft", "-j", "list", "table", "inet", "agent_build", capture_output=True, text=True).stdout
    (ROOT / "firewall.json").write_text(actual)
    enable_linger()
    run("systemctl", "start", f"user@{UID}.service")
    as_builder("dockerd-rootless-setuptool.sh", "install")
    as_builder("systemctl", "--user", "enable", "--now", "docker")
    architecture, checksum = WOODPECKER_ARCHIVES[os.uname().machine]
    url = (f"https://github.com/woodpecker-ci/woodpecker/releases/download/v{WOODPECKER_VERSION}/"
           f"woodpecker-cli_linux_{architecture}.tar.gz")
    with tempfile.TemporaryDirectory() as directory:
        archive = Path(directory) / "woodpecker.tar.gz"
        with urlopen(url, timeout=60) as response, archive.open("wb") as output:
            shutil.copyfileobj(response, output)
        if hashlib.sha256(archive.read_bytes()).hexdigest() != checksum:
            raise ValueError("Woodpecker archive checksum mismatch")
        destination = HOME / ".local/bin"
        as_builder("install", "-d", "-m", "0700", str(destination))
        with tarfile.open(archive) as source:
            member = source.getmember("woodpecker-cli")
            if not member.isfile():
                raise ValueError("Woodpecker archive contains no executable")
            with source.extractfile(member) as executable:
                write_builder(destination / "woodpecker-cli", executable.read(), "0755")
    supervisor = HOME / ".local/libexec/agent-docker"
    as_builder("install", "-d", "-m", "0700", str(supervisor))
    as_builder("install", "-m", "0755", str(ROOT / "woodpecker-supervisor"), str(supervisor / "woodpecker-supervisor"))
    units = HOME / ".config/systemd/user"
    as_builder("install", "-d", "-m", "0700", str(units))
    write_builder(units / "agent-docker-reaper.service", (
        "[Service]\nType=oneshot\n"
        f"ExecStart={supervisor}/woodpecker-supervisor reap 00000000000000000000000000000000\n").encode())
    write_builder(units / "agent-docker-reaper.timer", (
        "[Timer]\nOnBootSec=15min\nOnUnitActiveSec=1h\n[Install]\nWantedBy=timers.target\n").encode())
    as_builder("systemctl", "--user", "daemon-reload")
    as_builder("systemctl", "--user", "enable", "--now", "agent-docker-reaper.timer")
    check()


if __name__ == "__main__":
    if os.getuid() != 0:
        raise SystemExit("build guest installation requires guest root")
    if sys.argv[1:] == ["--check"]:
        check()
    else:
        install(Path(sys.argv[1]), json.load(sys.stdin))
