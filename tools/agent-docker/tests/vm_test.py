"""Build access must never acquire infrastructure mounts or administrator identity."""
from pathlib import Path
from contextlib import contextmanager
import sys
import hashlib
import json
import tempfile
import socket
import subprocess
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SOURCE))


@contextmanager
def qmp_server(directory, status, blocks=(), *, stall=False):
    """A disposable QMP peer; only the read-only commands used by doctor are accepted."""
    commands = []
    errors = []
    finished = threading.Event()
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
        listener.bind(str(Path(directory) / "qmp.sock"))
        listener.listen()
        listener.settimeout(2)

        def serve():
            try:
                with listener.accept()[0] as connection:
                    if stall:
                        finished.wait(2)
                        return
                    connection.sendall(b'{"QMP":{"version":{},"capabilities":[]}}\r\n')
                    with connection.makefile("rb") as stream:
                        for line in stream:
                            request = json.loads(line)
                            name = request["execute"]
                            commands.append(name)
                            result = {"qmp_capabilities": {}, "query-status": status,
                                      "query-block": blocks}[name]
                            # Events may arrive between command replies.
                            connection.sendall(b'{"event":"STOP"}\r\n')
                            connection.sendall(json.dumps({"return": result, "id": request["id"]}).encode() + b"\r\n")
            except Exception as error:
                errors.append(error)

        thread = threading.Thread(target=serve, daemon=True)
        thread.start()
        try:
            yield commands
        finally:
            finished.set()
            thread.join(3)
            if thread.is_alive():
                raise AssertionError("QMP fixture did not stop")
            if errors:
                raise errors[0]


class BuildVMTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import vm
        cls.vm = vm

    def test_build_template_has_no_host_shares_or_automatic_port_forwards(self):
        for kind, architecture in (("qemu", "x86_64"), ("vz", "aarch64")):
            with self.subTest(kind=kind):
                platform = SimpleNamespace(vm_type=kind, guest_arch=architecture,
                                           image="https://example.invalid/image", image_digest="sha256:pin")
                template = self.vm.template(platform, Path("/snapshot"))
                self.assertEqual([], template["mounts"])
                self.assertFalse(template["ssh"]["forwardAgent"])
                self.assertFalse(template["ssh"]["loadDotSSHPubKeys"])
                self.assertEqual([{"guestPortRange": [1, 65535], "ignore": True}],
                                 template["portForwards"])
                self.assertEqual({"system": False, "user": False}, template["containerd"])
                self.assertFalse(template["propagateProxyEnv"])

    def test_docker_connection_uses_build_identity_and_new_state(self):
        connection = self.vm.connection(23456)
        self.assertEqual("agentbuilder", connection["AGENT_DOCKER_SSH_USER"])
        self.assertEqual("ssh://agentbuilder@host.docker.internal:23456", connection["DOCKER_HOST"])
        self.assertEqual("/run/secrets/agent-docker-key", connection["AGENT_DOCKER_SSHKEY"])
        self.assertFalse(any("PODMAN" in key for key in connection))

    def test_access_files_reject_symlinks_and_shared_permissions(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "key"
            path.write_text("private")
            path.chmod(0o600)
            self.vm.private_file(path)
            path.chmod(0o644)
            with self.assertRaises(ValueError):
                self.vm.private_file(path)
            alias = Path(directory) / "alias"
            alias.symlink_to(path)
            with self.assertRaises(ValueError):
                self.vm.private_file(alias)

    def test_failed_creation_refuses_a_vm_owned_by_another_generation(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "state"
            access = Path(directory) / "access"
            owner = self.vm.BuildVM(state, access)
            template = state / "vm.yaml"
            template.write_text("{}")
            record = {"schema": 1, "role": "build", "phase": "creating",
                      "instance": "agent-build-docker-test", "access": str(access),
                      "generation": "a" * 32, "files": {},
                      "template_digest": hashlib.sha256(template.read_bytes()).hexdigest()}
            self.vm.atomic_json(owner.record_path, record)
            machine = {"config": {"env": {"SANDBOX_BUILD_GENERATION": "b" * 32}}}
            with patch.object(self.vm, "machines", return_value={record["instance"]: machine}), \
                    patch.object(self.vm, "command") as command:
                with self.assertRaisesRegex(ValueError, "another creator"):
                    owner.setup(record["instance"])
                command.assert_not_called()

    def test_failed_creation_recovers_the_owned_vm_without_recreating_it(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "state"
            access = Path(directory) / "access"
            owner = self.vm.BuildVM(state, access)
            template = state / "vm.yaml"
            template.write_text("{}")
            record = {"schema": 1, "role": "build", "phase": "creating",
                      "instance": "agent-build-docker-test", "access": str(access),
                      "generation": "a" * 32, "files": {},
                      "template_digest": hashlib.sha256(template.read_bytes()).hexdigest()}
            self.vm.atomic_json(owner.record_path, record)
            machine = {"config": {"env": {"SANDBOX_BUILD_GENERATION": record["generation"]}}}
            with patch.object(self.vm, "machines", return_value={record["instance"]: machine}), \
                    patch.object(self.vm, "command") as command, \
                    patch.object(owner, "guest", side_effect=OSError("guest unavailable")):
                with self.assertRaisesRegex(OSError, "guest unavailable"):
                    owner.setup(record["instance"])
                command.assert_called_once_with("limactl", "start", "--tty=false", record["instance"])
            self.assertEqual("installing", json.loads(owner.record_path.read_text())["phase"])

    def test_teardown_retries_access_cleanup_after_vm_deletion(self):
        with tempfile.TemporaryDirectory() as directory:
            owner = self.vm.BuildVM(Path(directory) / "state", Path(directory) / "access")
            owner.access.mkdir()
            (owner.access / "connection.env").write_text("stale access")
            self.vm.atomic_json(owner.record_path, {
                "schema": 1, "role": "build", "phase": "deleting",
                "instance": "agent-build-docker-test", "access": str(owner.access)})
            with patch.object(self.vm, "machines", return_value={}), \
                    patch.object(self.vm, "command") as command:
                owner.teardown()
                command.assert_not_called()
            self.assertFalse(owner.access.exists())
            self.assertFalse(owner.record_path.exists())

    def test_qmp_distinguishes_running_from_paused_and_reports_disk_errors(self):
        cases = [
            ({"running": True, "status": "running"}, [], None),
            ({"running": False, "status": "io-error"},
             [{"device": "boot-disk", "io-status": "nospace"}], "boot-disk: nospace"),
            ({"running": False, "status": "paused"}, [], "QEMU is paused \\(paused\\)"),
            ({"running": False, "status": "io-error"},
             [{"device": "data-disk", "io-status": "failed"}], "data-disk: failed"),
        ]
        for status, blocks, error in cases:
            with self.subTest(status=status, blocks=blocks), tempfile.TemporaryDirectory() as directory:
                machine = {"vmType": "qemu", "status": "Running", "dir": directory}
                with qmp_server(directory, status, blocks) as commands:
                    if error:
                        with self.assertRaisesRegex(ValueError, error):
                            self.vm.check_qemu(machine, time.monotonic() + 1)
                    else:
                        self.vm.check_qemu(machine, time.monotonic() + 1)
                self.assertEqual(["qmp_capabilities", "query-status"] +
                                 ([] if status["running"] else ["query-block"]), commands)

    def test_unresponsive_qmp_is_bounded_and_non_qemu_needs_no_socket(self):
        self.vm.check_qemu({"vmType": "vz"}, time.monotonic() + 1)
        with tempfile.TemporaryDirectory() as directory:
            with qmp_server(directory, {}, stall=True):
                started = time.monotonic()
                with self.assertRaises(TimeoutError):
                    self.vm.check_qemu({"vmType": "qemu", "dir": directory}, started + 0.1)
                self.assertLess(time.monotonic() - started, 1)

    def test_doctor_checks_execution_before_contacting_guest(self):
        with tempfile.TemporaryDirectory() as directory:
            owner = self.vm.BuildVM(Path(directory) / "state", Path(directory) / "access")
            machine = {"status": "Running", "vmType": "qemu", "dir": directory}
            with qmp_server(directory, {"running": False, "status": "io-error"},
                            [{"device": "boot-disk", "io-status": "nospace"}]), \
                    patch.object(owner, "machine", return_value=machine), \
                    patch.object(owner, "guest") as guest:
                with self.assertRaisesRegex(ValueError, "nospace.*resume-a-qemu"):
                    owner.doctor({})
                guest.assert_not_called()

    def test_doctor_bounds_each_external_check_and_accepts_healthy_engine(self):
        import lima.host as host
        for blocked in ("machine", "identity", "policy", "docker", None):
            with self.subTest(blocked=blocked), tempfile.TemporaryDirectory() as directory:
                owner = self.vm.BuildVM(Path(directory) / "state", Path(directory) / "access")
                record = {"machine_id": "identity", "engine_id": "engine", "instance": "agent-build-docker-test",
                          "config_digest": hashlib.sha256(json.dumps({}, sort_keys=True).encode()).hexdigest()}
                calls = []
                budgets = []
                run = self.vm.command

                def check(phase, result, kwargs):
                    calls.append(phase)
                    budgets.append(kwargs["timeout"])
                    if phase == blocked:
                        return run(sys.executable, "-c", "import time; time.sleep(5)", timeout=kwargs["timeout"])
                    self.assertGreater(kwargs["timeout"], 0)
                    self.assertLessEqual(kwargs["timeout"], 0.2)
                    return result

                def command(*args, **kwargs):
                    if args[:2] == ("limactl", "list"):
                        return check("machine", SimpleNamespace(stdout=json.dumps({
                            "name": record["instance"], "status": "Running", "vmType": "vz",
                            "config": {}, "sshLocalPort": 2222})), kwargs)
                    if args[0] == "ssh":
                        return check("docker", SimpleNamespace(stdout=json.dumps(
                            {"ID": "engine", "SecurityOptions": ["name=rootless"]})), kwargs)
                    return check("identity" if "cat" in args else "policy",
                                 SimpleNamespace(stdout="identity\n"), kwargs)

                with patch.object(self.vm, "DOCTOR_SECONDS", 0.2), \
                        patch.object(host, "command", side_effect=command), \
                        patch.object(self.vm, "command", side_effect=command):
                    started = time.monotonic()
                    if blocked:
                        with self.assertRaises(subprocess.TimeoutExpired):
                            owner.doctor(record)
                        self.assertEqual(blocked, calls[-1])
                    else:
                        owner.doctor(record)
                        self.assertEqual(["machine", "identity", "policy", "docker"], calls)
                        self.assertTrue(all(later < earlier for earlier, later in zip(budgets, budgets[1:])),
                                        "each check must consume the same deadline")
                    self.assertLess(time.monotonic() - started, 2)

    def test_doctor_lock_does_not_wait_for_another_lifecycle_operation(self):
        with tempfile.TemporaryDirectory() as directory:
            owner = self.vm.BuildVM(Path(directory) / "state", Path(directory) / "access")
            with owner.locked():
                with self.assertRaisesRegex(ValueError, "lifecycle operation holds the lock"):
                    with owner.locked(wait=False):
                        self.fail("acquired occupied lock")


if __name__ == "__main__":
    unittest.main()
