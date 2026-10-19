#!/usr/bin/env python3
"""Own the no-share Lima build VM; never select the infrastructure daemon."""
import argparse
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import socket
import stat
import subprocess
import sys
import time
import uuid

SOURCE = Path(__file__).resolve().parent
SANDBOX = SOURCE.parent / "codex-sandbox"
sys.path.insert(0, str(SANDBOX))
from lima.host import atomic_json, command, machines, private_directory
from lima.docker_platform import current
from network_policy import policy_bytes

USER = "agentbuilder"
DOCTOR_SECONDS = 30


def check_qemu(machine, deadline):
    """Read QMP directly: Lima's Running state does not establish guest execution."""
    if machine.get("vmType") != "qemu":
        return
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        def remaining():
            seconds = deadline - time.monotonic()
            if seconds <= 0:
                raise TimeoutError("QMP inspection deadline exceeded")
            connection.settimeout(seconds)

        remaining()
        connection.connect(str(Path(machine["dir"]) / "qmp.sock"))
        with connection.makefile("rb") as stream:
            def receive():
                remaining()
                line = stream.readline()
                if not line:
                    raise ValueError("QMP connection closed")
                return json.loads(line)

            def execute(name):
                remaining()
                connection.sendall(json.dumps({"execute": name, "id": name}).encode() + b"\n")
                while True:
                    reply = receive()
                    if reply.get("id") == name:
                        if "error" in reply:
                            raise ValueError(f"QMP {name} failed: {reply['error']}")
                        return reply["return"]

            if "QMP" not in receive():
                raise ValueError("QMP greeting is missing")
            execute("qmp_capabilities")
            status = execute("query-status")
            if status["running"]:
                return
            blocks = execute("query-block")
            disks = ", ".join(f"{block['device']}: {block['io-status']}"
                              for block in blocks if block.get("io-status", "ok") != "ok")
    raise ValueError(
        f"QEMU is paused ({status['status']}{'; ' + disks if disks else ''}) despite Lima's Running status; "
        "inspect host disk space and follow tools/codex-sandbox/lima/docker.md#resume-a-qemu-vm-after-disk-space-exhaustion")


def private_file(path):
    metadata = path.lstat()
    if (not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.getuid()
            or metadata.st_mode & 0o077):
        raise ValueError(f"expected an owned private regular file: {path}")


def template(platform, snapshot, generation=""):
    return {
        "minimumLimaVersion": "1.2.1", "vmType": platform.vm_type,
        "arch": platform.guest_arch, "cpus": 6, "memory": "8GiB", "disk": "60GiB",
        "mounts": [], "containerd": {"system": False, "user": False},
        "user": {"name": "sandboxadmin", "uid": 1000, "home": "/home/sandboxadmin",
                 "shell": "/bin/bash", "passwordlessSudo": True},
        "images": [{"location": platform.image, "arch": platform.guest_arch,
                    "digest": platform.image_digest}],
        "ssh": {"loadDotSSHPubKeys": False, "forwardAgent": False},
        "hostResolver": {"enabled": False}, "dns": ["1.1.1.1", "9.9.9.9"],
        "propagateProxyEnv": False,
        "env": {"SANDBOX_DOCKER_ARCH": platform.guest_arch, "SANDBOX_BUILD_GENERATION": generation},
        "provision": [
            {"mode": "dependency", "file": str(snapshot / "install-slirp4netns.py")},
            {"mode": "system", "file": str(snapshot / "docker-install.py")},
        ],
        # The only host listener is Lima's administrator SSH endpoint. The
        # gateway authenticates to that endpoint as the separate build user.
        "portForwards": [{"guestPortRange": [1, 65535], "ignore": True}],
    }


def connection(port):
    return {"AGENT_DOCKER_SSH_USER": USER, "AGENT_DOCKER_SSH_PORT": str(port),
            "DOCKER_HOST": f"ssh://{USER}@host.docker.internal:{port}",
            "AGENT_DOCKER_SSHKEY": "/run/secrets/agent-docker-key"}


