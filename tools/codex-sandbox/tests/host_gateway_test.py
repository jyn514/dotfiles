"""Host gateway ownership without loading the launcher or its mutable State."""
from dataclasses import replace
import io
import json
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import host_gateway as gateway
from relay_lifecycle import RelayResourcePlan
from sandbox_runtime import ContainerRuntime, Lima, VMRuntime
from docker_runtime import Docker


class HostGatewayTest(unittest.TestCase):
    def setUp(self):
        self.runtime = ContainerRuntime()
        self.runtime.run = Mock(return_value=SimpleNamespace(returncode=0, stdout=""))
        self.runtime.network_addresses = Mock(return_value={
            "gateway-link": "10.0.0.2", "gateway-egress": "10.0.0.3"})
        self.resources = RelayResourcePlan("gateway-link", "gateway-egress", "gateway")
        self.handle = gateway.GatewayHandle(self.runtime, self.resources)
        self.build = gateway.BuildSshProjection(
            user="worker", port=2345, key=Path("/key"), known_hosts=Path("/known"),
            guest_key="/guest-key", guest_known_hosts="/container-known")
        self.bridge = Mock(port=4321)
        self.factory = Mock(return_value=self.bridge)
        patcher = patch.object(gateway, "FixedTcpBridge", self.factory)
        patcher.start()
        self.addCleanup(patcher.stop)

    def prepare(self, capabilities=frozenset({"nested-containers"})):
        return self.handle.prepare(capabilities, self.build)

    def start(self, **kwargs):
        self.handle.start(image="synthetic-image", network_flags=["--dns", "192.0.2.42"], **kwargs)

    def test_partial_network_startup_is_owned_and_cleaned(self):
        create = Mock(side_effect=[None, OSError("egress failed")])
        def runtime(command, **_kwargs):
            if command[:2] == ["network", "ls"]:
                return SimpleNamespace(returncode=0, stdout="gateway-link\n")
            if command[:2] == ["network", "inspect"]:
                return SimpleNamespace(returncode=0, stdout=self.handle.owner + "\n")
            return SimpleNamespace(returncode=0, stdout="")
        self.runtime.run.side_effect = runtime
        with patch.object(gateway, "create_relay_network", create):
            with self.assertRaisesRegex(OSError, "egress failed"):
                self.prepare()
            self.assertRegex(self.handle.owner, r"\A[0-9a-f]{32}\Z")
            result = self.handle.cleanup(19)
        self.assertEqual(19, result.primary_status)
        self.assertFalse(result.remaining)
        self.assertTrue(any(call.args[0][:2] == ["network", "rm"]
                            for call in self.runtime.run.call_args_list))
        self.bridge.stop.assert_called_once()

    def test_gateway_requires_both_nested_capability_and_build_service(self):
        for capabilities, build in ((frozenset(), self.build),
                                     (frozenset({"nested-containers"}), None)):
            with self.subTest(capabilities=capabilities, build=build):
                result = self.handle.prepare(capabilities, build)
                self.assertEqual((), result.arguments)
                self.assertFalse(result.selected)
                self.assertFalse(result.build_available)
        self.factory.assert_not_called()
        self.runtime.run.assert_not_called()

    def test_tic_only_prepares_shared_networks_without_build_bridge(self):
        result = self.handle.prepare(frozenset({"tic"}), None)
        self.assertEqual((), result.arguments)
        self.assertTrue(result.selected)
        self.assertFalse(result.build_available)
        self.assertIsNone(self.handle.build_bridge)
        self.assertEqual(2, self.runtime.run.call_count)
        self.factory.assert_not_called()

    def test_build_gateway_uses_selected_service_port_and_bridge(self):
        result = self.prepare()
        self.start()
        self.factory.assert_called_once_with(("127.0.0.1", 2345))
        self.assertTrue(result.build_available)
        self.assertIn("DOCKER_HOST=ssh://worker@gateway:2222", result.arguments)
        command = self.runtime.run.call_args.args[0]
        self.assertEqual("4321", command[command.index("--build-port") + 1])
        self.assertEqual("192.0.2.42", command[command.index("--dns") + 1])
        self.bridge.allow_peers.assert_called_once_with({"10.0.0.2", "10.0.0.3", "127.0.0.1"})

    def test_direct_host_loopback_preserves_ssh_projection_and_cleanup(self):
        self.assertFalse(ContainerRuntime.host_loopback_access)
        self.assertTrue(Lima.host_loopback_access)
        self.assertTrue(Docker.host_loopback_access)
        for tic in (False, True):
            with self.subTest(tic=tic), socket.socket() as listener:
                listener.bind(("127.0.0.1", 0)); listener.listen()
                port = listener.getsockname()[1]
                runtime = Mock(host_loopback_access=True, host_address="host.lima.internal")
                runtime.network_addresses.return_value = self.runtime.network_addresses.return_value
                handle = gateway.GatewayHandle(runtime, self.resources)
                removed = []
                with patch.object(gateway, "create_relay_networks"), patch.object(
                        gateway, "remove_owned_resource",
                        side_effect=lambda runtime, kind, name, owner, **kw: removed.append(name)):
                    result = handle.prepare(frozenset({"nested-containers", "tic"} if tic else
                                                     {"nested-containers"}), replace(self.build, port=port))
                    probe, _ = listener.accept(); probe.close()
                    handle.start(image="direct-image", network_flags=[], tic_port=4567 if tic else None)
                    self.assertIsNone(handle.build_bridge)
                    self.assertEqual(port, handle.build_port)
                    self.assertEqual(1, result.arguments.count("--network"))
                    self.assertIn("DOCKER_HOST=ssh://worker@gateway:2222", result.arguments)
                    self.assertIn("AGENT_DOCKER_SSHKEY=/guest-key", result.arguments)
                    self.assertIn("AGENT_DOCKER_KNOWN_HOSTS=/container-known", result.arguments)
                    self.assertIn("type=bind,src=/known,dst=/container-known,readonly", result.arguments)
                    self.assertIn("type=bind,src=/key,dst=/guest-key,readonly", result.arguments)
                    command = runtime.start_detached.call_args.args[3]
                    self.assertEqual(str(port), command[command.index("--build-port") + 1])
                    self.assertEqual(tic, "--tic-port" in command)
                    self.assertEqual("host.lima.internal", command[command.index("--host") + 1])
                    self.assertFalse(handle.cleanup(0).remaining)
                    self.assertEqual("gateway", removed[0])
                    self.assertEqual({"gateway", "gateway-link", "gateway-egress"}, set(removed))
                    self.assertFalse(any(i.startswith("bridge:") for i in handle.registry.identities))
        self.factory.assert_not_called()

    def test_direct_stopped_service_warns_but_keeps_tic_only_when_selected(self):
        for tic in (False, True):
            with self.subTest(tic=tic):
                runtime = Mock(host_loopback_access=True)
                handle = gateway.GatewayHandle(runtime, self.resources)
                with patch.object(gateway, "create_relay_networks") as create, patch(
                        "socket.create_connection", side_effect=ConnectionRefusedError("refused")), patch(
                        "sys.stderr", new_callable=io.StringIO) as stderr:
                    result = handle.prepare(frozenset({"nested-containers", "tic"} if tic else
                                                     {"nested-containers"}), self.build)
                self.assertFalse(result.build_available)
                self.assertEqual(tic, result.selected)
                self.assertEqual(tic, create.called)
                self.assertIn("tools/agent-docker/vm.py start", stderr.getvalue())
                self.assertIsNone(handle.build_port)
                self.assertIsNone(handle.build_bridge)

    def test_stopped_bridged_service_warns_and_creates_no_gateway(self):
        self.bridge.start.side_effect = ConnectionRefusedError(111, "refused")
        with patch("sys.stderr", new_callable=io.StringIO) as stderr:
            result = self.prepare()
        self.assertFalse(result.selected)
        self.assertFalse(result.build_available)
        self.runtime.run.assert_not_called()
        self.assertIn("tools/agent-docker/vm.py start", stderr.getvalue())

    def test_stopped_build_observation_survives_later_network_failure(self):
        self.runtime.host_loopback_access = True
        with patch("socket.create_connection", side_effect=ConnectionRefusedError("refused")), patch.object(
                gateway, "create_relay_networks", side_effect=OSError("networks unavailable")), patch(
                "sys.stderr", new_callable=io.StringIO):
            with self.assertRaisesRegex(OSError, "networks unavailable"):
                self.prepare(frozenset({"nested-containers", "tic"}))
        self.assertTrue(self.handle.build_unavailable)
        self.assertIsNone(self.handle.build_port)
        self.assertEqual({"network:gateway-link", "network:gateway-egress"}, set(self.handle.registry.identities))

    def test_cleanup_closes_registry_before_background_start_can_create(self):
        self.prepare()
        self.handle.cleanup(0)
        with self.assertRaisesRegex(ValueError, "cleanup has started"):
            self.start()

    def test_tic_selection_and_admission_keep_broker_registry_ownership(self):
        broker = Mock(address="127.0.0.1:34567")
        broker.start_bridge.return_value = Mock(port=45678)
        self.assertEqual(45678, self.handle.select_tic_upstream(broker))
        broker.start_bridge.assert_called_once_with(set())
        self.assertEqual((), self.handle.registry.identities)
        self.handle.addresses = {"gateway-link": "192.0.2.11", "gateway-egress": "192.0.2.12"}
        self.handle.admit_tic_upstream()
        broker.start_bridge.return_value.allow_peers.assert_called_once_with(
            {"192.0.2.11", "192.0.2.12", "127.0.0.1"})
        self.runtime.host_loopback_access = True
        direct = gateway.GatewayHandle(self.runtime, self.resources)
        broker.reset_mock()
        self.assertEqual(34567, direct.select_tic_upstream(broker))
        direct.admit_tic_upstream()
        broker.start_bridge.assert_not_called()

    def test_existing_handle_uses_bound_runtime_despite_another_owner(self):
        other = Mock(host_loopback_access=True)
        gateway.GatewayHandle(other, RelayResourcePlan("other-link", "other-egress", "other"))
        self.prepare(); self.start()
        self.assertEqual([], other.mock_calls)
        self.runtime.network_addresses.assert_called_once_with("gateway", ("gateway-link", "gateway-egress"))
        self.factory.assert_called_once_with(("127.0.0.1", self.build.port))

    def test_tic_readiness_is_publication_not_a_replayed_request(self):
        from gateway import TIC_READY_MESSAGE
        runtime = Mock()
        handle = gateway.GatewayHandle(runtime, self.resources)
        handle.wait_tic_ready()
        runtime.wait_for_log.assert_called_once_with("gateway", TIC_READY_MESSAGE, 7)
        runtime.run.assert_not_called()
        runtime.wait_for_log.side_effect = subprocess.TimeoutExpired("logs", 7)
        with self.assertRaisesRegex(gateway.GatewayError, "publication timed out; no fallback"):
            handle.wait_tic_ready()
        self.runtime.run.return_value = SimpleNamespace(returncode=0, stdout=TIC_READY_MESSAGE + "\n")
        self.handle.wait_tic_ready()
        self.assertEqual(["logs", "--tail", "20", "gateway"], self.runtime.run.call_args.args[0])
        self.runtime.run.return_value = SimpleNamespace(returncode=125, stdout="")
        with self.assertRaisesRegex(gateway.GatewayError, "log is unavailable; no fallback"):
            self.handle.wait_tic_ready()

    def test_recovery_retains_foreign_then_retries_in_dependency_order(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            remaining = ("container:gateway", "network:gateway-link", "network:gateway-egress")
            path = gateway.persist_relay_recovery(self.runtime, home, self.resources, self.handle.owner, remaining)
            def foreign(command, **_kwargs):
                if command[:2] == ["network", "ls"]:
                    return SimpleNamespace(returncode=0, stdout="gateway-link\ngateway-egress\n")
                if command[:3] == ["container", "ls", "--all"]:
                    return SimpleNamespace(returncode=0, stdout="gateway\n")
                return SimpleNamespace(returncode=0, stdout="foreign\n")
            self.runtime.run.side_effect = foreign
            with patch("sys.stderr", new_callable=io.StringIO):
                gateway.recover_relays(self.runtime, home)
            self.assertTrue(path.exists())
            removed = []
            def owned(command, **kwargs):
                if "inspect" in command:
                    return SimpleNamespace(returncode=0, stdout=self.handle.owner + "\n")
                if "rm" in command:
                    removed.append(command[-1])
                    return SimpleNamespace(returncode=0, stdout="")
                return foreign(command, **kwargs)
            self.runtime.run.side_effect = owned
            gateway.recover_relays(self.runtime, home)
            self.assertFalse(path.exists())
            self.assertEqual("gateway", removed[0])
            self.assertCountEqual(["gateway-link", "gateway-egress"], removed[1:])

    def test_malformed_and_symlink_records_are_retained_with_warnings(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            recovery = home / ".local/state/codex-sandbox/gateway-recovery"
            recovery.mkdir(parents=True, mode=0o700)
            malformed = recovery / "malformed.json"
            malformed.write_text(json.dumps({"version": True, "runtime": "x", "owner": "owner", "resources": []}))
            malformed.chmod(0o600)
            target = recovery / "target"; target.write_text("{}")
            symlink = recovery / "symlink.json"; symlink.symlink_to(target)
            with patch("sys.stderr", new_callable=io.StringIO) as stderr:
                gateway.recover_relays(self.runtime, home)
            self.assertTrue(malformed.exists())
            self.assertTrue(symlink.is_symlink())
            self.assertGreaterEqual(stderr.getvalue().count("retained"), 2)

    def test_duplicate_recovery_identity_rejected_before_resource_inspection(self):
        resource = {"kind": "network", "name": "same", "owner": "owner", "dependencies": []}
        payload = {"version": 1, "runtime": gateway.runtime_identity(self.runtime), "owner": "owner",
                   "resources": [resource, resource]}
        with self.assertRaisesRegex(gateway.GatewayError, "duplicate"):
            gateway.parse_relay_recovery(self.runtime, json.dumps(payload).encode())
        self.runtime.run.assert_not_called()

    def test_existing_network_owner_adopted_only_for_same_owner(self):
        for actual, expected in (("owner", "owned"), ("other", "mismatched")):
            self.runtime.run.reset_mock()
            self.runtime.run.return_value = SimpleNamespace(returncode=0, stdout=actual + "\n")
            with self.subTest(owner=actual):
                self.assertEqual(expected, gateway.gateway_network_presence(self.runtime, "network", "owner").value)
            self.runtime.run.assert_called_once()
            self.assertEqual(["network", "inspect"], self.runtime.run.call_args.args[0][:2])

    def test_network_listing_or_inspection_failure_is_not_absence(self):
        failed = SimpleNamespace(returncode=125, stdout="")
        cases = (([failed, failed], "listing failed"),
                 ([failed, SimpleNamespace(returncode=0, stdout="network\n")], "inspection failed"))
        for results, message in cases:
            self.runtime.run.reset_mock(); self.runtime.run.side_effect = results
            with self.subTest(message=message), self.assertRaisesRegex(Exception, message):
                gateway.gateway_network_presence(self.runtime, "network", "owner")
            self.assertEqual([["network", "inspect"], ["network", "ls"]],
                             [c.args[0][:2] for c in self.runtime.run.call_args_list])
        self.runtime.run.side_effect = [failed, SimpleNamespace(returncode=0, stdout="")]
        self.assertEqual("absent", gateway.gateway_network_presence(self.runtime, "network", "owner").value)
        lima = Mock(spec=VMRuntime)
        lima.relay_owner_label.return_value = "dev.codex.relay-owner"
        lima.run.side_effect = OSError("VM unavailable")
        with self.assertRaisesRegex(OSError, "VM unavailable"):
            gateway.gateway_network_presence(lima, "network", "owner")

    def test_recovery_retains_record_when_runtime_listing_is_unavailable(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            path = gateway.persist_relay_recovery(self.runtime, home, self.resources, self.handle.owner,
                                                  ("network:gateway-link",))
            self.runtime.run.return_value = SimpleNamespace(returncode=125, stdout="")
            with patch("sys.stderr", new_callable=io.StringIO):
                gateway.recover_relays(self.runtime, home)
            self.assertTrue(path.exists())


if __name__ == "__main__":
    unittest.main()
