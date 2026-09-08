#!/usr/bin/python3
"""Read-only guest preflight for the provisioned outer host."""

import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys


def run(*args):
    result = subprocess.run(args, capture_output=True, text=True, timeout=30)
    if result.returncode:
        print(result.stderr, file=sys.stderr, end="")
    result.check_returncode()
    return result.stdout


def verify_mount(share, index):
    path = Path(share["mountPoint"])
    mounts = json.loads(run("findmnt", "--json", "--target", str(path),
                            "--output", "TARGET,SOURCE,FSTYPE,OPTIONS"))["filesystems"]
    if (len(mounts) != 1 or mounts[0]["target"] != str(path) or
            mounts[0]["fstype"] != "virtiofs" or mounts[0]["source"] != f"mount{index}" or
            ("rw" if share["writable"] else "ro") not in mounts[0]["options"].split(",")):
        raise ValueError(f"effective host share differs from setup: {share!r}; mount{index}: {mounts!r}")
    if not path.is_dir() or not os.access(path, os.R_OK | os.X_OK):
        raise ValueError(f"host share is not visible: {path}")
    if share["writable"] and not os.access(path, os.W_OK):
        raise ValueError(f"host share is not writable: {path}")


def verify_worker(workers, info, namespace):
    if len(workers) != 1:
        raise ValueError("expected one BuildKit worker")
    labels = workers[0]["labels"]
    if (labels.get("org.mobyproject.buildkit.worker.executor") != "containerd" or
            labels.get("org.mobyproject.buildkit.worker.containerd.namespace") != namespace):
        raise ValueError("BuildKit must use the outer containerd namespace")
    if ("name=rootless" not in info.get("SecurityOptions", []) or not info.get("ID") or
            labels.get("org.mobyproject.buildkit.worker.containerd.uuid") != info["ID"]):
        raise ValueError("BuildKit and nerdctl must use the same rootless containerd daemon")
    if info.get("ServerVersion") != "v2.3.3" or workers[0]["buildkitVersion"]["version"] != "v0.31.2":
        raise ValueError("containerd or BuildKit differs from the validated stack")


def main():
    record = json.load(sys.stdin)
    if os.getuid() == 0:
        raise ValueError("outer runtime must run as the unprivileged Lima user")
    if os.environ.get("SANDBOX_GENERATION") != record["generation"]:
        raise ValueError("guest generation differs from the host record")
    base = Path("/usr/local/share/codex-sandbox")
    for name in ("network-policy.json", "rootless-network.json", "verify-host.py", "public-only", "boot-credential.py", "relay-network.py"):
        path = Path("/usr/local/libexec/cni/public-only") if name == "public-only" else base / name
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            raise ValueError(f"untrusted installed policy file: {path}")
        if hashlib.sha256(path.read_bytes()).hexdigest() != record["files"][name]:
            raise ValueError(f"installed policy differs from setup: {path}")
    for name in ("bridge", "host-local", "loopback", "portmap", "firewall", "tuning", "public-only"):
        if not os.access("/usr/local/libexec/cni/" + name, os.X_OK):
            raise ValueError(f"required CNI plugin missing: {name}")
    if "slirp4netns version 1.3.5" not in run("slirp4netns", "--version"):
        raise ValueError("slirp4netns version differs from validated stack")
    pid = int(run("systemctl", "--user", "show", "containerd.service", "--property=MainPID", "--value"))
    arguments = (Path("/proc") / str(pid) / "cmdline").read_bytes().decode().rstrip("\0").split("\0")
    if not {"--net=slirp4netns", "--disable-host-loopback", "--cidr=10.0.2.0/24"}.issubset(arguments):
        raise ValueError("containerd RootlessKit network differs from pinned state")
    state = [arg.removeprefix("--state-dir=") for arg in arguments if arg.startswith("--state-dir=")]
    if len(state) != 1:
        raise ValueError("ambiguous RootlessKit state")
    network = json.loads(run("rootlessctl", "--socket", state[0] + "/api.sock", "info", "--json"))["networkDriver"]
    if network.get("driver") != "slirp4netns" or network.get("dns") != ["10.0.2.3"]:
        raise ValueError("RootlessKit effective DNS differs from policy")
    address = "unix://" + os.environ["XDG_RUNTIME_DIR"] + "/buildkit-" + record["namespace"] + "/buildkitd.sock"
    # Pinning the CIDR restarts containerd and its PartOf BuildKit service.
    # Wait for that socket within run's deadline instead of accepting a race.
    workers = json.loads(run("buildctl", "--addr", address, "--wait", "debug", "workers", "--format", "{{json .}}"))
    info = json.loads(run("nerdctl", "--namespace", record["namespace"], "info", "--format", "{{json .}}"))
    verify_worker(workers, info, record["namespace"])
    if run("nerdctl", "--version").strip() != "nerdctl version 2.3.5":
        raise ValueError("nerdctl differs from the validated stack")
    network_path = Path(record["network_path"])
    if hashlib.sha256(network_path.read_bytes()).hexdigest() != record["network_digest"]:
        raise ValueError("public CNI network changed since setup")
    for index, share in enumerate(record["shares"]):
        verify_mount(share, index)
    print("Guest runtime and installed policy verified", file=sys.stderr)


if __name__ == "__main__":
    main()
