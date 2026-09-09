"""Native identity and transport regressions at the outer-runtime boundary."""

from dataclasses import replace
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import sandbox_runtime as runtime


CONTENT = "sha256:" + "1" * 64
CONFIG = "sha256:" + "2" * 64
LAYER = "sha256:" + "3" * 64
REFERENCE = "localhost/codex-sandbox@" + CONTENT


def native(name=REFERENCE, content=CONTENT):
    return {"Image": {"Name": name, "Target": {
        "mediaType": "application/vnd.oci.image.manifest.v1+json",
        "digest": content, "size": 123,
    }}, "ImageConfigDesc": {"digest": CONFIG},
        "ImageConfig": {"rootfs": {"diff_ids": [LAYER]}}}


def lima():
    backend = object.__new__(runtime.Lima)
    backend.record = {"instance": "sandbox-host-test", "namespace": "default"}
    backend.host = Mock()
    backend.host.state = Path('/owned-state')
    backend.host.runtime_epoch.return_value = ('a' * 32, 'b' * 32)
    backend.host.verify_runtime.side_effect = lambda record: runtime.Host.verify_runtime(backend.host, record)
    return backend


class ImageIdentityTest(unittest.TestCase):
    def setUp(self):
        self.enterContext(runtime.verification_scope())

    def test_launch_reuses_verification_across_helpers_but_not_new_launches(self):
        backend = lima()
        child = lima()
        with runtime.verification_scope():
            backend.verify()
            inherited = os.environ.copy()
            backend.verify()
            with patch.dict(os.environ, inherited, clear=True):
                child.verify()
            backend.host.verify.assert_called_once()
            child.host.verify.assert_not_called()
            # A nested/new launcher must not accept its parent's receipt.
            with runtime.verification_scope():
                child.verify()
            child.host.verify.assert_called_once()

    def test_service_restart_or_record_change_requires_full_verification(self):
        backend = lima()
        with runtime.verification_scope():
            backend.verify()
            for epoch in [('c' * 32, 'b' * 32), ('c' * 32, 'd' * 32)]:
                backend.host.runtime_epoch.return_value = epoch
                backend.verify()
            backend.record['generation'] = 'replacement'
            backend.verify()
            self.assertEqual(4, backend.host.verify.call_count)

    def test_failed_or_racing_verification_cannot_publish_a_receipt(self):
        backend = lima()
        with runtime.verification_scope():
            backend.host.verify.side_effect = ValueError('policy changed')
            with self.assertRaisesRegex(ValueError, 'policy changed'):
                backend.verify()
            backend.host.verify.side_effect = None
            backend.host.runtime_epoch.side_effect = [('a', 'b'), ('a', 'c')]
            with self.assertRaisesRegex(ValueError, 'restarted during verification'):
                backend.verify()
            backend.host.runtime_epoch.side_effect = None
            backend.verify()
            self.assertEqual(3, backend.host.verify.call_count)

    def test_cached_verification_still_checks_vm_identity(self):
        backend = lima()
        with runtime.verification_scope():
            backend.verify()
            backend.host.runtime_epoch.side_effect = ValueError('VM identity changed')
            with self.assertRaisesRegex(ValueError, 'VM identity changed'):
                backend.verify()

    def test_cancelled_router_reconciles_exec_published_after_initial_cleanup_inspection(self):
        backend = lima()
        backend.run = Mock(return_value=SimpleNamespace(stdout=json.dumps([{"ID": "a" * 64}])))
        process = Mock()
        process.poll.return_value = None
        listings = iter(["", '42 exec_id:"codex-forward-owned"\n', ""])
        killed = []

        def guest(arguments, **kwargs):
            if "kill" in arguments:
                killed.append(arguments)
                process.poll.return_value = 143
                return SimpleNamespace(stdout="")
            # Cancel before the first startup inspection has published an exec.
            if not guest.cancelled:
                guest.cancelled = True
                raise SystemExit(143)
            return SimpleNamespace(stdout=next(listings))

        guest.cancelled = False
        backend.guest = guest
        with patch.object(runtime.subprocess, "Popen", return_value=process), \
                patch.object(runtime.uuid, "uuid4", return_value=SimpleNamespace(hex="owned")), \
                patch.object(runtime.time, "sleep"):
            with self.assertRaises(SystemExit) as result:
                backend.forward_proxy("proxy")
        self.assertEqual(143, result.exception.code)
        self.assertEqual(1, len(killed))
        self.assertEqual(["--exec-id", "codex-forward-owned", "a" * 64], killed[0][-3:])
        process.kill.assert_not_called()
        process.stdin.close.assert_called_once()

    def test_native_empty_inspection_means_missing_but_malformed_identity_is_fatal(self):
        backend = lima()
        backend.run = Mock(return_value=SimpleNamespace(stdout=""))
        with self.assertRaises(subprocess.CalledProcessError):
            backend.inspect_image("absent")
        backend.run.return_value.stdout = "broken-json"
        with self.assertRaises(json.JSONDecodeError):
            backend.inspect_image("corrupt")

    def test_volume_create_collision_cannot_initialize_another_creators_volume(self):
        backend = lima()
        backend.run = Mock(return_value=SimpleNamespace(stdout=json.dumps([
            {"Labels": {"dev.codex.volume-owner": "another-creator"}},
        ])))
        backend.guest = Mock()
        with self.assertRaisesRegex(runtime.RuntimeError, "another creator"):
            backend.initialize_volume("collision", 501, 20, "this-creator")
        backend.guest.assert_not_called()

    def test_replaced_vm_cannot_receive_container_removal(self):
        backend = lima()
        backend.host.machine.side_effect = ValueError("recorded VM identity changed")
        with patch.object(runtime.subprocess, "run") as run:
            with self.assertRaisesRegex(ValueError, "identity changed"):
                backend.terminate("previous-generation-container")
        run.assert_not_called()

    def test_registered_aliases_preserve_the_requested_runnable_reference(self):
        backend = lima()
        backend.run = Mock(return_value=SimpleNamespace(stdout=json.dumps([
            native("docker.io/example:mutable"), native(),
        ])))
        self.assertEqual(runtime.Image(REFERENCE, CONTENT, CONFIG, LAYER),
                         backend.inspect_image(REFERENCE))

    def test_aliases_cannot_hide_conflicting_content(self):
        backend = lima()
        backend.run = Mock(return_value=SimpleNamespace(stdout=json.dumps([
            native(), native("docker.io/example:mutable", "sha256:" + "4" * 64),
        ])))
        with self.assertRaisesRegex(runtime.RuntimeError, "disagree"):
            backend.inspect_image(REFERENCE)

    def test_digest_name_cannot_claim_another_descriptor(self):
        backend = lima()
        backend.run = Mock(return_value=SimpleNamespace(stdout=json.dumps([
            native(REFERENCE, "sha256:" + "4" * 64),
        ])))
        with self.assertRaisesRegex(runtime.RuntimeError, "differs"):
            backend.inspect_image(REFERENCE)

    def test_rejects_image_changed_during_registration(self):
        backend = lima()
        image = runtime.Image("example:mutable", CONTENT, CONFIG, LAYER)
        backend.inspect_image = Mock(side_effect=[image,
            subprocess.CalledProcessError(1, ["inspect", "missing"]),
            replace(image, config="sha256:" + "4" * 64)])
        backend.register_reference = Mock()
        with self.assertRaisesRegex(runtime.RuntimeError, "changed during"):
            backend.resolve_image(image.reference)
        self.assertEqual(1, backend.register_reference.call_count, "unverified image reached the FROM alias")

    def test_local_from_alias_must_match_registered_descriptor(self):
        backend = lima()
        image = runtime.Image("example:mutable", CONTENT, CONFIG, LAYER)
        backend.inspect_image = Mock(side_effect=[image,
            subprocess.CalledProcessError(1, ["inspect", "missing"]),
            image, image, replace(image, content="sha256:" + "4" * 64)])
        backend.register_reference = Mock()
        with self.assertRaisesRegex(runtime.RuntimeError, "local FROM"):
            backend.resolve_image(image.reference)

    def test_cached_image_resolution_does_not_republish_verified_names(self):
        backend = lima()
        tag = "localhost/codex-sandbox:sha256-" + CONTENT.removeprefix("sha256:")
        immutable = tag + "@" + CONTENT
        images = {name: runtime.Image(name, CONTENT, CONFIG, LAYER)
                  for name in ("example:mutable", immutable, tag)}
        backend.inspect_image = Mock(side_effect=images.__getitem__)
        backend.register_reference = Mock(side_effect=AssertionError("cache hit must not publish"))
        self.assertEqual(images[immutable], backend.resolve_image("example:mutable"))
        self.assertEqual(set(images), {call.args[0] for call in backend.inspect_image.call_args_list})
        backend.host.guest.assert_not_called()

    def test_cached_names_cannot_hide_different_image_identity(self):
        tag = "localhost/codex-sandbox:sha256-" + CONTENT.removeprefix("sha256:")
        immutable = tag + "@" + CONTENT
        for alias in (immutable, tag):
            for field in ("content", "config", "rootfs"):
                with self.subTest(alias=alias, field=field):
                    backend = lima()
                    images = {name: runtime.Image(name, CONTENT, CONFIG, LAYER)
                              for name in ("example:mutable", immutable, tag)}
                    images[alias] = replace(images[alias], **{field: "sha256:" + "4" * 64})
                    backend.inspect_image = Mock(side_effect=images.__getitem__)
                    backend.register_reference = Mock(side_effect=AssertionError("must not repair a collision"))
                    with self.assertRaisesRegex(runtime.RuntimeError, "registration differs"):
                        backend.resolve_image("example:mutable")

    def test_missing_from_tag_is_published_without_replacing_canonical_image(self):
        backend = lima()
        tag = "localhost/codex-sandbox:sha256-" + CONTENT.removeprefix("sha256:")
        immutable = tag + "@" + CONTENT
        canonical = runtime.Image(immutable, CONTENT, CONFIG, LAYER)
        images = {"example:mutable": replace(canonical, reference="example:mutable"),
                  immutable: canonical}

        def inspect(name):
            if name not in images:
                raise subprocess.CalledProcessError(1, ["inspect", name])
            return images[name]

        def register(source, target):
            images.setdefault(target, replace(images[source], reference=target))

        backend.inspect_image = inspect
        backend.register_reference = register
        self.assertEqual(canonical, backend.resolve_image("example:mutable"))
        self.assertIs(canonical, images[immutable])
        self.assertEqual(replace(canonical, reference=tag), images[tag])

    def test_same_rootfs_does_not_make_a_mutable_tag_an_immutable_identity(self):
        backend = lima()
        image = runtime.Image(REFERENCE, CONTENT, CONFIG, LAYER)
        backend.inspect_image = Mock(return_value=image)
        backend.run = Mock(return_value=SimpleNamespace(stdout=json.dumps([{
            "Image": "example:mutable", "SnapshotKey": "owned-container", "Snapshotter": "overlayfs",
        }])))
        backend.guest = Mock(return_value=SimpleNamespace(stdout=json.dumps({"Parent": LAYER})))
        self.assertFalse(backend.container_matches_image("owned", image))

    def test_snapshot_parent_must_match_even_when_image_name_matches(self):
        backend = lima()
        image = runtime.Image(REFERENCE, CONTENT, CONFIG, LAYER)
        backend.inspect_image = Mock(return_value=image)
        backend.run = Mock(return_value=SimpleNamespace(stdout=json.dumps([{
            "Image": REFERENCE, "SnapshotKey": "owned-container", "Snapshotter": "overlayfs",
        }])))
        backend.guest = Mock(return_value=SimpleNamespace(stdout=json.dumps({"Parent": LAYER})))
        self.assertTrue(backend.container_matches_image("owned", image))
        backend.guest.return_value.stdout = json.dumps({"Parent": "sha256:" + "4" * 64})
        self.assertFalse(backend.container_matches_image("owned", image))


