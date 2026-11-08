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



class GatewayLauncherCleanupTest(unittest.TestCase):
    def setUp(self):
        self.launcher = runpy.run_path(str(Path(__file__).resolve().parents[1] / "codex-sandbox"))

    def state(self):
        return SimpleNamespace(gateway_handle=None, suffix="test")

    def test_stopped_build_is_unpublished_even_when_later_network_creation_fails(self):
        import host_gateway
        state = SimpleNamespace(
            capabilities=frozenset({'nested-containers', 'tic'}), gateway_handle=None,
            gateway_link_network='link', gateway_egress_network='egress', gateway_container='gateway',
            agent_docker={'AGENT_DOCKER_SSH_USER': 'worker', 'AGENT_DOCKER_SSH_PORT': '12345',
                          'AGENT_DOCKER_SSHKEY': '/guest-key'},
            agent_docker_key=Path('/key'), agent_docker_known_hosts=Path('/known'),
            container_known_hosts='/guest-known',
        )
        runtime = Mock(host_loopback_access=True)
        with patch.dict(self.launcher['prepare_gateway'].__globals__, OUTER_RUNTIME=runtime), patch(
                'socket.create_connection', side_effect=ConnectionRefusedError('stopped')), patch.object(
                host_gateway, 'create_relay_networks', side_effect=OSError('network failed')), patch(
                'sys.stderr', new_callable=io.StringIO):
            with self.assertRaisesRegex(OSError, 'network failed'):
                self.launcher['prepare_gateway'](state)
        self.assertIsNone(state.agent_docker)
        self.assertIsNotNone(state.gateway_handle)
        self.assertTrue(state.gateway_handle.build_unavailable)
        self.assertEqual({'network:link', 'network:egress'}, set(state.gateway_handle.registry.identities))

    def test_insecure_recovery_directory_warning_does_not_replace_primary_status(self):
        with tempfile.TemporaryDirectory() as directory:
            state = self.state(); state.home = Path(directory)
            state.cleaned = False; state.codex_container_created = False
            state.skills_tmp = None; state.pi_agent_tmp = None
            state.command_session = None
            
            state.tmux_registration = None
            handle = self.launcher["GatewayHandle"](
                self.launcher["OUTER_RUNTIME"],
                self.launcher["RelayResourcePlan"]("gateway-link", "gateway-egress", "gateway"))
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


class GatewayTest(unittest.TestCase):
    def test_real_build_only_and_shared_gateway_keep_stream_targets_distinct(self):
        from gateway_fixture import LocalGateway
        for tic in (False, True):
            with self.subTest(tic=tic), socket.socket() as build, socket.socket() as ticket:
                for listener in (build, ticket):
                    listener.bind(('127.0.0.1', 0))
                    listener.listen()
                    listener.settimeout(5)
                relay = LocalGateway(ticket.getsockname()[1] if tic else None, build.getsockname()[1])
                workers, errors = [], []
                def respond(listener, marker):
                    try:
                        while True:
                            connection, _ = listener.accept()
                            with connection:
                                data = bytearray()
                                while chunk := connection.recv(65536):
                                    data.extend(chunk)
                                if not data:  # Gateway listener readiness probes.
                                    continue
                                connection.sendall(marker + bytes(data))
                                return
                    except BaseException as error:
                        errors.append(error)
                try:
                    cases = [(build, 2222, b'build:')]
                    if tic:
                        cases.append((ticket, gateway.TIC_PORT, b'tic:'))
                    for listener, port, marker in cases:
                        worker = threading.Thread(target=respond, args=(listener, marker))
                        workers.append(worker)
                        worker.start()
                        with socket.create_connection(('127.0.0.1', port), timeout=3) as client:
                            client.sendall(b'owned request')
                            client.shutdown(socket.SHUT_WR)
                            data = bytearray()
                            while chunk := client.recv(65536):
                                data.extend(chunk)
                            self.assertEqual(marker + b'owned request', data)
                finally:
                    relay.stop()
                    for worker in workers:
                        worker.join(timeout=6)
                        self.assertFalse(worker.is_alive())
                if errors:
                    raise errors[0]
                for port in ([2222, gateway.TIC_PORT] if tic else [2222]):
                    with self.assertRaises(OSError):
                        socket.create_connection(('127.0.0.1', port), timeout=.2)

    def test_nested_listener_runs_without_other_capabilities(self):
        child = Mock(pid=12, returncode=None)
        with patch.object(gateway.subprocess, 'Popen', return_value=child) as spawn, \
                patch.object(gateway.os, 'wait', return_value=(12, 0)), \
                patch.object(gateway.os, 'killpg'):
            self.assertEqual(1, gateway.serve('host.lima.internal', build_port=22))
        self.assertIn('TCP4-LISTEN:2222,fork,reuseaddr', spawn.call_args.args[0])

    def test_empty_gateway_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'at least one listener'):
            gateway.serve('host.lima.internal')

    def test_tic_listener_shares_gateway_and_publishes_readiness(self):
        child = Mock(pid=12, returncode=None)
        with patch.object(gateway.subprocess, 'Popen', return_value=child) as spawn, \
                patch.object(gateway, 'wait_listener') as ready, \
                patch.object(gateway.os, 'wait', return_value=(12, 0)), \
                patch.object(gateway.os, 'killpg'), \
                patch('sys.stdout', new_callable=io.StringIO) as stdout:
            self.assertEqual(1, gateway.serve('host.lima.internal', build_port=22, tic_port=4321))
        commands = [call.args[0] for call in spawn.call_args_list]
        self.assertTrue(any('TCP4-LISTEN:2222,fork,reuseaddr' in command for command in commands))
        self.assertTrue(any('TCP4-LISTEN:2225,fork,reuseaddr' in command for command in commands))
        ready.assert_called_once_with(2225, [child, child])
        self.assertEqual(f'{gateway.TIC_READY_MESSAGE}\n', stdout.getvalue())


if __name__ == '__main__':
    unittest.main()
