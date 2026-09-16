"""Listener ownership must survive partial gateway creation."""
import os
import io
import json
from pathlib import Path
import runpy
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import gateway

TRANSPORT = runpy.run_path(str(Path(__file__).resolve().parents[3] / "libexec/agent-wrappers/gateway-transport"))


class GatewayTransportTest(unittest.TestCase):
    def test_delayed_listener_succeeds_before_one_deadline(self):
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        address = listener.getsockname()
        listener.close()

        def start_later():
            time.sleep(0.15)
            with socket.socket() as server:
                server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                server.bind(address); server.listen(1)
                connection, _ = server.accept(); connection.close()

        worker = threading.Thread(target=start_later)
        worker.start()
        connection = TRANSPORT["connect_until"](address, time.monotonic() + 1)
        connection.close(); worker.join()

    def test_connected_relay_outlives_connection_attempt_timeout(self):
        with socket.socket() as server:
            server.bind(("127.0.0.1", 0)); server.listen(1)
            local, client = socket.socketpair()
            failures = []

            def delayed_server():
                connection, _ = server.accept()
                with connection:
                    self.assertEqual(b"request", connection.recv(7))
                    # Longer than the connect attempt's remaining timeout.
                    time.sleep(0.3)
                    connection.sendall(b"response")
                    connection.shutdown(socket.SHUT_WR)

            responder = threading.Thread(target=delayed_server)
            responder.start()
            upstream = TRANSPORT["connect_until"](
                server.getsockname(), time.monotonic() + 0.1,
            )
            self.assertIsNone(upstream.gettimeout())

            def run_relay():
                try:
                    TRANSPORT["relay"](local, upstream)
                except BaseException as error:
                    failures.append(error)

            worker = threading.Thread(target=run_relay)
            worker.start()
            client.sendall(b"request"); client.shutdown(socket.SHUT_WR)
            self.assertEqual(b"response", client.recv(8))
            client.close(); worker.join(); responder.join()
            local.close(); upstream.close()
            self.assertEqual([], failures)

    def test_permanent_failure_stops_at_deadline(self):
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0)); address = probe.getsockname()
        started = time.monotonic()
        with self.assertRaises(TimeoutError):
            TRANSPORT["connect_until"](address, started + 0.2)
        self.assertLess(time.monotonic() - started, 0.6)

    def test_interruption_is_not_retried(self):
        with patch.object(TRANSPORT["socket"], "create_connection", side_effect=InterruptedError):
            with self.assertRaises(InterruptedError):
                TRANSPORT["connect_until"](("127.0.0.1", 1), time.monotonic() + 1)

    def test_accept_returns_child_exit_status_without_waiting_for_connection(self):
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0)); listener.listen(1)
            child = subprocess.Popen([sys.executable, "-c", "raise SystemExit(7)"])
            self.assertIsNone(TRANSPORT["accept_before_deadline"](
                listener, child, time.monotonic() + 2,
            ))
            self.assertEqual(7, child.wait())

    def test_accept_uses_invocation_deadline(self):
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0)); listener.listen(1)
            child = Mock(); child.poll.return_value = None
            started = time.monotonic()
            with self.assertRaises(TimeoutError):
                TRANSPORT["accept_before_deadline"](listener, child, started + 0.15)
            self.assertLess(time.monotonic() - started, 0.5)

    def test_accept_interruption_is_terminal(self):
        listener = Mock(); child = Mock(); child.poll.return_value = None
        selector = Mock()
        selector.__enter__ = Mock(return_value=selector)
        selector.__exit__ = Mock(return_value=False)
        selector.select.side_effect = InterruptedError
        with patch.object(TRANSPORT["selectors"], "DefaultSelector", return_value=selector):
            with self.assertRaises(InterruptedError):
                TRANSPORT["accept_before_deadline"](listener, child, time.monotonic() + 1)
        selector.select.assert_called_once()

    def test_native_ssh_configuration_forces_host_key_verification(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory); (home / ".ssh").mkdir()
            command = TRANSPORT["force_verified_native_ssh"](
                home, 4321, ["/usr/local/bin/podman", "info"],
            )
            config = (home / ".ssh/config").read_text(encoding="utf-8")
        self.assertEqual(["/usr/local/bin/podman", "--ssh=native", "info"], command)
        self.assertIn("StrictHostKeyChecking yes", config)
        self.assertIn("UserKnownHostsFile ", config)
        self.assertIn("Port 4321", config)

    def test_relay_send_failure_does_not_call_connection_retry(self):
        left = Mock(); right = Mock()
        left.recv.side_effect = [b"request"]
        right.sendall.side_effect = OSError("ambiguous send")
        fake_selector = Mock()
        fake_selector.select.return_value = [(Mock(fileobj=left, data=right), None)]
        with patch.object(TRANSPORT["selectors"], "DefaultSelector", return_value=fake_selector):
            with self.assertRaisesRegex(OSError, "ambiguous send"):
                TRANSPORT["relay"](left, right)
        right.sendall.assert_called_once_with(b"request")


class GatewayLifecycleTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.launcher = runpy.run_path(str(Path(__file__).resolve().parents[1] / "codex-sandbox"))

    def state(self):
        return SimpleNamespace(
            capabilities=frozenset({"nested-containers"}),
            agent_podman={"AGENT_PODMAN_SSH_USER": "worker", "SOCKET_PATH": "/podman.sock",
                          "CONTAINER_SSHKEY": "/key", "AGENT_PODMAN_SSH_PORT": "2222"},
            gateway_link_network="gateway-link", gateway_egress_network="gateway-egress",
            gateway_container="gateway", sidecar_image="helper@sha256:" + "0" * 64,
            agent_podman_key=Path("/key"),
            agent_podman_known_hosts=Path("/known"), container_known_hosts="/container-known",
            gateway_handle=None, resource_owner="legacy-owner",
        )

    def test_partial_network_startup_is_owned_and_cleaned(self):
        state = self.state(); events = []
        create = Mock(side_effect=[events.append("create-link"), OSError("egress failed")])
        def runtime(command, **_kwargs):
            if command[:2] == ["network", "ls"]:
                return SimpleNamespace(returncode=0, stdout="gateway-link\n")
            if command[:2] == ["network", "inspect"]:
                return SimpleNamespace(returncode=0, stdout=state.gateway_handle.owner + "\n")
            events.append("remove-" + command[-1])
            return SimpleNamespace(returncode=0, stdout="")
        run = Mock(side_effect=runtime)
        prepare = self.launcher["prepare_gateway"]
        with patch.dict(prepare.__globals__, create_relay_network=create), \
                patch.object(prepare.__globals__["OUTER_RUNTIME"], "run", run):
            with self.assertRaisesRegex(OSError, "egress failed"):
                prepare(state)
            self.assertRegex(state.gateway_handle.owner, r"\A[0-9a-f]{32}\Z")
            result = state.gateway_handle.cleanup(19)
        self.assertEqual(19, result.primary_status)
        self.assertFalse(result.remaining)
        self.assertTrue(any(call.args[0][:2] == ["network", "rm"]
                            for call in run.call_args_list))

    def test_editor_only_ignores_available_podman_credentials(self):
        state = self.state()
        state.capabilities = frozenset({"host-editor"})
        commands = []

        def run(command, **_kwargs):
            commands.append(command)
            if command[1:2] == ["inspect"]:
                return SimpleNamespace(returncode=0, stdout="10.0.0.2\n")
            return SimpleNamespace(returncode=0, stdout="")

        prepare = self.launcher["prepare_gateway"]
        start = self.launcher["start_gateway"]
        bridge = Mock(port=1234)
        with patch.dict(start.__globals__, run=run, create_relay_network=Mock(),
                        HostEditorBridge=Mock(return_value=bridge)):
            prepare(state)
            start(state)
        gateway_run = commands[0]
        self.assertIn("--editor-port", gateway_run)
        self.assertNotIn("--podman-port", gateway_run)

    def test_agent_room_uses_fixed_gateway_port_and_loopback_target(self):
        state = self.state()
        state.capabilities = frozenset({"agent-room"})
        commands = []

        def run(command, **_kwargs):
            commands.append(command)
            if command[1:2] == ["inspect"]:
                return SimpleNamespace(returncode=0, stdout="10.0.0.2\n")
            return SimpleNamespace(returncode=0, stdout="")

        bridge = Mock(port=3456)
        bridge_factory = Mock(return_value=bridge)
        prepare = self.launcher["prepare_gateway"]
        start = self.launcher["start_gateway"]
        with patch.dict(start.__globals__, run=run, create_relay_network=Mock(),
                        FixedTcpBridge=bridge_factory):
            prepare(state)
            start(state)
        bridge_factory.assert_called_once_with(("127.0.0.1", 3000))
        gateway_run = commands[0]
        self.assertEqual("3456", gateway_run[gateway_run.index("--agent-room-port") + 1])
        bridge.allow_peers.assert_called_once_with({"10.0.0.2", "127.0.0.1"})

    def test_cleanup_closes_registry_before_background_start_can_create(self):
        state = self.state()
        prepare = self.launcher["prepare_gateway"]
        with patch.dict(prepare.__globals__, create_relay_network=Mock()):
            prepare(state)
        state.gateway_handle.cleanup(0)
        with self.assertRaisesRegex(ValueError, "cleanup has started"):
            self.launcher["start_gateway"](state)

    def test_recovery_retains_foreign_resources_then_retries_in_dependency_order(self):
        with tempfile.TemporaryDirectory() as directory:
            state = self.state(); state.home = Path(directory)
            handle = self.launcher["GatewayHandle"](state, False, True)
            state.gateway_handle = handle
            remaining = ("container:gateway", "network:gateway-link", "network:gateway-egress")
            path = self.launcher["persist_relay_recovery"](
                state, handle.resources, handle.owner, remaining,
            )
            self.assertIsNotNone(path)
            recover = self.launcher["recover_relays"]

            def foreign(command, **_kwargs):
                if command[:2] == ["network", "ls"]:
                    return SimpleNamespace(returncode=0, stdout="gateway-link\ngateway-egress\n")
                if command[:2] == ["network", "inspect"]:
                    return SimpleNamespace(returncode=0, stdout="foreign\n")
                if command[:3] == ["container", "ls", "--all"]:
                    return SimpleNamespace(returncode=0, stdout="gateway\n")
                return SimpleNamespace(returncode=0, stdout="foreign\n")

            with patch.object(recover.__globals__["OUTER_RUNTIME"], "run", side_effect=foreign), \
                    patch("sys.stderr", new_callable=io.StringIO):
                recover(state)
            self.assertTrue(path.exists(), "foreign resources must retain recovery authority")

            removed = []
            def owned(command, **_kwargs):
                if command[:2] == ["network", "ls"]:
                    return SimpleNamespace(returncode=0, stdout="gateway-link\ngateway-egress\n")
                if command[:2] == ["network", "inspect"]:
                    return SimpleNamespace(returncode=0, stdout=handle.owner + "\n")
                if command[:3] == ["container", "ls", "--all"]:
                    return SimpleNamespace(returncode=0, stdout="gateway\n")
                if command[:2] == ["container", "inspect"]:
                    return SimpleNamespace(returncode=0, stdout=handle.owner + "\n")
                if "rm" in command:
                    removed.append(command[-1])
                return SimpleNamespace(returncode=0, stdout="")
            with patch.object(recover.__globals__["OUTER_RUNTIME"], "run", side_effect=owned):
                recover(state)
            self.assertFalse(path.exists())
            self.assertEqual("gateway", removed[0])
            self.assertCountEqual(["gateway-link", "gateway-egress"], removed[1:])

    def test_insecure_recovery_directory_warning_does_not_replace_primary_status(self):
        with tempfile.TemporaryDirectory() as directory:
            state = self.state(); state.home = Path(directory)
            state.cleaned = False; state.codex_container_created = False
            state.skills_tmp = None; state.pi_agent_tmp = None
            state.proxy_lock = None; state.proxy_state = None; state.proxy_args = None
            state.manifest = None; state.pi_auth_mask = None; state.prepared_images = None
            state.tmux_registration = None
            handle = self.launcher["GatewayHandle"](state, False, True)
            state.gateway_handle = handle
            resource_type = self.launcher["OwnedResource"]
            presence = self.launcher["ResourcePresence"]
            handle.registry.register(resource_type(
                "network:gateway-link", handle.owner,
                lambda: presence.MISMATCHED, lambda: None))
            recovery = state.home / ".local/state/codex-sandbox/gateway-recovery"
            recovery.mkdir(parents=True, mode=0o755)
            cleanup = self.launcher["cleanup"]
            with patch("sys.stderr", new_callable=io.StringIO) as output:
                cleanup(state)
            self.assertIn("could not be persisted", output.getvalue())
            self.assertTrue(state.cleaned)

    def test_malformed_and_symlink_recovery_records_are_retained_with_warnings(self):
        with tempfile.TemporaryDirectory() as directory:
            state = self.state(); state.home = Path(directory)
            recovery = state.home / ".local/state/codex-sandbox/gateway-recovery"
            recovery.mkdir(parents=True, mode=0o700)
            malformed = recovery / "malformed.json"
            malformed.write_text(json.dumps({"version": True, "runtime": "x", "owner": "owner",
                "resources": []}), encoding="utf-8")
            malformed.chmod(0o600)
            target = recovery / "target"; target.write_text("{}", encoding="utf-8")
            symlink = recovery / "symlink.json"; symlink.symlink_to(target)
            recover = self.launcher["recover_relays"]
            with patch("sys.stderr", new_callable=io.StringIO) as output:
                recover(state)
            self.assertTrue(malformed.exists())
            self.assertTrue(symlink.is_symlink())
            self.assertGreaterEqual(output.getvalue().count("retained"), 2)

    def test_duplicate_recovery_identity_is_rejected_before_resource_inspection(self):
        parse = self.launcher["_parse_relay_recovery"]
        resource = {"kind": "network", "name": "same", "owner": "owner",
                    "dependencies": []}
        payload = {"version": 1, "runtime": parse.__globals__["runtime_identity"](
            parse.__globals__["OUTER_RUNTIME"]), "owner": "owner",
            "resources": [resource, resource]}
        with self.assertRaisesRegex(Exception, "duplicate"):
            parse(json.dumps(payload).encode())

    def test_existing_network_owner_is_adopted_only_for_same_owner(self):
        presence = self.launcher["_gateway_network_presence"]
        for actual, expected in (("owner", "owned"), ("other", "mismatched")):
            run = Mock(side_effect=[
                SimpleNamespace(returncode=0, stdout="network\n"),
                SimpleNamespace(returncode=0, stdout=actual + "\n"),
            ])
            with patch.object(presence.__globals__["OUTER_RUNTIME"], "run", run):
                self.assertEqual(expected, presence("network", "owner").value)

    def test_network_listing_or_inspection_failure_is_not_absence(self):
        presence = self.launcher["_gateway_network_presence"]
        failed = SimpleNamespace(returncode=125, stdout="")
        with patch.object(presence.__globals__["OUTER_RUNTIME"], "run", return_value=failed):
            with self.assertRaisesRegex(Exception, "listing failed"):
                presence("network", "owner")
        run = Mock(side_effect=[SimpleNamespace(returncode=0, stdout="network\n"), failed])
        with patch.object(presence.__globals__["OUTER_RUNTIME"], "run", run):
            with self.assertRaisesRegex(Exception, "inspection failed"):
                presence("network", "owner")
        lima = Mock(spec=presence.__globals__["VMRuntime"])
        lima.run.side_effect = OSError("VM unavailable")
        with patch.dict(presence.__globals__, OUTER_RUNTIME=lima):
            with self.assertRaisesRegex(OSError, "VM unavailable"):
                presence("network", "owner")

    def test_recovery_retains_record_when_runtime_listing_is_unavailable(self):
        with tempfile.TemporaryDirectory() as directory:
            state = self.state(); state.home = Path(directory)
            handle = self.launcher["GatewayHandle"](state, False, True)
            state.gateway_handle = handle
            path = self.launcher["persist_relay_recovery"](
                state, handle.resources, handle.owner, ("network:gateway-link",),
            )
            unavailable = Mock(return_value=SimpleNamespace(returncode=125, stdout=""))
            with patch.object(
                    self.launcher["recover_relays"].__globals__["OUTER_RUNTIME"],
                    "run", unavailable,
            ), patch("sys.stderr", new_callable=io.StringIO):
                self.launcher["recover_relays"](state)
            self.assertTrue(path.exists())


