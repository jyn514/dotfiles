import hashlib
import json
import os
from pathlib import Path
import socket
import struct
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tic_broker import InstalledTicBuild, TicBrokerLaunch
from docker_runtime import Docker
NATIVE_REVISION = (Path(__file__).resolve().parents[2] / "tic-proxy/native-revision").read_text().strip()
from trusted_services import (LifecycleError, LifecycleState, OwnedResource, OwnerSet,
                              ResourcePresence, ResourceRegistry)


class TicBrokerTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.workspace = self.root / "workspace"
        self.common = self.workspace / ".git"
        self.common.mkdir(parents=True)
        self.manifest = self.root / "process-fixture.json"
        self.native = self.root / "ti"
        self.native.write_text("#!/bin/sh\necho native-must-not-run > \"$0.executed\"\nexit 99\n")
        self.native.chmod(0o700)
        self.broker = self.root / "tic-broker"
        self.make_build()

    def make_build(self, mode="ready"):
        fixture_dir = str(Path(__file__).resolve().parent)
        self.broker.write_text(f"#!{sys.executable}\nimport sys\nsys.path.insert(0, {fixture_dir!r})\n"
                               f"from tic_broker_fixture import main\nmain({mode!r})\n")
        self.broker.chmod(0o700)
        digest = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
        self.binding = dict(version=1, native_revision=NATIVE_REVISION, policy_version=1,
                            broker_executable=str(self.broker), broker_sha256=digest(self.broker),
                            native_executable=str(self.native), native_sha256=digest(self.native),
                            guest_client_executable=str(self.native), guest_client_sha256=digest(self.native),
                            guest_client_platform="linux/amd64")
        self.manifest.write_text(json.dumps(self.binding))
        return self.fixture_build()

    def fixture_build(self):
        value = json.loads(self.manifest.read_text())
        build = InstalledTicBuild(Path(value['broker_executable']), value['broker_sha256'],
                                  Path(value['native_executable']), value['native_sha256'],
                                  Path(value['guest_client_executable']), value['guest_client_sha256'],
                                  value['guest_client_platform'], value['native_revision'])
        build.verify()
        return build

    def launch(self, build=None, **kwargs):
        authority = dict(workspace=self.workspace, common_dir=self.common,
                         user_name="Fixture Author", user_email="fixture@example.invalid", namespace="fixture")
        authority.update(kwargs)
        launch = TicBrokerLaunch(build or self.fixture_build(), **authority)
        self.addCleanup(launch.stop)
        return launch

    def exchange(self, address, token):
        host, port = address.rsplit(":", 1)
        with socket.create_connection((host, int(port)), timeout=2) as connection:
            request = json.dumps({"token": token, "request": {
                "version": 2, "command": "tic", "argv": ["list"], "stdin": ""}}).encode()
            connection.sendall(struct.pack("!I", len(request)) + request)
            # Wire 2 uses the length, not request EOF. Keep the client alive
            # until the response; FIN intentionally cancels an active request.
            data = bytearray()
            while chunk := connection.recv(65536):
                data.extend(chunk)
        self.assertEqual(len(data) - 4, struct.unpack("!I", data[:4])[0])
        return json.loads(data[4:])

    def test_default_owner_is_accepted_by_docker_relay_validator_without_starting_services(self):
        launch = self.launch()
        runtime = Docker.__new__(Docker)
        runtime.record = {}
        runtime.run = mock.Mock()
        with mock.patch("tic_broker.subprocess.Popen") as spawn:
            runtime.create_relay_network("tic-owner-contract", internal=True, owner=launch.owner)
        spawn.assert_not_called()
        runtime.run.assert_called_once()
        self.assertIn("dev.codex.relay-owner=" + launch.owner, runtime.run.call_args.args[0])
        self.assertIsNone(launch.process)
        self.assertIsNone(launch.directory)

    def test_required_readiness_and_fixed_bridge_preserve_framed_response_without_request_eof(self):
        launch = self.launch().start()
        self.assertEqual('best-effort', launch.plan.availability.value)
        self.assertEqual(LifecycleState.READY, launch.lifecycle.state)
        config = json.loads((launch.directory / "config.json").read_text())
        evidence = json.loads((launch.directory / "evidence.json").read_text())
        self.assertEqual(0o600, evidence["mode"])
        self.assertNotIn("SANDBOX_TIC_TOKEN", evidence["environment"])
        self.assertEqual(str(self.workspace), config["workspace"])
        self.assertEqual(str(self.common), config["common_dir"])
        self.assertEqual("Fixture Author", config["user_name"])
        self.assertEqual("fixture", config["namespace"])
        bridge = launch.start_bridge({"127.0.0.1"})
        environment = launch.environment(f"127.0.0.1:{bridge.port}")
        launch.attach()
        result = self.exchange(environment["SANDBOX_TIC_ENDPOINT"], environment["SANDBOX_TIC_TOKEN"])
        self.assertEqual("fixture response", result["stdout"])
        self.assertFalse(Path(str(self.native) + ".executed").exists())
        directory = launch.directory
        process = launch.process
        cleanup = launch.stop(19)
        self.assertEqual(19, cleanup.primary_status)
        self.assertFalse(cleanup.remaining)
        self.assertIsNotNone(process.poll())
        self.assertFalse(directory.exists())
        self.assertEqual(LifecycleState.REMOVED, launch.lifecycle.state)

    def test_empty_and_whitespace_identity_literals_are_preserved_in_private_config(self):
        for literal in ("", " ", " \t\n "):
            with self.subTest(literal=repr(literal)):
                launch = self.launch(user_name=literal, user_email=literal, namespace=literal).start()
                config = json.loads((launch.directory / "config.json").read_bytes())
                for field in ("user_name", "user_email", "namespace"):
                    self.assertEqual(literal, config[field])
                    self.assertEqual(literal, launch.plan.fixed_parameters[field])
                self.assertFalse(launch.stop().remaining)

    def test_identity_validation_rejects_non_strings_nul_and_unrepresentable_values_only(self):
        for field in ("user_name", "user_email", "namespace"):
            for value in (None, 0, True, "embedded\0nul", "unpaired-\ud800"):
                with self.subTest(field=field, value=repr(value)):
                    with self.assertRaises(LifecycleError):
                        self.launch(**{field: value})

    def test_actual_encoded_config_limit_rejects_before_resources_or_broker_spawn(self):
        # JSON escaping, fixed authority and the fresh token all count toward
        # the existing broker config limit, not just the identity's text length.
        launch = self.launch(user_name="\n" * 32768)
        with mock.patch("tic_broker.subprocess.Popen") as spawn:
            with self.assertRaisesRegex(LifecycleError, "configuration exceeds 64 KiB"):
                launch.start()
        spawn.assert_not_called()
        self.assertIsNone(launch.directory)
        self.assertIsNone(launch.lifetime_writer)
        self.assertEqual("", launch.token)
        self.assertFalse(launch.registry.identities)

    def test_independent_launches_share_only_accepted_store_authority(self):
        one = self.launch().start()
        two = self.launch().start()
        self.assertNotEqual(one.address, two.address)
        self.assertNotEqual(one.token, two.token)
        self.assertNotEqual(one.process.pid, two.process.pid)
        one.stop()
        self.assertEqual(0, self.exchange(two.address, two.token)["exit"])

    def test_lifetime_writer_is_not_inherited_by_unrelated_child(self):
        launch = self.launch().start()
        process = launch.process
        self.assertFalse(os.get_inheritable(launch.lifetime_writer))
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(10)"], close_fds=False)
        def reap_child():
            if child.poll() is None:
                child.kill()
            child.wait(timeout=3)
        self.addCleanup(reap_child)
        launch.close_lifetime()
        self.assertEqual(0, process.wait(timeout=2))
        with self.assertRaises(LifecycleError):
            launch.environment()
        child.terminate()
        child.wait(timeout=2)

    def test_external_registry_keeps_broker_until_final_owner_cleanup(self):
        registry = ResourceRegistry("fixture-owner")
        launch = self.launch(registry=registry, owners=OwnerSet()).start()
        launch.attach()
        # Ending a disposable execution attachment does not manipulate owner.
        subprocess.run([sys.executable, "-c", "pass"], check=True)
        self.assertEqual(0, self.exchange(launch.address, launch.token)["exit"])
        directory, process = launch.directory, launch.process
        result = registry.cleanup(31)
        self.assertEqual(31, result.primary_status)
        self.assertFalse(result.remaining)
        self.assertFalse(directory.exists())
        self.assertIsNotNone(process.poll())

    def failing_provider_dependent(self, launch):
        launch.start_bridge({"127.0.0.1"})
        present = {"value": True, "fail": True}
        self.addCleanup(lambda: present.update(fail=False))
        launch.registry.RETRY_DELAYS = ()

        def remove():
            # Provider cleanup must start only after execution authority has
            # ended, regardless of whether provider deletion then succeeds.
            self.assertIsNone(launch.process)
            self.assertIsNone(launch.lifetime_writer)
            self.assertEqual("", launch.token)
            self.assertIsNone(launch.address)
            if present["fail"]:
                raise OSError("owned fake provider removal failed")
            present["value"] = False

        launch.registry.register(OwnedResource(
            "container:fixture-retained", launch.owner,
            lambda: ResourcePresence.OWNED if present["value"] else ResourcePresence.ABSENT,
            remove, (launch.bridge_resource,)))
        return present

    def test_failed_provider_cleanup_cannot_retain_broker_authority(self):
        launch = self.launch().start()
        process, directory = launch.process, launch.directory
        present = self.failing_provider_dependent(launch)
        launch.attach()
        result = launch.stop(37)
        self.assertEqual(37, result.primary_status)
        self.assertIn("container:fixture-retained", result.remaining)
        self.assertIn(launch.process_resource, result.remaining)
        self.assertEqual(["container:fixture-retained"], [failure.identity for failure in result.failures])
        self.assertEqual(0, process.returncode)
        self.assertTrue(process.stdout.closed)
        self.assertIsNone(launch.process)
        self.assertIsNone(launch.lifetime_writer)
        self.assertEqual("", launch.token)
        self.assertIsNone(launch.address)
        self.assertEqual(LifecycleState.CLEANUP_FAILED, launch.lifecycle.state)
        # Retained resource identities do not prove live host admission; nor do
        # we pretend dependency-retained filesystem resources were removed.
        self.assertTrue(directory.exists())
        with self.assertRaises(LifecycleError):
            launch.environment()
        present["fail"] = False
        self.assertFalse(launch.stop(37).remaining)
        self.assertFalse(directory.exists())
        self.assertEqual(LifecycleState.REMOVED, launch.lifecycle.state)

    def test_required_startup_failures_leave_no_resources(self):
        for mode in ("exit", "timeout", "oversize", "malformed"):
            with self.subTest(mode=mode):
                launch = self.launch(self.make_build(mode))
                with self.assertRaises((LifecycleError, ValueError)):
                    launch.start(timeout=.15)
                self.assertEqual((), launch.registry.identities)
                self.assertIsNone(launch.process)
                self.assertIsNone(launch.lifetime_writer)
                self.assertFalse(launch.directory.exists())
                self.assertEqual(LifecycleState.REMOVED, launch.lifecycle.state)

    def test_explicit_stop_kills_and_reaps_owned_child_that_ignores_eof_and_term(self):
        launch = self.launch(self.make_build("ignore-termination")).start()
        process = launch.process
        started = time.monotonic()
        result = launch.stop(23)
        self.assertLess(time.monotonic() - started, 7)
        self.assertEqual(23, result.primary_status)
        self.assertFalse(result.remaining)
        self.assertEqual(-9, process.returncode)
        self.assertFalse(launch.directory.exists())
        self.assertEqual("", launch.token)

    def test_spawn_failure_removes_config_and_lifetime(self):
        launch = self.launch()
        with mock.patch("tic_broker.subprocess.Popen", side_effect=OSError("owned fixture failure")):
            with self.assertRaises(OSError):
                launch.start()
        self.assertFalse(launch.directory.exists())
        self.assertIsNone(launch.lifetime_writer)
        self.assertFalse(launch.registry.identities)

    def test_registration_rejection_retains_no_untransferred_resource(self):
        for rejected in (1, 2, 3):
            with self.subTest(rejected=rejected):
                launch = self.launch()
                register = launch.registry.register
                calls = 0

                def reject_selected(resource):
                    nonlocal calls
                    calls += 1
                    if calls == rejected:
                        raise LifecycleError("fixture rejected resource transfer")
                    register(resource)

                with mock.patch.object(launch.registry, "register", side_effect=reject_selected):
                    with self.assertRaises(LifecycleError):
                        launch.start()
                self.assertFalse(launch.registry.identities)
                self.assertIsNone(launch.process)
                self.assertIsNone(launch.lifetime_writer)
                self.assertFalse(launch.directory.exists())

    def test_build_rejects_malformed_revision_digest_and_platform(self):
        for field, value in (("native_revision", "invalid-revision"),
                             ("broker_sha256", "invalid"), ("native_sha256", "invalid"),
                             ("guest_client_sha256", "invalid"),
                             ("guest_client_platform", "darwin/arm64")):
            with self.subTest(field=field):
                self.manifest.write_text(json.dumps({**self.binding, field: value}))
                with self.assertRaises(LifecycleError):
                    self.fixture_build()

    def test_ready_revision_must_match_trusted_installed_manifest(self):
        # A well-formed trusted manifest revision is authoritative, but a broker
        # compiled for a different native build cannot become ready under it.
        self.binding["native_revision"] = "0" * 40
        self.manifest.write_text(json.dumps(self.binding))
        launch = self.launch()
        self.assertEqual("0" * 40, launch.build.native_revision)
        with self.assertRaisesRegex(LifecycleError, "build/policy mismatch"):
            launch.start()
        self.assertFalse(launch.registry.identities)
        self.assertIsNone(launch.process)

    def test_unsafe_executable_mode_is_rejected_before_any_launch_effect(self):
        launch = self.launch()
        self.native.chmod(0o777)
        with self.assertRaises(LifecycleError):
            launch.start()
        self.assertIsNone(launch.directory)
        self.assertFalse(launch.registry.identities)

    def active_native_with_real_broker(self):
        broker = os.environ.get("TIC_PROXY_TEST_BROKER")
        if not broker:
            self.skipTest("set TIC_PROXY_TEST_BROKER to an explicit owned compiled artifact")
        subprocess.run(["git", "init", "--quiet", str(self.workspace)], check=True)
        self.native.write_text(
            f"#!{sys.executable}\n"
            "from pathlib import Path\nimport os, signal, time\n"
            "base = Path(__file__)\n"
            "def stop(*args):\n"
            "    base.with_suffix('.terminated').write_text('terminated')\n"
            "    raise SystemExit(0)\n"
            "signal.signal(signal.SIGTERM, stop)\n"
            "base.with_suffix('.started').write_text(str(Path(os.environ['HOME']).parent))\n"
            "while True: time.sleep(.01)\n")
        native_hash = hashlib.sha256(self.native.read_bytes()).hexdigest()
        Path(str(self.native) + ".tic-proxy.json").write_text(json.dumps({
            "native_revision": NATIVE_REVISION, "policy_version": 1, "sha256": native_hash}))
        broker = Path(broker).resolve()
        self.binding.update(broker_executable=str(broker), broker_sha256=hashlib.sha256(broker.read_bytes()).hexdigest(),
                            native_sha256=native_hash, guest_client_sha256=native_hash)
        self.manifest.write_text(json.dumps(self.binding))
        launch = self.launch().start()
        return launch

    def send_active_request(self, launch, connection):
        request = json.dumps({"token": launch.token, "request": {
            "version": 2, "command": "tic", "argv": ["list"], "stdin": ""}}).encode()
        connection.sendall(struct.pack("!I", len(request)) + request)
        # Hold the request connection open while testing lifetime cancellation.
        deadline = time.monotonic() + 3
        while not self.native.with_suffix(".started").exists() and time.monotonic() < deadline:
            time.sleep(.01)
        self.assertTrue(self.native.with_suffix(".started").exists())
        private = Path(self.native.with_suffix(".started").read_text())
        self.assertTrue(private.is_dir())
        return private

    def test_real_broker_lifetime_eof_cancels_active_native_when_explicitly_selected(self):
        launch = self.active_native_with_real_broker()
        process = launch.process
        host, port = launch.address.rsplit(":", 1)
        with socket.create_connection((host, int(port)), timeout=3) as connection:
            private = self.send_active_request(launch, connection)
            launch.close_lifetime()
            self.assertEqual(0, process.wait(timeout=3))
            self.assertTrue(self.native.with_suffix(".terminated").exists())
            self.assertFalse(private.exists())
        self.assertFalse(launch.stop().remaining)

    def test_failed_provider_cleanup_still_cancels_native_with_real_broker(self):
        launch = self.active_native_with_real_broker()
        process, directory = launch.process, launch.directory
        present = self.failing_provider_dependent(launch)
        launch.attach()
        host, port = launch.address.rsplit(":", 1)
        with socket.create_connection((host, int(port)), timeout=3) as connection:
            private = self.send_active_request(launch, connection)
            result = launch.stop(41)
            self.assertEqual(41, result.primary_status)
            self.assertEqual(["container:fixture-retained"], [failure.identity for failure in result.failures])
            self.assertIn(launch.bridge_resource, result.remaining)
            self.assertIn(launch.process_resource, result.remaining)
            self.assertEqual(0, process.returncode)
            self.assertTrue(self.native.with_suffix(".terminated").exists())
            self.assertFalse(private.exists())
            self.assertIsNone(launch.process)
            self.assertIsNone(launch.lifetime_writer)
            self.assertEqual("", launch.token)
            self.assertIsNone(launch.address)
            self.assertTrue(directory.exists())
        present["fail"] = False
        self.assertFalse(launch.stop(41).remaining)
        self.assertFalse(directory.exists())

    def test_literal_identity_reaches_native_intentional_environment_with_real_broker(self):
        broker = os.environ.get("TIC_PROXY_TEST_BROKER")
        if not broker:
            self.skipTest("set TIC_PROXY_TEST_BROKER to an explicit owned compiled artifact")
        subprocess.run(["git", "init", "--quiet", str(self.workspace)], check=True)
        self.native.write_text(
            f"#!{sys.executable}\n"
            "import json, os\n"
            "print(json.dumps({key: os.environ[key] for key in ("
            "'GIT_CONFIG_COUNT', 'GIT_CONFIG_KEY_0', 'GIT_CONFIG_VALUE_0', "
            "'GIT_CONFIG_KEY_1', 'GIT_CONFIG_VALUE_1', 'GIT_CONFIG_KEY_2', 'GIT_CONFIG_VALUE_2')}))\n")
        native_hash = hashlib.sha256(self.native.read_bytes()).hexdigest()
        Path(str(self.native) + ".tic-proxy.json").write_text(json.dumps({
            "native_revision": NATIVE_REVISION, "policy_version": 1, "sha256": native_hash}))
        broker = Path(broker).resolve()
        self.binding.update(broker_executable=str(broker), broker_sha256=hashlib.sha256(broker.read_bytes()).hexdigest(),
                            native_sha256=native_hash, guest_client_sha256=native_hash)
        self.manifest.write_text(json.dumps(self.binding))
        # Alternate each field between empty and whitespace so a fallback or
        # trimming at either config/child boundary cannot pass accidentally.
        for values in (("", " \t\n", ""), (" \t", "", " \n")):
            with self.subTest(values=repr(values)):
                launch = self.launch(user_name=values[0], user_email=values[1], namespace=values[2]).start()
                response = self.exchange(launch.address, launch.token)
                self.assertEqual(0, response["exit"], response)
                environment = json.loads(response["stdout"])
                self.assertEqual("3", environment["GIT_CONFIG_COUNT"])
                for index, (key, value) in enumerate(zip(("user.name", "user.email", "meta.namespace"), values)):
                    self.assertEqual(key, environment[f"GIT_CONFIG_KEY_{index}"])
                    self.assertEqual(value, environment[f"GIT_CONFIG_VALUE_{index}"])
                self.assertFalse(launch.stop().remaining)

    def test_real_compiled_broker_when_explicitly_selected(self):
        broker = os.environ.get("TIC_PROXY_TEST_BROKER")
        native = os.environ.get("TIC_PROXY_TEST_NATIVE")
        if not broker or not native:
            self.skipTest("set TIC_PROXY_TEST_BROKER and TIC_PROXY_TEST_NATIVE to explicit owned compiled artifacts")
        subprocess.run(["git", "init", "--quiet", str(self.workspace)], check=True)
        broker, native = Path(broker).resolve(), Path(native).resolve()
        self.binding.update(broker_executable=str(broker), broker_sha256=hashlib.sha256(broker.read_bytes()).hexdigest(),
                            native_executable=str(native), native_sha256=hashlib.sha256(native.read_bytes()).hexdigest())
        self.manifest.write_text(json.dumps(self.binding))
        launch = self.launch().start()
        self.assertFalse((self.common / "git-meta.sqlite").exists())
        bridge = launch.start_bridge({"127.0.0.1"})
        response = self.exchange(f"127.0.0.1:{bridge.port}", launch.token)
        self.assertEqual(0, response["exit"], response)


if __name__ == "__main__":
    unittest.main()