class NetworkMembershipTest(unittest.TestCase):
    def backend(self, addresses, allocation):
        backend = lima()
        backend.run = Mock(side_effect=[
            SimpleNamespace(stdout=json.dumps([{
                "ID": "a" * 64,
                "Process": {"NetNS": {"Interfaces": [{"Name": "eth7", "Addrs": addresses}]}},
            }])),
            SimpleNamespace(stdout=json.dumps([{"CNI": {"name": "owned", "plugins": [{
                "type": "bridge", "ipam": {"ranges": [[{"subnet": "10.254.254.0/24"}]]},
            }]}}])),
        ])
        backend.guest = Mock(return_value=SimpleNamespace(stdout=allocation))
        return backend

    def test_uses_live_interface_and_ipam_owner_instead_of_interface_order(self):
        backend = self.backend(["10.254.254.130/24"], "default-" + "a" * 64 + "\neth7\n")
        self.assertEqual("10.254.254.130", backend.network_address("owned", "owned"))

    def test_subnet_match_does_not_substitute_for_allocation_ownership(self):
        backend = self.backend(["10.254.254.130/24"], "default-" + "b" * 64 + "\neth7\n")
        with self.assertRaisesRegex(runtime.RuntimeError, "membership"):
            backend.network_address("owned", "owned")

    def test_rejects_ambiguous_live_addresses(self):
        backend = self.backend(["10.254.254.130/24", "10.254.254.131/24"], "default-" + "a" * 64 + "\neth7\n")
        with self.assertRaisesRegex(runtime.RuntimeError, "ambiguous"):
            backend.network_address("owned", "owned")