class GatewayTest(unittest.TestCase):
    def test_second_listener_spawn_failure_reaps_the_first(self):
        popen = subprocess.Popen
        children = []

        def spawn(_command, **kwargs):
            if children:
                raise OSError('second listener failed')
            child = popen(['sleep', '300'], **kwargs)
            children.append(child)
            return child

        with patch.object(gateway.subprocess, 'Popen', side_effect=spawn):
            with self.assertRaisesRegex(OSError, 'second listener failed'):
                gateway.serve('host.lima.internal', 1234, 5678)
        self.assertIsNotNone(children[0].poll())
        with self.assertRaises(ProcessLookupError):
            os.killpg(children[0].pid, 0)

    def test_nested_listener_does_not_require_editor(self):
        child = Mock(pid=12, returncode=None)
        with patch.object(gateway.subprocess, 'Popen', return_value=child) as spawn, \
                patch.object(gateway.os, 'wait', return_value=(12, 0)), \
                patch.object(gateway.os, 'killpg'):
            self.assertEqual(1, gateway.serve('host.lima.internal', podman_port=22))
        self.assertIn('TCP4-LISTEN:2222,fork,reuseaddr', spawn.call_args.args[0])

    def test_agent_room_listener_has_fixed_local_port(self):
        child = Mock(pid=12, returncode=None)
        with patch.object(gateway.subprocess, 'Popen', return_value=child) as spawn, \
                patch.object(gateway.os, 'wait', return_value=(12, 0)), \
                patch.object(gateway.os, 'killpg'):
            self.assertEqual(1, gateway.serve('host.lima.internal', agent_room_port=3456))
        self.assertIn('TCP4-LISTEN:2225,fork,reuseaddr', spawn.call_args.args[0])
        self.assertEqual('TCP4:host.lima.internal:3456', spawn.call_args.args[0][-1])

    def test_empty_gateway_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'at least one listener'):
            gateway.serve('host.lima.internal')


if __name__ == '__main__':
    unittest.main()