class BuildVM:
    def __init__(self, state, access):
        self.state = private_directory(Path(state).expanduser().absolute()).resolve()
        self.access = Path(access).expanduser().absolute()
        self.record_path = self.state / "vm.json"

    @contextmanager
    def locked(self, *, wait=True):
        with (self.state / "lock").open("a") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | (0 if wait else fcntl.LOCK_NB))
            except BlockingIOError as error:
                raise ValueError("another build VM lifecycle operation holds the lock; retry after it finishes") from error
            yield

    def record(self):
        private_file(self.record_path)
        record = json.loads(self.record_path.read_text())
        if (record.get("schema") != 1 or record.get("role") != "build"
                or record.get("access") != str(self.access)
                or not re.fullmatch(r"agent-build-docker(?:-[a-z0-9-]+)?", record.get("instance", ""))):
            raise ValueError("build VM state has a different identity")
        return record

    def machine(self, record, *, timeout=900):
        machine = machines(timeout=timeout).get(record["instance"])
        if machine is None:
            raise ValueError("owned build VM is missing; retain state and provision a new identity")
        digest = hashlib.sha256(json.dumps(machine["config"], sort_keys=True).encode()).hexdigest()
        if digest != record["config_digest"]:
            raise ValueError("build VM configuration changed; inspect before restarting")
        return machine

    def guest(self, record, *args, **kwargs):
        return command("limactl", "shell", "--workdir=/", record["instance"], *args, **kwargs)

    def build_ssh(self, record, *args, machine=None, **kwargs):
        machine = machine if machine is not None else self.machine(record)
        return command("ssh", "-F", "/dev/null", "-T", "-o", "BatchMode=yes",
                       "-o", "IdentitiesOnly=yes", "-o", "StrictHostKeyChecking=yes",
                       "-o", "HostKeyAlias=agent-docker", "-o", "ConnectTimeout=10",
                       "-o", f"UserKnownHostsFile={self.access / 'known_hosts.sandbox'}",
                       "-i", str(self.access / "id_ed25519"),
                       "-p", str(machine["sshLocalPort"]), f"{USER}@127.0.0.1", *args, **kwargs)

    def setup(self, instance):
        if not re.fullmatch(r"agent-build-docker(?:-[a-z0-9-]+)?", instance):
            raise ValueError("build VM requires a separate agent-build-docker instance")
        if self.record_path.exists():
            record = self.record()
            if record["instance"] != instance:
                raise ValueError("build instance changed; use a separate state and access directory")
            if record["phase"] == "ready":
                return self.start()
            if record["phase"] != "creating":
                self.machine(record)
        else:
            if instance in machines():
                raise ValueError("refusing to adopt an existing Lima VM")
            if self.access.exists() or self.access.is_symlink():
                raise ValueError("refusing existing build access; use a fresh access directory")
            configuration = current()
            snapshot = private_directory(self.state / "source")
            files = {
                "docker-install.py": SANDBOX / "lima/docker/install.py",
                "install-slirp4netns.py": SANDBOX / "lima/install-slirp4netns.py",
                "guest-install.py": SOURCE / "guest-install.py",
                "woodpecker-supervisor": SOURCE / "woodpecker-supervisor.sh",
            }
            for name, source in files.items():
                shutil.copyfile(source, snapshot / name)
            (snapshot / "network-policy.json").write_bytes(policy_bytes())
            generation = uuid.uuid4().hex
            atomic_json(self.state / "vm.yaml", template(configuration, snapshot, generation))
            command("limactl", "validate", str(self.state / "vm.yaml"))
            record = {"schema": 1, "role": "build", "phase": "creating", "instance": instance,
                      "access": str(self.access), "generation": generation,
                      "template_digest": hashlib.sha256((self.state / "vm.yaml").read_bytes()).hexdigest(),
                      "files": {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                                for path in snapshot.iterdir()}}
            atomic_json(self.record_path, record)
        if record["phase"] == "creating":
            if hashlib.sha256((self.state / "vm.yaml").read_bytes()).hexdigest() != record["template_digest"]:
                raise ValueError("build template changed during setup")
            existing = machines().get(instance)
            if existing is None:
                command("limactl", "create", "--tty=false", "--name=" + instance,
                        str(self.state / "vm.yaml"))
            machine = machines()[instance]
            if machine["config"].get("env", {}).get("SANDBOX_BUILD_GENERATION") != record["generation"]:
                raise ValueError("build VM creation has an unknown outcome; refusing another creator's instance")
            record["config_digest"] = hashlib.sha256(
                json.dumps(machine["config"], sort_keys=True).encode()).hexdigest()
            record["phase"] = "installing"
            atomic_json(self.record_path, record)
        command("limactl", "start", "--tty=false", instance)
        self.machine(record)
        for name, digest in record["files"].items():
            if hashlib.sha256((self.state / "source" / name).read_bytes()).hexdigest() != digest:
                raise ValueError("build provisioning snapshot changed; retain state for inspection")
        identity = self.guest(record, "cat", "/etc/machine-id", capture_output=True, text=True).stdout.strip()
        if not re.fullmatch(r"[a-f0-9]{32}", identity):
            raise ValueError("build VM machine identity is missing")
        if record.get("machine_id", identity) != identity:
            raise ValueError("build VM identity changed")
        record["machine_id"] = identity
        atomic_json(self.record_path, record)
        private_directory(self.access)
        key = self.access / "id_ed25519"
        if not key.exists():
            command("ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", "agent-docker", "-f", str(key))
        private_file(key)
        staging = self.guest(record, "mktemp", "-d", capture_output=True, text=True).stdout.strip()
        if not re.fullmatch(r"/tmp/tmp\.[a-zA-Z0-9]+", staging):
            raise ValueError("guest staging path is malformed")
        try:
            command("limactl", "copy", *[str(self.state / "source" / name) for name in record["files"]],
                    f"{instance}:{staging}/")
            self.guest(record, "sudo", "python3", staging + "/guest-install.py", staging,
                       input=json.dumps({"generation": record["generation"],
                                         "public_key": key.with_suffix(".pub").read_text().strip()}).encode())
        finally:
            self.guest(record, "rm", "-rf", "--", staging)
        host_key = self.guest(record, "cat", "/usr/local/share/agent-docker/ssh_host_ed25519_key.pub",
                              capture_output=True, text=True).stdout.split()
        if len(host_key) < 2 or host_key[0] != "ssh-ed25519":
            raise ValueError("build VM SSH host key is missing")
        self.publish_text(self.access / "known_hosts.sandbox", f"agent-docker {host_key[0]} {host_key[1]}\n")
        self.doctor(record)
        self.publish_connection(record)
        record["phase"] = "ready"
        atomic_json(self.record_path, record)
        print(f"build VM ready: {instance}; access: {self.access}")
        return record

    def publish_text(self, path, value):
        # Use the existing atomic publisher, then serialize the small text file
        # through the same private sibling/rename boundary.
        temporary = path.with_name(path.name + "." + uuid.uuid4().hex)
        try:
            descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "w") as stream:
                stream.write(value)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)

    def publish_connection(self, record):
        values = connection(self.machine(record)["sshLocalPort"])
        self.publish_text(self.access / "connection.env", "".join(f"{key}={value}\n" for key, value in values.items()))

    def doctor(self, record):
        deadline = time.monotonic() + DOCTOR_SECONDS

        def remaining():
            seconds = deadline - time.monotonic()
            if seconds <= 0:
                raise ValueError(f"build VM checks exceeded {DOCTOR_SECONDS} seconds")
            return seconds

        machine = self.machine(record, timeout=remaining())
        if machine["status"] != "Running":
            raise ValueError(f"build VM is {machine['status']}; run tools/agent-docker/vm.py start on the host")
        try:
            check_qemu(machine, min(deadline, time.monotonic() + 3))
        except OSError as error:
            raise ValueError(f"cannot inspect QEMU execution state: {error}; inspect the VM's QMP socket") from error
        identity = self.guest(record, "cat", "/etc/machine-id", capture_output=True, text=True,
                              timeout=remaining()).stdout.strip()
        if identity != record["machine_id"]:
            raise ValueError("build VM machine identity changed")
        self.guest(record, "sudo", "python3", "/usr/local/share/agent-docker/guest-install.py", "--check",
                   timeout=remaining())
        info = json.loads(self.build_ssh(record, "docker", "info", "--format", "'{{json .}}'",
                                         machine=machine, capture_output=True, text=True, timeout=remaining()).stdout)
        if not any("rootless" in option for option in info["SecurityOptions"]):
            raise ValueError("build Docker daemon is not rootless")
        if record.get("engine_id", info["ID"]) != info["ID"]:
            raise ValueError("build Docker daemon identity changed")
        record["engine_id"] = info["ID"]

    def start(self):
        record = self.record()
        if record["phase"] != "ready":
            raise ValueError("build setup is incomplete; inspect state and rerun setup")
        self.machine(record)
        command("limactl", "start", "--tty=false", record["instance"])
        self.doctor(record)
        self.publish_connection(record)
        print(f"build VM ready: {record['instance']}; restart the sandbox after a port change")
        return record

    def stop(self):
        record = self.record()
        self.machine(record)
        command("limactl", "stop", "--tty=false", record["instance"])

    def teardown(self):
        record = self.record()
        present = record["instance"] in machines()
        if present or record["phase"] != "deleting":
            self.machine(record)
        # Explicit teardown is the only operation that destroys builds. Refuse
        # unexpected access files rather than recursively removing user state.
        names = {"id_ed25519", "id_ed25519.pub", "known_hosts.sandbox", "connection.env"}
        if self.access.exists() and any(path.name not in names for path in self.access.iterdir()):
            raise ValueError("build access directory has unexpected files; inspect before teardown")
        record["phase"] = "deleting"
        atomic_json(self.record_path, record)
        if present:
            command("limactl", "stop", "--tty=false", record["instance"])
            command("limactl", "delete", "--force", record["instance"])
        if self.access.exists():
            for path in self.access.iterdir():
                path.unlink()
            self.access.rmdir()
        self.record_path.unlink()
        print(f"removed build VM {record['instance']}; retained provisioning snapshot at {self.state}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", default=Path.home() / ".local/state/agent-docker")
    parser.add_argument("--access", default=os.environ.get("AGENT_DOCKER_ACCESS_DIR", Path.home() / ".agent-docker-access"))
    parser.add_argument("--instance", default="agent-build-docker")
    parser.add_argument("operation", choices=("setup", "start", "stop", "doctor", "teardown"))
    args = parser.parse_args()
    try:
        owner = BuildVM(args.state, args.access)
        with owner.locked(wait=args.operation != "doctor"):
            if args.operation == "setup":
                owner.setup(args.instance)
            elif args.operation == "doctor":
                owner.doctor(owner.record())
                print("build VM checks passed")
            else:
                getattr(owner, args.operation)()
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        print(f"agent Docker {args.operation} failed: {error}; state retained at {args.state}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