class TransportTest(unittest.TestCase):
    def setUp(self):
        self.enterContext(runtime.verification_scope())

    def test_failed_pre_start_supervision_cleans_created_container_without_attaching(self):
        backend = runtime.Podman()
        backend.workload_argv = Mock(return_value=["owned-create"])
        backend.popen = Mock()
        backend.terminate = Mock()
        creation = Mock()
        creation.wait.return_value = 0

        def supervise():
            creation.wait.assert_called()
            backend.popen.assert_not_called()
            raise ValueError("supervision failed")

        with patch.object(runtime.subprocess, "Popen", return_value=creation):
            with self.assertRaisesRegex(ValueError, "supervision failed"):
                with backend.workload(None, "owned", [], before_start=supervise):
                    self.fail("unsupervised container reached attachment")
        backend.popen.assert_not_called()
        backend.terminate.assert_called_once_with("owned")

    def test_recorded_owner_rejects_replacement_vm_namespace_or_policy(self):
        backend = lima()
        backend.host.state = Path("/owned/state")
        backend.record.update(generation="a" * 32, vm_identity="owned-vm", network_digest="owned-policy")
        identity = runtime.runtime_identity(backend)
        with patch.object(runtime, "Lima", return_value=backend):
            self.assertIs(backend, runtime.recorded_runtime(identity))
            for key in ("generation", "namespace", "network_digest", "vm_identity"):
                with self.assertRaisesRegex(ValueError, "owner changed"):
                    runtime.recorded_runtime({**identity, key: "replacement"})

    def test_missing_runtime_identity_means_legacy_podman_not_current_default(self):
        with patch.object(runtime, "Lima") as lima_factory:
            self.assertEqual("podman", runtime.state_runtime({"proxies": []}).provider)
            with self.assertRaisesRegex(ValueError, "unsupported recorded"):
                runtime.state_runtime({"runtime": {"provider": "lima"}})
            lima_factory.assert_not_called()

    def test_signal_during_creation_awaits_producer_before_removing_container(self):
        backend = runtime.Podman()
        image = runtime.Image(REFERENCE, CONTENT, CONFIG, LAYER)
        creation = Mock()
        creation.wait.side_effect = [SystemExit(143), 0]
        removed = []
        def remove(name):
            self.assertEqual(2, creation.wait.call_count, "cleanup raced unfinished container creation")
            removed.append(name)
        backend.terminate = remove
        with patch.object(runtime.subprocess, "Popen", return_value=creation):
            with self.assertRaises(SystemExit) as result:
                with backend.workload(image, "owned", ["--network", "none"]):
                    self.fail("interrupted creation reached attachment")
        self.assertEqual(143, result.exception.code)
        self.assertEqual(["owned"], removed)

    def test_environment_is_private_and_removed_after_failure(self):
        backend = runtime.Podman()
        with self.assertRaisesRegex(ValueError, "owned failure"):
            with backend.environment_file({"OWNED_TOKEN": "dummy $token `literal`"}) as args:
                path = Path(args[1])
                self.assertEqual(0o600, path.stat().st_mode & 0o777)
                self.assertEqual("OWNED_TOKEN=dummy $token `literal`\n", path.read_text())
                self.assertNotIn("dummy", repr(args))
                raise ValueError("owned failure")
        self.assertFalse(path.exists())

    def test_environment_rejects_line_injection_before_staging(self):
        with self.assertRaises(runtime.RuntimeError):
            with runtime.Podman().environment_file({"TERM": "xterm\nGH_TOKEN=injected"}):
                self.fail("invalid environment published")

    def test_missing_vm_fails_before_workload_transport(self):
        with patch.object(runtime, "Host") as host:
            host.return_value.record.return_value = {"phase": "ready"}
            host.return_value.verify_runtime.side_effect = ValueError("recorded VM is missing")
            with self.assertRaisesRegex(ValueError, "missing"):
                runtime.Lima("owned-state")

    def test_lima_preserves_arguments_and_suppresses_guest_proxy_environment(self):
        backend = lima()
        args = ["exec", "owned", "printf", "%s", "spaces ' $() `literal`"]
        command = backend.argv(args)
        self.assertEqual(args, command[-len(args):])
        self.assertIn("-uHTTP_PROXY", command)
        self.assertIn("-uhttp_proxy", command)

    def test_wait_preserves_workload_status_and_transport_failure(self):
        for backend in (runtime.Podman(), lima()):
            backend.run = Mock(return_value=SimpleNamespace(stdout="37\n"))
            self.assertEqual(37, backend.wait("owned"))
            backend.run.side_effect = subprocess.CalledProcessError(255, ["owned-transport"])
            with self.assertRaises(subprocess.CalledProcessError):
                backend.wait("owned")

    def test_invalid_policy_prevents_workload_execution(self):
        backend = lima()
        backend.host.verify.side_effect = ValueError("policy changed")
        with self.assertRaisesRegex(ValueError, "policy changed"):
            backend.workload_argv(runtime.Image(REFERENCE, CONTENT, CONFIG, LAYER), [])

    def test_old_lima_hosts_cannot_create_unprotected_relays(self):
        backend = lima()
        backend.record["files"] = {}
        backend.run = Mock()
        for internal in (True, False):
            with self.assertRaisesRegex(runtime.RuntimeError, "trusted relay"):
                backend.create_relay_network("owned", internal=internal)
        backend.run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
