"""Outer engine operations. Callers retain resource and session ownership."""

from dataclasses import dataclass
from contextlib import contextmanager
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import uuid

from lima.host import Host
from network_policy import PROHIBITED_ROUTES


DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
NAME = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_.-]*")
PROXY_ENV = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY",
             "http_proxy", "https_proxy", "all_proxy", "no_proxy")
ENGINE_ENV = ("CONTAINERD_ADDRESS", "CONTAINERD_NAMESPACE", "BUILDKIT_HOST",
              "NERDCTL_TOML", "NERDCTL_NAMESPACE")
IMAGE_TYPES = {
    "application/vnd.oci.image.index.v1+json",
    "application/vnd.oci.image.manifest.v1+json",
    "application/vnd.docker.distribution.manifest.list.v2+json",
    "application/vnd.docker.distribution.manifest.v2+json",
}


class RuntimeError(ValueError):
    pass


def digest(value):
    if not isinstance(value, str) or not DIGEST.fullmatch(value):
        raise RuntimeError("invalid image content digest")
    return value


def single_json(output):
    items = json.loads(output)
    if not isinstance(items, list) or len(items) != 1 or not isinstance(items[0], dict):
        raise RuntimeError("expected exactly one inspected object")
    return items[0]


def chain_id(diff_ids):
    if not diff_ids:
        raise RuntimeError("image has no root filesystem layers")
    chain = digest(diff_ids[0])
    for item in diff_ids[1:]:
        chain = "sha256:" + hashlib.sha256((chain + " " + digest(item)).encode()).hexdigest()
    return chain


@dataclass(frozen=True)
class Image:
    reference: str
    content: str
    config: str
    rootfs: str


