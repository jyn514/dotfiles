#!/usr/bin/env python3
"""Provision and inspect the dedicated Lima sandbox host; never select a launcher backend."""

import argparse
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import uuid


SOURCE = Path(__file__).resolve().parent
GUEST = "/usr/local/share/codex-sandbox"
sys.path.insert(0, str(SOURCE.parent))
from network_policy import policy_bytes


def command(*args, **kwargs):
    if not kwargs.get("capture_output"):
        kwargs.setdefault("stdout", sys.stderr)
    kwargs.setdefault("timeout", 900)
    return subprocess.run(args, check=True, **kwargs)


def private_directory(path):
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise ValueError(f"expected an owned private directory: {path}")
    return path


def atomic_json(path, value):
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=".publish-")
    try:
        with os.fdopen(descriptor, "w") as stream:
            json.dump(value, stream, sort_keys=True, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def shares(read, write):
    result = []
    for writable, paths in ((False, read), (True, write)):
        for raw in paths:
            path = Path(raw).expanduser().resolve(strict=True)
            if not path.is_dir() or any(c in str(path) for c in (",", "\n", "\r", "\t", "\0")):
                raise ValueError(f"unsupported share directory: {path}")
            for previous in result:
                other = Path(previous["location"])
                if path.is_relative_to(other) or other.is_relative_to(path):
                    raise ValueError(f"overlapping shares: {path} and {other}")
            result.append({"location": str(path), "mountPoint": str(path), "writable": writable})
    return sorted(result, key=lambda item: item["location"])


def bind_source(record, raw, writable=False):
    path = Path(raw).expanduser().resolve(strict=True)
    if any(c in str(path) for c in (",", "\n", "\r", "\0")):
        raise ValueError(f"unsupported bind source: {path}")
    matching = [share for share in record["shares"] if path.is_relative_to(Path(share["location"]))]
    if len(matching) != 1 or writable and not matching[0]["writable"]:
        raise ValueError(f"bind source is outside the required shares: {path}")
    if not path.is_file() and not path.is_dir():
        raise ValueError(f"unsupported bind source type: {path}")
    return path


def machines():
    output = command("limactl", "list", "--json", capture_output=True, text=True).stdout
    return {item["name"]: item for line in output.splitlines() if line for item in [json.loads(line)]}


class Host:
    def __init__(self, state):
        self.state = private_directory(Path(state).expanduser().absolute()).resolve()
        self.record_path = self.state / "host.json"

    @contextmanager
    def locked(self):
        with (self.state / "lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            yield

    def record(self):
        record = json.loads(self.record_path.read_text())
        if record.get("schema") != 1 or not re.fullmatch(r"sandbox-host(?:-[a-z0-9-]+)?", record["instance"]):
            raise ValueError("unsupported sandbox host record")
        return record

    def guest(self, record, *args, **kwargs):
        # SSH otherwise consumes the caller's protocol input during inspection.
        if "input" not in kwargs:
            kwargs.setdefault("stdin", subprocess.DEVNULL)
        return command("limactl", "shell", "--workdir", "/tmp", record["instance"], *args, **kwargs)

    def machine(self, record):
        machine = machines().get(record["instance"])
        if machine is None:
            raise ValueError("recorded VM is missing; rerun setup only for unfinished creation")
        if "vm_identity" in record:
            identity = hashlib.sha256((Path(machine["dir"]) / "vz-identifier").read_bytes()).hexdigest()
            if identity != record["vm_identity"]:
                raise ValueError("VM hardware identity changed after setup")
        config = machine["config"]
        digest = hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()
        if record.get("config_digest", digest) != digest:
            raise ValueError("VM configuration changed after creation")
        actual = [{key: mount.get(key, False) for key in ("location", "mountPoint", "writable")}
                  for mount in config.get("mounts", [])]
        if (config.get("env", {}).get("SANDBOX_GENERATION") != record["generation"] or
                sorted(actual, key=lambda item: item["location"]) != record["shares"] or
                config["ssh"].get("forwardAgent") or config["containerd"].get("system") or
                not config["containerd"].get("user")):
            raise ValueError("VM identity or security configuration differs from the setup record")
        return machine

    def setup(self, instance, read, write):
        if not re.fullmatch(r"sandbox-host(?:-[a-z0-9-]+)?", instance):
            raise ValueError("instance must be sandbox-host or sandbox-host-SUFFIX")
        scratch = private_directory(self.state / "scratch")
        requested = shares(read, [*write, str(scratch)])
        # The host record and installed source snapshot must never enter shares.
        if any(self.state.is_relative_to(Path(item["location"])) or
               (Path(item["location"]).is_relative_to(self.state) and
                not Path(item["location"]).is_relative_to(scratch)) for item in requested):
            raise ValueError("a share exposes the host control directory")
        recovering_installation = False
        if self.record_path.exists():
            record = self.record()
            if record["instance"] != instance or record["shares"] != requested:
                raise ValueError("existing setup has different shares or instance; use a separate state directory")
            if record["phase"] == "ready":
                return self.start()
            recovering_installation = record["phase"] == "installing"
        else:
            if instance in machines():
                raise ValueError("refusing to adopt an existing VM without an ownership record")
            generation = uuid.uuid4().hex
            snapshot = self.state / "source"
            private_directory(snapshot)
            for name in ("install-slirp4netns.py", "pin-rootless-network.py", "public-only", "rootless-network.json", "verify-host.py", "configure-network.py", "mount-shares.py", "boot-credential.py", "relay-network.py"):
                shutil.copyfile(SOURCE / name, snapshot / name)
            (snapshot / "network-policy.json").write_bytes(policy_bytes())
            template = (SOURCE / "network-fixture.yaml").read_text()
            template = template.replace("# Feasibility fixture only; not a production VM or launcher default.",
                                        "# Host-owned sandbox VM. Generated by explicit operator setup.")
            template = template.replace("cpus: 2", "cpus: 4").replace("memory: 2GiB", "memory: 4GiB").replace("disk: 12GiB", "disk: 64GiB")
            template = template.replace("mounts: []", "mountType: virtiofs\nmounts: " + json.dumps(requested))
            template = template.replace("file: install-slirp4netns.py", "file: " + json.dumps(str(snapshot / "install-slirp4netns.py")))
            template += "\nenv:\n  SANDBOX_GENERATION: " + json.dumps(generation) + "\n"
            template_path = self.state / "host.yaml"
            template_path.write_text(template)
            command("limactl", "validate", str(template_path))
            record = {"schema": 1, "instance": instance, "generation": generation,
                      "namespace": "default", "shares": requested, "phase": "creating",
                      "template_digest": hashlib.sha256(template.encode()).hexdigest(),
                      "files": {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                                for path in snapshot.iterdir() if path.is_file()}}
            atomic_json(self.record_path, record)
        if hashlib.sha256((self.state / "host.yaml").read_bytes()).hexdigest() != record["template_digest"]:
            raise ValueError("rendered setup template changed")
        snapshot = self.state / "source"
        for name, digest in record["files"].items():
            if hashlib.sha256((snapshot / name).read_bytes()).hexdigest() != digest:
                raise ValueError(f"setup snapshot changed: {name}")
        if instance not in machines():
            if record["phase"] != "creating":
                raise ValueError("recorded VM disappeared after creation; refusing automatic replacement")
            command("limactl", "create", "--tty=false", "--name=" + instance, str(self.state / "host.yaml"))
        machine = self.machine(record)
        record["config_digest"] = hashlib.sha256(json.dumps(machine["config"], sort_keys=True).encode()).hexdigest()
        record["phase"] = "installing"
        atomic_json(self.record_path, record)
        if recovering_installation:
            # SIGTERM can leave Lima's host-agent PID without its socket. This
            # VM has never published readiness, so no session may depend on it.
            # Stop only the identity-checked pending VM before retrying startup.
            command("limactl", "stop", "--force", "--tty=false", instance)
        command("limactl", "start", "--tty=false", instance)
        machine = self.machine(record)
        record["vm_identity"] = hashlib.sha256((Path(machine["dir"]) / "vz-identifier").read_bytes()).hexdigest()
        atomic_json(self.record_path, record)
        temporary = self.guest(record, "mktemp", "-d", capture_output=True, text=True).stdout.strip()
        try:
            for name in record["files"]:
                self.guest(record, "tee", temporary + "/" + name, input=(snapshot / name).read_bytes(), stdout=subprocess.DEVNULL)
            self.guest(record, "sudo", "python3", temporary + "/mount-shares.py", input=json.dumps(record).encode())
            self.guest(record, "python3", temporary + "/pin-rootless-network.py", temporary + "/rootless-network.json")
            self.guest(record, "sudo", "install", "-d", "-m", "755", GUEST)
            for name in ("network-policy.json", "rootless-network.json", "verify-host.py", "boot-credential.py", "relay-network.py"):
                self.guest(record, "sudo", "install", "-m", "644", temporary + "/" + name, GUEST + "/" + name)
            self.guest(record, "sudo", "install", "-m", "755", temporary + "/public-only", "/usr/local/libexec/cni/public-only")
            self.guest(record, "python3", temporary + "/configure-network.py")
            record["network_path"] = machine["config"]["user"]["home"] + "/.config/cni/net.d/default/nerdctl-codex-public-only.conflist"
            network = self.guest(record, "cat", record["network_path"], capture_output=True).stdout
            record["network_digest"] = hashlib.sha256(network).hexdigest()
        finally:
            primary_failure = sys.exc_info()[0] is not None
            try:
                self.guest(record, "rm", "-rf", "--", temporary)
            except (OSError, subprocess.SubprocessError) as error:
                if not primary_failure:
                    raise
                print(f"Guest staging cleanup failed: {error}", file=sys.stderr)
        self.verify(record)
        record["phase"] = "ready"
        atomic_json(self.record_path, record)
        return record

    def verify(self, record):
        self.machine(record)
        digest = self.guest(record, "sha256sum", GUEST + "/verify-host.py", capture_output=True, text=True).stdout.split()[0]
        if digest != record["files"]["verify-host.py"]:
            raise ValueError("installed verifier changed; refusing to execute it")
        self.guest(record, "python3", GUEST + "/verify-host.py", input=json.dumps(record).encode())

    def start(self):
        record = self.record()
        if record["phase"] != "ready":
            raise ValueError("setup is incomplete; rerun setup with the same shares")
        self.machine(record)
        command("limactl", "start", "--tty=false", record["instance"])
        self.verify(record)
        return record

    def check_bind(self, raw, writable=False):
        record = self.record()
        if record["phase"] != "ready":
            raise ValueError("setup is incomplete")
        self.verify(record)
        path = bind_source(record, raw, writable)
        self.guest(record, "test", "-d" if path.is_dir() else "-f", str(path))
        self.guest(record, "test", "-r", str(path))
        if writable:
            self.guest(record, "test", "-w", str(path))
        if path.is_file():
            actual = self.guest(record, "sha256sum", str(path), capture_output=True, text=True).stdout.split()[0]
            if hashlib.sha256(path.read_bytes()).hexdigest() != actual:
                raise ValueError(f"guest bind source differs from the host: {path}")
        return {"source": str(path), "writable": writable}

    def stop(self):
        record = self.record()
        self.machine(record)
        command("limactl", "stop", "--tty=false", record["instance"])
        return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", type=Path, default=Path.home() / ".local/state/codex-sandbox-lima")
    sub = parser.add_subparsers(dest="operation", required=True)
    setup = sub.add_parser("setup")
    setup.add_argument("--instance", default="sandbox-host")
    setup.add_argument("--share-read", action="append", default=[])
    setup.add_argument("--share-write", action="append", default=[])
    sub.add_parser("start")
    sub.add_parser("status")
    sub.add_parser("stop")
    bind = sub.add_parser("check-bind")
    bind.add_argument("--write", action="store_true")
    bind.add_argument("source")
    args = parser.parse_args()
    host = Host(args.state)
    with host.locked():
        if args.operation == "setup":
            record = host.setup(args.instance, args.share_read, args.share_write)
        elif args.operation == "start":
            record = host.start()
        elif args.operation == "check-bind":
            record = host.check_bind(args.source, args.write)
        elif args.operation == "stop":
            record = host.stop()
        else:
            record = host.record()
            machine = host.machine(record)
            if machine["status"] == "Running" and record["phase"] == "ready":
                host.verify(record)
            record = {**record, "status": machine["status"]}
        print(json.dumps(record, sort_keys=True))


if __name__ == "__main__":
    def interrupted(signum, _frame):
        raise SystemExit(128 + signum)

    for signum in (signal.SIGTERM, signal.SIGHUP):
        signal.signal(signum, interrupted)
    try:
        main()
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        sys.exit(str(error))
