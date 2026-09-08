"""Host setup rejects aliases, stale ownership, and unsupported bind sources."""

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


SOURCE = Path(__file__).resolve().parents[1] / "lima/host.py"
spec = importlib.util.spec_from_file_location("lima_host", SOURCE)
host = importlib.util.module_from_spec(spec)
spec.loader.exec_module(host)
verify_spec = importlib.util.spec_from_file_location("verify_host", SOURCE.with_name("verify-host.py"))
verify = importlib.util.module_from_spec(verify_spec)
verify_spec.loader.exec_module(verify)
mount_spec = importlib.util.spec_from_file_location("mount_shares", SOURCE.with_name("mount-shares.py"))
mounts = importlib.util.module_from_spec(mount_spec)
mount_spec.loader.exec_module(mounts)
network_spec = importlib.util.spec_from_file_location("configure_network", SOURCE.with_name("configure-network.py"))
network = importlib.util.module_from_spec(network_spec)
network_spec.loader.exec_module(network)


class HostTests(unittest.TestCase):
    def test_changed_native_network_cannot_be_adopted_as_trusted_policy(self):
        # Captured from the pinned 2.3.5 stack's disposable host gate, including
        # its real host-local range encoding. This is native input, not a mock.
        original = (Path(__file__).parent / "fixtures/lima-public-network.json").read_text()
        network.validate(json.loads(original))
        for mutation in ("private-route", "lost-isolation", "ipv6"):
            changed = json.loads(original)
            if mutation == "private-route":
                changed["plugins"][0]["ipam"]["routes"].append({"dst": "192.168.1.0/24", "gw": "10.254.254.1"})
            elif mutation == "lost-isolation":
                changed["plugins"][2].pop("ingressPolicy")
            else:
                changed["plugins"][0]["ipam"]["ranges"].append([{"subnet": "fd00::/64"}])
            with self.subTest(mutation=mutation), self.assertRaisesRegex(ValueError, "validated bridge"):
                network.validate(changed)

    def test_builder_cannot_silently_use_another_daemon_or_namespace(self):
        worker = {"labels": {"org.mobyproject.buildkit.worker.executor": "containerd",
                             "org.mobyproject.buildkit.worker.containerd.namespace": "default",
                             "org.mobyproject.buildkit.worker.containerd.uuid": "owned"},
                  "buildkitVersion": {"version": "v0.31.2"}}
        info = {"ID": "owned", "ServerVersion": "v2.3.3", "SecurityOptions": ["name=rootless"]}
        verify.verify_worker([worker], info, "default")
        for change in ({"ID": "another daemon"}, {"SecurityOptions": []}):
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, "same rootless"):
                verify.verify_worker([worker], {**info, **change}, "default")
        with self.assertRaisesRegex(ValueError, "namespace"):
            verify.verify_worker([worker], info, "buildkit")

    def test_lima_fstab_space_repair_is_idempotent_and_preserves_unrelated_entries(self):
        unrelated = "LABEL=root\t/\text4\tdefaults\t0 1\n"
        raw = "mount0\t/host/external metadata\tvirtiofs\tro,nofail,comment=cloudconfig\t0\t0\n"
        share = {"mountPoint": "/host/external metadata", "writable": False}
        fixed = mounts.repair(unrelated + raw, [share])
        self.assertEqual(unrelated + raw.replace("external metadata", "external\\040metadata"), fixed)
        self.assertEqual(fixed, mounts.repair(fixed, [share]))
        with self.assertRaisesRegex(ValueError, "unexpected"):
            mounts.repair(unrelated + raw.replace("ro,", "rw,"), [share])

    def test_unmounted_directory_and_changed_mount_mode_are_not_host_shares(self):
        with tempfile.TemporaryDirectory() as temporary:
            share = {"mountPoint": temporary, "writable": True}
            mounted = {"target": temporary, "source": "mount0", "fstype": "virtiofs", "options": "rw,relatime"}
            with patch.object(verify, "run", return_value=json.dumps({"filesystems": [mounted]})):
                verify.verify_mount(share, 0)
            for changes in ({"target": "/", "source": "/dev/vda", "fstype": "ext4"},
                            {"source": "mount1"}, {"options": "ro,relatime"}):
                with self.subTest(changes=changes), patch.object(verify, "run", return_value=json.dumps(
                        {"filesystems": [{**mounted, **changes}]})):
                    with self.assertRaisesRegex(ValueError, "effective"):
                        verify.verify_mount(share, 0)

    def test_symlink_cannot_escape_shared_root(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            shared = root / "project with spaces"
            shared.mkdir()
            external = root / "external metadata"
            external.mkdir()
            (shared / "metadata").symlink_to(external)
            record = {"shares": host.shares([], [shared])}
            with self.assertRaisesRegex(ValueError, "outside"):
                host.bind_source(record, shared / "metadata", True)
            record["shares"] = host.shares([external], [shared])
            self.assertEqual(external, host.bind_source(record, shared / "metadata"))
            with self.assertRaisesRegex(ValueError, "outside"):
                host.bind_source(record, shared / "metadata", True)

    def test_alias_and_parent_shares_are_ambiguous(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            child = root / "child"
            child.mkdir()
            alias = root / "alias"
            alias.symlink_to(child)
            for read, write in (([root], [child]), ([child], [alias])):
                with self.subTest(read=read), self.assertRaisesRegex(ValueError, "overlapping"):
                    host.shares(read, write)

    def test_private_state_rejects_symlink_and_group_access(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            directory = root / "state"
            directory.mkdir(mode=0o750)
            with self.assertRaisesRegex(ValueError, "private"):
                host.Host(directory)
            directory.chmod(0o700)
            alias = root / "alias"
            alias.symlink_to(directory)
            with self.assertRaisesRegex(ValueError, "private"):
                host.Host(alias)

    def test_setup_does_not_adopt_preexisting_vm(self):
        with tempfile.TemporaryDirectory() as temporary:
            instance = host.Host(Path(temporary))
            with patch.object(host, "machines", return_value={"sandbox-host": {}}), \
                    patch.object(host, "command") as command:
                with self.assertRaisesRegex(ValueError, "adopt"):
                    instance.setup("sandbox-host", [], [])
                command.assert_not_called()
            self.assertFalse(instance.record_path.exists())

    def test_setup_cannot_share_its_control_source(self):
        with tempfile.TemporaryDirectory() as temporary:
            instance = host.Host(Path(temporary))
            source = instance.state / "source"
            source.mkdir()
            with patch.object(host, "command") as command:
                with self.assertRaisesRegex(ValueError, "control"):
                    instance.setup("sandbox-host", [], [source])
                command.assert_not_called()

    def test_interrupted_creation_keeps_identity_and_checks_snapshot_before_retry(self):
        with tempfile.TemporaryDirectory() as temporary:
            instance = host.Host(Path(temporary))
            def command(*args, **kwargs):
                if args[1] == "create":
                    raise OSError("interrupted creation")
            with patch.object(host, "machines", return_value={}), patch.object(host, "command", side_effect=command):
                with self.assertRaisesRegex(OSError, "interrupted"):
                    instance.setup("sandbox-host", [], [])
            record = instance.record()
            self.assertEqual("creating", record["phase"])
            (instance.state / "source/install-slirp4netns.py").write_text("changed")
            with patch.object(host, "command") as command:
                with self.assertRaisesRegex(ValueError, "snapshot changed"):
                    instance.setup("sandbox-host", [], [])
                command.assert_not_called()
            self.assertEqual(record, instance.record())

    def test_changed_generation_cannot_start_or_reprovision(self):
        with tempfile.TemporaryDirectory() as temporary:
            instance = host.Host(Path(temporary))
            record = {"schema": 1, "instance": "sandbox-host", "phase": "ready", "generation": "owned", "shares": []}
            host.atomic_json(instance.record_path, record)
            machine = {"config": {"env": {"SANDBOX_GENERATION": "replacement"}, "mounts": []}}
            with patch.object(host, "machines", return_value={"sandbox-host": machine}), \
                    patch.object(host, "command") as command:
                with self.assertRaisesRegex(ValueError, "identity"):
                    instance.start()
                command.assert_not_called()

    def test_pending_startup_recovers_a_host_agent_without_its_socket(self):
        with tempfile.TemporaryDirectory() as temporary:
            instance = host.Host(Path(temporary))
            def interrupted(*args, **kwargs):
                if args[1] == "create":
                    raise OSError("creation interrupted")
            with patch.object(host, "machines", return_value={}), \
                    patch.object(host, "command", side_effect=interrupted):
                with self.assertRaises(OSError):
                    instance.setup("sandbox-host", [], [])
            record = instance.record()
            record["phase"] = "installing"
            host.atomic_json(instance.record_path, record)
            stopped = False
            def recover(*args, **kwargs):
                nonlocal stopped
                if args[1] == "stop":
                    stopped = True
                elif args[1] == "start":
                    if not stopped:
                        raise ValueError("missing host-agent socket")
                    raise InterruptedError("startup reached after stale-agent cleanup")
            with patch.object(host, "machines", return_value={"sandbox-host": {}}), \
                    patch.object(instance, "machine", return_value={"config": {}}), \
                    patch.object(host, "command", side_effect=recover):
                with self.assertRaisesRegex(InterruptedError, "startup reached"):
                    instance.setup("sandbox-host", [], [])
            self.assertEqual(record["generation"], instance.record()["generation"])
            with patch.object(host, "machines", return_value={"sandbox-host": {}}), \
                    patch.object(instance, "machine", side_effect=ValueError("replacement VM")), \
                    patch.object(host, "command") as command:
                with self.assertRaisesRegex(ValueError, "replacement VM"):
                    instance.setup("sandbox-host", [], [])
                command.assert_not_called()


if __name__ == "__main__":
    unittest.main()