class Podman:
    """Keep the existing docker-compatible host entrypoint during migration."""

    provider = "podman"
    host_address = "host.docker.internal"

    def builder_image(self, reference):
        return digest(reference)

    def forward_proxy(self, container):
        return subprocess.run(self.argv([
            "exec", "--interactive", container, "/trusted/bin/sandbox-proxy-forward"])).returncode

    def argv(self, arguments, *, cwd=None):
        return ["docker", *arguments]

    def run(self, arguments, *, cwd=None, **kwargs):
        kwargs.setdefault("check", True)
        kwargs.setdefault("text", True)
        if isinstance(self, Lima) and "input" not in kwargs:
            kwargs.setdefault("stdin", subprocess.DEVNULL)
        return subprocess.run(self.argv(arguments, cwd=cwd), cwd=cwd, **kwargs)

    def popen(self, arguments, *, cwd=None, **kwargs):
        return subprocess.Popen(self.argv(arguments, cwd=cwd), cwd=cwd, **kwargs)

    @contextmanager
    def environment_file(self, values):
        for name, value in values.items():
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name) or any(c in value for c in "\0\r\n"):
                raise RuntimeError("environment data cannot be represented in an env file")
        directory = self.host.state / "scratch" if isinstance(self, Lima) else None
        descriptor, name = tempfile.mkstemp(prefix="environment-", dir=directory)
        try:
            with os.fdopen(descriptor, "w") as stream:
                for key, value in values.items():
                    stream.write(key + "=" + value + "\n")
            if isinstance(self, Lima):
                self.host.check_bind(name)
            yield ["--env-file", name]
        finally:
            Path(name).unlink(missing_ok=True)

    def inspect_image(self, reference):
        raw = single_json(self.run(["image", "inspect", reference], capture_output=True).stdout)
        config = digest("sha256:" + raw["Id"].removeprefix("sha256:"))
        return Image(config, config, config, chain_id(raw["RootFS"]["Layers"]))

    def resolve_image(self, reference):
        return self.inspect_image(reference)

    def build(self, tag, dockerfile, context, *, build_args=(), target=None):
        arguments = ["build", "--jobs", "4", "--file", str(dockerfile), "--tag", tag]
        for value in build_args:
            arguments += ["--build-arg", value]
        if target:
            arguments += ["--target", target]
        self.run([*arguments, str(context)], stdout=sys.stderr)
        return self.resolve_image(tag)

    def container_matches_image(self, container, image):
        raw = single_json(self.run(["inspect", container], capture_output=True).stdout)
        return "sha256:" + raw["Image"].removeprefix("sha256:") == image.config

    def network_address(self, container, network):
        raw = single_json(self.run(["inspect", container], capture_output=True).stdout)
        entry = raw["NetworkSettings"]["Networks"].get(network)
        if not entry or not entry.get("IPAddress"):
            raise RuntimeError(f"container is not attached to {network}")
        return str(ipaddress.IPv4Address(entry["IPAddress"]))

    def workload_argv(self, image, arguments, command=(), *, cwd=None, operation="run"):
        return self.argv([operation, "--pull=never", "--http-proxy=false", *arguments,
                          image.reference, *command], cwd=cwd)

    def wait(self, container):
        result = self.run(["wait", container], capture_output=True)
        value = result.stdout.strip()
        if not value.isdecimal() or not 0 <= int(value) <= 255:
            raise RuntimeError("runtime returned an invalid workload exit status")
        return int(value)

    def terminate(self, container):
        self.run(["rm", "--force", container], stdout=subprocess.DEVNULL, timeout=30)

    @contextmanager
    def workload(self, image, name, arguments, command=(), **kwargs):
        """Own one uniquely named workload and await its transport on every exit."""
        process = None
        creation = None
        # The caller allocates the unique name before entry. Cleanup must also
        # cover creation that succeeds remotely but fails before Popen returns.
        try:
            argv = self.workload_argv(image, ["--name", name, *arguments], command, operation="create")
            creation = subprocess.Popen(argv, stdout=subprocess.DEVNULL)
            status = creation.wait()
            if status:
                raise subprocess.CalledProcessError(status, argv)
            attach = ["start", "--attach"]
            if "--interactive" in arguments or "-i" in arguments:
                attach.append("--interactive")
            process = self.popen([*attach, name], **kwargs)
            yield process
        finally:
            primary = sys.exc_info()[0] is not None
            cleanup_error = None
            if creation is not None:
                # A signal during create must not let cleanup race a producer
                # that can still publish the named container after removal.
                try:
                    creation.wait(timeout=30)
                except subprocess.TimeoutExpired:
                    creation.kill()
                    creation.wait()
                    cleanup_error = RuntimeError(f"container creation outcome is unknown; inspect {name}")
            try:
                self.terminate(name)
            except (OSError, ValueError, subprocess.SubprocessError) as error:
                cleanup_error = error
            if process is not None:
                try:
                    process.wait(timeout=30)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
                    cleanup_error = RuntimeError("workload transport did not exit after container removal")
            if cleanup_error is not None:
                if not primary:
                    raise cleanup_error
                print(f"workload cleanup failed: {cleanup_error}", file=sys.stderr)

    def ensure_public_network(self):
        if self.run(["network", "exists", "codex-public-only"], check=False,
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0:
            return
        arguments = ["network", "create", "--ignore", "--subnet", "10.254.254.0/24",
                     "--gateway", "10.254.254.1", "--ip-range", "10.254.254.128/25",
                     "--opt", "isolate=true"]
        for route in PROHIBITED_ROUTES:
            arguments += ["--route", route + ",prohibit"]
        # Podman's native --ignore handles concurrent repository launchers.
        self.run([*arguments, "codex-public-only"], stdout=subprocess.DEVNULL)

    def create_relay_network(self, name, *, internal):
        arguments = ["network", "create", "--opt", "isolate=true"]
        if internal:
            arguments.append("--internal")
        # Relay names are caller-owned and unique. A create race is an error,
        # never permission to adopt another launcher's existing network.
        self.run([*arguments, name], stdout=subprocess.DEVNULL)


class Lima(Podman):
    provider = "lima"
    host_address = "host.lima.internal"

    def builder_image(self, reference):
        if not re.fullmatch(r"localhost/codex-sandbox:sha256-([0-9a-f]{64})@sha256:\1", reference):
            raise RuntimeError("Lima image builder must use sandbox-image in the selected store")
        self.inspect_image(reference)
        return reference

    def forward_proxy(self, container):
        raw = single_json(self.run(["inspect", "--mode=native", container], capture_output=True).stdout)
        container_id = raw["ID"]
        if not re.fullmatch(r"[0-9a-f]{64}", container_id):
            raise RuntimeError("proxy returned an invalid native container ID")
        exec_id = "codex-forward-" + uuid.uuid4().hex
        ctr = ["containerd-rootless-setuptool.sh", "nsenter", "--", "ctr",
               "--namespace", self.record["namespace"], "tasks"]
        command = ["limactl", "shell", "--workdir", "/tmp", self.record["instance"],
                   *ctr, "exec", "--exec-id", exec_id, container_id,
                   "/trusted/bin/sandbox-proxy-forward"]
        def interrupted(signum, _frame):
            raise SystemExit(128 + signum)

        signals = (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)
        handlers = {signum: signal.signal(signum, interrupted) for signum in signals}
        process = None
        try:
            process = subprocess.Popen(command, stdin=subprocess.PIPE)
            # Containerd's CLI can observe EOF before registering its stdin
            # closer. A live exec PID proves startup reached that registration;
            # only then forward bytes and EOF, without changing proxy framing.
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    return process.returncode
                listing = self.guest([*ctr, "ps", container_id], capture_output=True,
                                     text=True, timeout=10).stdout
                if re.search(r'(?m)^[1-9][0-9]*\s+exec_id:"' + re.escape(exec_id) + r'"\s*$', listing):
                    break
                time.sleep(0.05)
            else:
                raise RuntimeError("proxy exec did not publish its native process identity")
            try:
                shutil.copyfileobj(sys.stdin.buffer, process.stdin)
                process.stdin.close()
            except BrokenPipeError:
                pass
            return process.wait()
        finally:
            for signum in signals:
                signal.signal(signum, signal.SIG_IGN)
            try:
                # A dead SSH transport does not prove its guest exec exited.
                self.host.machine(self.record)
                deadline = time.monotonic() + 10
                while True:
                    # Cancellation can precede publication. Keep looking while
                    # the startup producer can still create the guest exec.
                    settled = process is None or process.poll() is not None
                    listing = self.guest([*ctr, "ps", container_id], capture_output=True,
                                         text=True, timeout=10).stdout
                    if re.search(r'(?m)^[1-9][0-9]*\s+exec_id:"' + re.escape(exec_id) + r'"\s*$', listing):
                        self.guest([*ctr, "kill", "--signal", "SIGKILL", "--exec-id", exec_id,
                                    container_id], timeout=10)
                    elif settled:
                        break
                    if time.monotonic() >= deadline:
                        raise RuntimeError(f"guest exec did not settle: {container_id}/{exec_id}")
                    time.sleep(0.05)
            except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
                print(f"proxy exec cleanup failed: {error}", file=sys.stderr)
            finally:
                if process is not None:
                    if process.poll() is None:
                        process.kill()
                        process.wait()
                    try:
                        process.stdin.close()
                    except BrokenPipeError:
                        pass
                for signum, handler in handlers.items():
                    signal.signal(signum, handler)

    def __init__(self, state):
        self.host = Host(state)
        self.record = self.host.record()
        if self.record.get("phase") != "ready":
            raise RuntimeError("Lima setup is incomplete; rerun explicit host setup")
        self.verify()
        machine = self.host.machine(self.record)
        self.buildkit_address = (f"unix:///run/user/{machine['config']['user']['uid']}/"
                                 f"buildkit-{self.record['namespace']}/buildkitd.sock")

    def verify(self):
        # This executes only the installed verifier after checking its digest.
        # Ordinary runtime operations must never repair policy from this checkout.
        self.host.verify(self.record)

    def argv(self, arguments, *, cwd=None):
        self.host.machine(self.record)
        directory = "/tmp" if cwd is None else str(self.host.check_bind(cwd)["source"])
        return ["limactl", "shell", "--workdir", directory, self.record["instance"],
                "env", *["-u" + name for name in (*PROXY_ENV, *ENGINE_ENV)],
                "nerdctl", "--address", "/run/containerd/containerd.sock",
                "--namespace", self.record["namespace"], *arguments]

    def guest(self, arguments, **kwargs):
        return self.host.guest(self.record, *arguments, **kwargs)

    def inspect_image(self, reference):
        arguments = ["image", "inspect", "--mode=native", reference]
        output = self.run(arguments, capture_output=True).stdout
        # Nerdctl 2.3.5 native inspect exits zero with no output for a missing
        # image. Treat only that result as absence; malformed identity is fatal.
        if not output.strip():
            raise subprocess.CalledProcessError(1, arguments, stderr="image is absent")
        items = json.loads(output)
        if not isinstance(items, list) or not items:
            raise RuntimeError("image inspection returned no native image")
        # Nerdctl returns every registered alias of the requested image.
        # Check agreement before choosing a name; aliases are not ambiguity.
        raw = next((item for item in items if item["Image"]["Name"] == reference), items[0])
        if any((item["Image"]["Target"], item["ImageConfigDesc"], item["ImageConfig"]) !=
               (raw["Image"]["Target"], raw["ImageConfigDesc"], raw["ImageConfig"]) for item in items):
            raise RuntimeError("image aliases disagree about native content")
        target = raw["Image"]["Target"]
        if target.get("mediaType") not in IMAGE_TYPES or type(target.get("size")) is not int or target["size"] <= 0:
            raise RuntimeError("image target is not a supported content descriptor")
        if "@" in reference and reference.rsplit("@", 1)[1] != target["digest"]:
            raise RuntimeError("image name digest differs from its descriptor")
        return Image(raw["Image"]["Name"], digest(target["digest"]),
                     digest(raw["ImageConfigDesc"]["digest"]),
                     chain_id(raw["ImageConfig"]["rootfs"]["diff_ids"]))

    def resolve_image(self, reference):
        image = self.inspect_image(reference)
        local_tag = "localhost/codex-sandbox:sha256-" + image.content.removeprefix("sha256:")
        immutable = local_tag + "@" + image.content
        # A computed digest reference is not necessarily registered in containerd.
        # Tag locally, then verify the registration before it can reach run/FROM.
        # BuildKit 0.31 resolves canonical references through their tagged name,
        # then checks that tag's descriptor. Give each digest a separate tag so
        # concurrent builds never compete for a shared :latest registration.
        staging = "localhost/codex-sandbox-stage:" + uuid.uuid4().hex
        try:
            # Snapshot the mutable source under an owned private name before
            # publication. Never overwrite a canonical name another session uses.
            self.register_reference(image.reference, staging)
            staged = self.inspect_image(staging)
            expected = (image.content, image.config, image.rootfs)
            if (staged.content, staged.config, staged.rootfs) != expected:
                raise RuntimeError("image changed during immutable-reference registration")
            self.register_reference(staging, immutable)
            registered = self.inspect_image(immutable)
            if (registered.content, registered.config, registered.rootfs) != expected:
                raise RuntimeError("existing immutable-reference registration differs from image")
            self.register_reference(immutable, local_tag)
            local = self.inspect_image(local_tag)
            if (local.content, local.config, local.rootfs) != expected:
                raise RuntimeError("local FROM registration differs from immutable image")
            return Image(immutable, registered.content, registered.config, registered.rootfs)
        finally:
            primary = sys.exc_info()[0] is not None
            try:
                self.guest(["containerd-rootless-setuptool.sh", "nsenter", "--", "ctr",
                    "--namespace", self.record["namespace"], "images", "rm", staging],
                    stdout=subprocess.DEVNULL)
            except (OSError, subprocess.SubprocessError) as error:
                if not primary:
                    raise
                print(f"image staging cleanup failed: {error}", file=sys.stderr)

    def register_reference(self, source, target):
        # nerdctl tag may fetch missing content. The local image-service
        # operation only registers an existing descriptor in this namespace.
        try:
            self.guest(["containerd-rootless-setuptool.sh", "nsenter", "--", "ctr",
                        "--namespace", self.record["namespace"], "images", "tag",
                        "--local", source, target], capture_output=True)
        except subprocess.CalledProcessError:
            # An existing registration is reusable only after the caller checks
            # its full descriptor. Other errors remain errors if it is absent.
            self.inspect_image(target)

    def build(self, tag, dockerfile, context, *, build_args=(), target=None):
        self.verify()
        context = self.host.check_bind(context)["source"]
        dockerfile = self.host.check_bind(dockerfile)["source"]
        arguments = ["build", "--buildkit-host", self.buildkit_address,
                     "--pull=false", "--file", dockerfile, "--tag", tag]
        for value in build_args:
            arguments += ["--build-arg", value]
        if target:
            arguments += ["--target", target]
        self.run([*arguments, context], stdout=sys.stderr)
        return self.resolve_image(tag)

    def container_matches_image(self, container, image):
        raw = single_json(self.run(["inspect", "--mode=native", container], capture_output=True).stdout)
        if raw["Image"] != image.reference:
            return False
        registered = self.inspect_image(raw["Image"])
        if (registered.content, registered.config) != (image.content, image.config):
            return False
        snapshot = raw["SnapshotKey"]
        if not NAME.fullmatch(snapshot) or raw["Snapshotter"] != "overlayfs":
            raise RuntimeError("unsupported container snapshot identity")
        parent = json.loads(self.guest([
            "containerd-rootless-setuptool.sh", "nsenter", "--", "ctr",
            "--namespace", self.record["namespace"], "snapshots", "info", snapshot,
        ], capture_output=True, text=True).stdout)["Parent"]
        # Snapshot ancestry verifies actual filesystem identity, independent of
        # .Config.Image and names that may now point to a different image.
        return parent == image.rootfs

    def network_address(self, container, network):
        if not NAME.fullmatch(network):
            raise RuntimeError("invalid network name")
        raw = single_json(self.run(["inspect", "--mode=native", container], capture_output=True).stdout)
        config = single_json(self.run(["network", "inspect", "--mode=native", network],
                                      capture_output=True).stdout)["CNI"]
        if config["name"] != network or not re.fullmatch(r"[a-f0-9]{64}", raw["ID"]):
            raise RuntimeError("invalid native network identity")
        ranges = [ipaddress.IPv4Network(item["subnet"])
                  for plugin in config["plugins"] if plugin["type"] == "bridge"
                  for group in plugin["ipam"]["ranges"] for item in group]
        candidates = []
        for interface in raw["Process"]["NetNS"]["Interfaces"]:
            for address in interface["Addrs"]:
                ip = ipaddress.ip_interface(address).ip
                if any(ip in subnet for subnet in ranges):
                    allocation = self.guest([
                        "containerd-rootless-setuptool.sh", "nsenter", "--", "cat",
                        f"/var/lib/cni/networks/{network}/{ip}",
                    ], capture_output=True, text=True).stdout.split()
                    owner = self.record["namespace"] + "-" + raw["ID"]
                    if allocation == [owner, interface["Name"]]:
                        candidates.append(str(ip))
        if len(candidates) != 1:
            raise RuntimeError(f"missing or ambiguous live CNI membership in {network}")
        return candidates[0]

    def workload_argv(self, image, arguments, command=(), *, cwd=None, operation="run"):
        self.verify()
        if not image.reference.endswith("@" + image.content):
            raise RuntimeError("Lima workloads require a registered immutable reference")
        actual = self.inspect_image(image.reference)
        if (actual.content, actual.config, actual.rootfs) != (image.content, image.config, image.rootfs):
            raise RuntimeError("registered workload image changed")
        return self.argv([operation, "--pull=never", *arguments, image.reference, *command], cwd=cwd)

    def ensure_public_network(self):
        self.verify()

    def create_relay_network(self, name, *, internal, owner=None):
        self.verify()
        if "relay-network.py" not in self.record["files"] or self.record["namespace"] != "default":
            raise RuntimeError("Lima host lacks trusted relay provisioning; provision a new host")
        self.guest(["python3", "/usr/local/share/codex-sandbox/relay-network.py", name,
                    "internal" if internal else "egress", owner], stdout=subprocess.DEVNULL)

    def initialize_volume(self, name, uid, gid, owner):
        self.run(["volume", "create", "--label", "dev.codex.volume-owner=" + owner, name],
                 stdout=subprocess.DEVNULL)
        volume = single_json(self.run(["volume", "inspect", name], capture_output=True).stdout)
        if volume.get("Labels", {}).get("dev.codex.volume-owner") != owner:
            raise RuntimeError("refusing to initialize another creator's volume")
        path = Path(volume["Mountpoint"])
        if not path.is_absolute() or path.name != "_data" or path.parent.name != name:
            raise RuntimeError("volume returned an unexpected guest mountpoint")
        # Nerdctl copies image-directory ownership onto an empty volume at its
        # first real mount. A marker prevents that copy from undoing this UID.
        enter = ["containerd-rootless-setuptool.sh", "nsenter", "--"]
        self.guest([*enter, "touch", str(path / ".codex-initialized")], timeout=30)
        self.guest([*enter, "chown", f"{uid}:{gid}", str(path)], timeout=30)


def image_runtime(provider, state=None):
    if provider == "podman":
        return Podman()
    if provider == "lima":
        return Lima(state or Path.home() / ".local/state/codex-sandbox-lima")
    raise RuntimeError(f"unknown outer runtime: {provider}")


def runtime_identity(runtime):
    if runtime.provider == "podman":
        return {"provider": "podman"}
    record = runtime.record
    return {"provider": "lima", "state": str(runtime.host.state),
            **{key: record[key] for key in (
                "instance", "generation", "namespace", "vm_identity", "network_digest")}}


def recorded_runtime(identity):
    if identity == {"provider": "podman"}:
        return Podman()
    fields = {"provider", "state", "instance", "generation", "namespace", "vm_identity", "network_digest"}
    if (not isinstance(identity, dict) or set(identity) != fields or
            identity.get("provider") != "lima" or
            not all(isinstance(value, str) and value for value in identity.values()) or
            not Path(identity["state"]).is_absolute()):
        raise RuntimeError("unsupported recorded runtime; retain session state for explicit recovery")
    runtime = Lima(Path(identity["state"]))
    if runtime_identity(runtime) != identity:
        raise RuntimeError("recorded Lima owner changed; refusing to touch another VM generation or policy")
    return runtime


def state_runtime(state):
    # Legacy shared-state files were exclusively Podman. Never reinterpret
    # absence as the current default, which can change after publication.
    return recorded_runtime(state.get("runtime", {"provider": "podman"}))
