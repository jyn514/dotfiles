"""Build access must never acquire infrastructure mounts or administrator identity."""
from pathlib import Path
import sys
import hashlib
import json
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SOURCE))


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


if __name__ == "__main__":
    unittest.main()
