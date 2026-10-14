"""Listener ownership must survive partial gateway creation."""
import os
import io
import json
from pathlib import Path
import runpy
import signal
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

TRANSPORT = runpy.run_path(str(Path(__file__).resolve().parents[3] / "libexec/sandbox-wrappers/gateway-transport"))


class GatewayTransportTest(unittest.TestCase):
    def test_absent_build_service_never_executes_a_local_client(self):
        with patch.dict(os.environ, {"DOCKER_HOST": ""}), patch("sys.stderr", new_callable=io.StringIO):
            self.assertEqual(125, TRANSPORT["main"](["/nonexistent/docker", "info"]))

    def run_transport(self, client, environment, *, master_failure=False, master_hangs=False,
                      cancel_during_master_start=False):
        popen = subprocess.Popen
        children = []

        def spawn(command, **kwargs):
            if command[0] == '/usr/bin/ssh':
                if master_failure or master_hangs:
                    code = 'import time; time.sleep(300)' if master_hangs else 'raise SystemExit(255)'
                    command = [sys.executable, '-c', code]
                else:
                    command = [sys.executable,
                               str(Path(__file__).with_name('fixtures') / 'gateway-master.py'),
                               *command[1:]]
            child = popen(command, **kwargs)
            children.append(child)
            if cancel_during_master_start and len(children) == 1:
                os.kill(os.getpid(), signal.SIGTERM)
            return child

        try:
            with patch.dict(os.environ, environment), patch('subprocess.Popen', side_effect=spawn):
                return TRANSPORT['main']([str(client)])
        finally:
            for child in children:
                self.assertIsNotNone(child.poll(), 'transport must reap each owned process')
                with self.assertRaises(ProcessLookupError):
                    os.killpg(child.pid, 0)

    def test_docker_can_open_multiple_verified_ssh_connections(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            client = home / "docker"
            client.write_text(
                f"#!{sys.executable}\n"
                "import os, subprocess\n"
                "for _ in range(2):\n"
                "    value = subprocess.check_output(['ssh', '-G', 'agentbuilder@relay'], text=True)\n"
                "    assert 'hostkeyalias agent-docker' in value\n"
                "    assert 'stricthostkeychecking true' in value\n"
                "    assert 'proxycommand ' in value and '--connect %h %p' in value\n"
                "assert os.environ['HOME'] == os.environ['EXPECTED_HOME']\n"
                "assert 'DOCKER_CONTEXT' not in os.environ\n"
            )
            client.chmod(0o700)
            environment = {"DOCKER_HOST": "ssh://agentbuilder@relay:2222",
                           "AGENT_DOCKER_SSHKEY": str(home / "key"),
                           "AGENT_DOCKER_KNOWN_HOSTS": str(home / "known"),
                           "EXPECTED_HOME": os.environ["HOME"], "DOCKER_CONTEXT": "infrastructure",
                           "MASTER_RECORD": str(home / 'master.json')}
            self.assertEqual(0, self.run_transport(client, environment))
            record = json.loads((home / 'master.json').read_text())
            self.assertEqual('agentbuilder', record['settings']['user'])
            self.assertEqual('2222', record['settings']['port'])
            self.assertEqual('agent-docker', record['settings']['hostkeyalias'])
            self.assertFalse(Path(record['settings']['controlpath']).exists())

    def test_failed_master_does_not_start_the_client(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            marker = home / 'client-started'
            client = home / 'client'
            client.write_text(f'#!{sys.executable}\nfrom pathlib import Path\nPath({str(marker)!r}).touch()\n')
            client.chmod(0o700)
            environment = {'DOCKER_HOST': 'ssh://agentbuilder@relay:2222',
                           'AGENT_DOCKER_SSHKEY': str(home / 'key'),
                           'AGENT_DOCKER_KNOWN_HOSTS': str(home / 'known')}
            self.assertEqual(255, self.run_transport(client, environment, master_failure=True))
            self.assertFalse(marker.exists())

    def test_failed_client_reaps_the_master_and_preserves_status(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            client = home / 'client'
            client.write_text(f'#!{sys.executable}\nraise SystemExit(23)\n')
            client.chmod(0o700)
            environment = {'DOCKER_HOST': 'ssh://%61gentbuilder@another-relay:3333',
                           'AGENT_DOCKER_SSHKEY': str(home / 'another-key'),
                           'AGENT_DOCKER_KNOWN_HOSTS': str(home / 'another-known'),
                           'MASTER_RECORD': str(home / 'master.json')}
            self.assertEqual(23, self.run_transport(client, environment))
            record = json.loads((home / 'master.json').read_text())
            self.assertEqual('agentbuilder', record['settings']['user'])
            self.assertEqual('another-relay', record['settings']['hostname'])
            self.assertEqual('3333', record['settings']['port'])
            self.assertEqual(str(home / 'another-key'), record['settings']['identityfile'])
            self.assertFalse(Path(record['settings']['controlpath']).exists())

    def test_master_readiness_timeout_reaps_the_process_without_starting_client(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            environment = {'DOCKER_HOST': 'ssh://agentbuilder@relay:2222',
                           'AGENT_DOCKER_SSHKEY': str(home / 'key'),
                           'AGENT_DOCKER_KNOWN_HOSTS': str(home / 'known')}
            with patch.dict(TRANSPORT['main'].__globals__, DEADLINE_SECONDS=0.1), \
                    patch('sys.stderr', new_callable=io.StringIO) as output:
                self.assertEqual(255, self.run_transport(home / 'never-started', environment, master_hangs=True))
            self.assertIn('deadline', output.getvalue())

    def test_cancellation_forwards_the_signal_and_reaps_both_process_groups(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            marker = home / 'signal'
            client = home / 'client'
            client.write_text(
                f'#!{sys.executable}\n'
                'import os, signal, time\n'
                'from pathlib import Path\n'
                'def terminate(signum, _frame):\n'
                f'    Path({str(marker)!r}).write_text(str(signum))\n'
                '    raise SystemExit(0)\n'
                'signal.signal(signal.SIGINT, terminate)\n'
                'os.kill(os.getppid(), signal.SIGINT)\n'
                'time.sleep(300)\n'
            )
            client.chmod(0o700)
            environment = {'DOCKER_HOST': 'ssh://agentbuilder@relay:2222',
                           'AGENT_DOCKER_SSHKEY': str(home / 'key'),
                           'AGENT_DOCKER_KNOWN_HOSTS': str(home / 'known'),
                           'MASTER_RECORD': str(home / 'master.json')}
            self.assertEqual(128 + signal.SIGINT, self.run_transport(client, environment))
            self.assertEqual(str(signal.SIGINT), marker.read_text())
            record = json.loads((home / 'master.json').read_text())
            self.assertFalse(Path(record['settings']['controlpath']).exists())

    def test_cancellation_during_spawn_keeps_ownership_of_the_new_master(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            environment = {'DOCKER_HOST': 'ssh://agentbuilder@relay:2222',
                           'AGENT_DOCKER_SSHKEY': str(home / 'key'),
                           'AGENT_DOCKER_KNOWN_HOSTS': str(home / 'known'),
                           'MASTER_RECORD': str(home / 'master.json')}
            self.assertEqual(128 + signal.SIGTERM, self.run_transport(
                home / 'never-started', environment, cancel_during_master_start=True))

    def test_proxy_command_preserves_half_close_and_response(self):
        with socket.socket() as server:
            server.bind(("127.0.0.1", 0)); server.listen(1)
            def respond():
                connection, _ = server.accept()
                with connection:
                    request = bytearray()
                    while data := connection.recv(65536):
                        request.extend(data)
                    connection.sendall(bytes(request) + b"reply")
            worker = threading.Thread(target=respond)
            worker.start()
            result = subprocess.run([sys.executable,
                str(Path(__file__).resolve().parents[3] / "libexec/sandbox-wrappers/gateway-transport"),
                "--connect", "127.0.0.1", str(server.getsockname()[1])],
                input=b"request", capture_output=True, timeout=5)
            worker.join(timeout=5)
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual(b"requestreply", result.stdout)

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



class GatewayLifecycleTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.launcher = runpy.run_path(str(Path(__file__).resolve().parents[1] / "codex-sandbox"))

    def setUp(self):
        patcher = patch.dict(self.launcher["prepare_gateway"].__globals__,
                            FixedTcpBridge=Mock(return_value=Mock(port=4321)))
        patcher.start()
        self.addCleanup(patcher.stop)

    def state(self):
        return SimpleNamespace(
            capabilities=frozenset({"nested-containers"}),
            agent_docker={"AGENT_DOCKER_SSH_USER": "worker",
                          "AGENT_DOCKER_SSHKEY": "/key", "AGENT_DOCKER_SSH_PORT": "2222"},
            gateway_link_network="gateway-link", gateway_egress_network="gateway-egress",
            gateway_container="gateway", sidecar_image="helper@sha256:" + "0" * 64,
            agent_docker_key=Path("/key"),
            agent_docker_known_hosts=Path("/known"), container_known_hosts="/container-known",
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

    def test_unavailable_agent_room_is_a_warning_when_it_is_the_only_capability(self):
        state = self.state()
        state.capabilities = frozenset({"agent-room"})
        prepare = self.launcher["prepare_gateway"]
        bridge = Mock()
        bridge.start.side_effect = ConnectionRefusedError(111, "refused")
        with patch.dict(prepare.__globals__,
                        FixedTcpBridge=Mock(return_value=bridge),
                        create_relay_network=Mock()), \
                patch("sys.stderr", new_callable=io.StringIO) as stderr:
            self.assertEqual([], prepare(state))
        self.assertIsNone(state.gateway_handle)
        self.assertIn("warning: agent-room relay unavailable: [Errno 111] refused", stderr.getvalue())

    def test_stopped_build_service_warns_and_creates_no_gateway(self):
        state = self.state()
        prepare = self.launcher["prepare_gateway"]
        bridge = Mock()
        bridge.start.side_effect = ConnectionRefusedError(111, "refused")
        create = Mock()
        with patch.dict(prepare.__globals__, FixedTcpBridge=Mock(return_value=bridge),
                        create_relay_network=create), \
                patch("sys.stderr", new_callable=io.StringIO) as stderr:
            self.assertEqual([], prepare(state))
        self.assertIsNone(state.gateway_handle)
        self.assertIsNone(state.agent_docker)
        create.assert_not_called()
        self.assertIn("tools/agent-docker/vm.py start", stderr.getvalue())

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
            handle = self.launcher["GatewayHandle"](state, nested=True)
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
            state.manifest = None; state.prepared_images = None
            state.tmux_registration = None
            handle = self.launcher["GatewayHandle"](state, nested=True)
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
            handle = self.launcher["GatewayHandle"](state, nested=True)
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
                gateway.serve('host.lima.internal', build_port=1234, agent_room_port=5678)
        self.assertIsNotNone(children[0].poll())
        with self.assertRaises(ProcessLookupError):
            os.killpg(children[0].pid, 0)

    def test_nested_listener_runs_without_other_capabilities(self):
        child = Mock(pid=12, returncode=None)
        with patch.object(gateway.subprocess, 'Popen', return_value=child) as spawn, \
                patch.object(gateway.os, 'wait', return_value=(12, 0)), \
                patch.object(gateway.os, 'killpg'):
            self.assertEqual(1, gateway.serve('host.lima.internal', build_port=22))
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
