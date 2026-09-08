"""Host setup rejects aliases, stale ownership, and unsupported bind sources."""

import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
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
bind_spec = importlib.util.spec_from_file_location("check_binds", SOURCE.with_name("check-binds.py"))
binds = importlib.util.module_from_spec(bind_spec)
bind_spec.loader.exec_module(binds)


class HostTests(unittest.TestCase):
    def test_guest_batch_checks_final_entry_type_access_and_content(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            file = directory / "config"
            file.write_text("original")
            first = {"source": str(directory), "kind": "directory", "writable": False}
            last = {"source": str(file), "kind": "file", "writable": True,
                    "sha256": host.hashlib.sha256(b"original").hexdigest()}
            binds.check_binds([first, last])
            for changed, message in (({**last, "kind": "directory"}, "not a directory"),
                    ({**last, "sha256": "0" * 64}, "differs from the host"),
                    ({**last, "source": str(directory / "missing")}, "not a file")):
                with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                    binds.check_binds([first, changed])
            for denied, message in ((host.os.R_OK, "not readable"), (host.os.W_OK, "not writable")):
                with patch.object(binds.os, "access", side_effect=lambda path, mode:
                        not (path == file and mode == denied)):
                    with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                        binds.check_binds([first, last])

    def test_batch_preserves_duplicate_permissions_and_rejects_invalid_final_source_before_ssh(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            shared = root / "shared"
            shared.mkdir()
            file = shared / "literal ' $() name"
            file.write_text("matching contents")
            instance = host.Host(root)
            record = {"phase": "ready", "shares": [
                {"location": str(shared), "writable": True}]}

            def guest(_record, *args, **kwargs):
                return subprocess.run([sys.executable, *args[1:]], check=True, **kwargs)

            with patch.object(instance, "record", return_value=record), \
                    patch.object(instance, "verify_runtime"), \
                    patch.object(instance, "guest", side_effect=guest) as transport:
                self.assertEqual([
                    {"source": str(file), "writable": False},
                    {"source": str(shared), "writable": True},
                    {"source": str(file), "writable": True}],
                    instance.check_binds([(file, False), (shared, True), (file, True)]))
                transport.assert_called_once()
                transport.reset_mock()
                with self.assertRaisesRegex(ValueError, "outside"):
                    instance.check_binds([(shared, True), (root, False)])
                transport.assert_not_called()
                transport.side_effect = subprocess.CalledProcessError(255, ["ssh"])
                with self.assertRaises(subprocess.CalledProcessError):
                    instance.check_binds([(file, False)])

    def test_bind_preflight_reuses_verification_but_keeps_guest_access_checks(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            instance = host.Host(root)
            record = {'phase': 'ready', 'shares': [
                {'location': str(root), 'mountPoint': str(root), 'writable': True}]}
            with patch.object(instance, 'record', return_value=record), \
                    patch.object(instance, 'runtime_epoch', return_value=('a', 'b')), \
                    patch.object(instance, 'verify') as verify_full, \
                    patch.object(instance, 'guest') as guest, host.verification_scope():
                for _ in range(2):
                    self.assertEqual({'source': str(root), 'writable': True},
                        instance.check_bind(root, writable=True))
                verify_full.assert_called_once()
                self.assertEqual(2, guest.call_count, 'each bind needs one live guest batch')
                with host.verification_scope():
                    instance.check_bind(root)
                self.assertEqual(2, verify_full.call_count)

    def test_runtime_epoch_requires_both_active_services_and_current_vm(self):
        containerd = 'Id=containerd.service\nActiveState=active\nSubState=running\nInvocationID=' + 'a' * 32
        buildkit = 'Id=default-buildkit.service\nActiveState=active\nSubState=running\nInvocationID=' + 'b' * 32
        with tempfile.TemporaryDirectory() as temporary:
            instance = host.Host(Path(temporary))
            with patch.object(instance, 'machine') as machine, patch.object(instance, 'guest') as guest:
                guest.return_value = SimpleNamespace(stdout=buildkit + '\n\n' + containerd)
                self.assertEqual(('a' * 32, 'b' * 32), instance.runtime_epoch({'namespace': 'default'}))
                for output in (containerd, containerd + '\n\n' + containerd,
                        containerd + '\n\n' + buildkit.replace('active', 'inactive'),
                        containerd + '\n\n' + buildkit.replace('b' * 32, ''),
                        containerd + '\n\n' + buildkit.replace('running', 'dead')):
                    guest.return_value.stdout = output
                    with self.subTest(output=output), self.assertRaises(ValueError):
                        instance.runtime_epoch({'namespace': 'default'})
                guest.reset_mock()
                machine.side_effect = ValueError('replacement VM')
                with self.assertRaisesRegex(ValueError, 'replacement VM'):
                    instance.runtime_epoch({'namespace': 'default'})
                guest.assert_not_called()

    def test_quiet_verification_preserves_failure_diagnostics(self):
        with tempfile.TemporaryDirectory() as temporary:
            instance = host.Host(Path(temporary))
            error = subprocess.CalledProcessError(1, ['verifier'], stderr='policy changed\n')
            with patch.object(instance, 'machine'), patch.object(instance, 'guest', side_effect=[
                    SimpleNamespace(stdout='digest verifier'), error]), \
                    patch.object(host.sys, 'stderr', new_callable=io.StringIO) as stderr:
                with self.assertRaises(subprocess.CalledProcessError):
                    instance.verify({'files': {'verify-host.py': 'digest'}}, quiet=True)
                self.assertEqual('policy changed\n', stderr.getvalue())

    def test_default_setup_shares_home_once_including_its_scratch_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary).resolve()
            instance = host.Host(home / ".local/state/sandbox")
            def stop_after_plan(*args, **kwargs):
                if args[1] == "create":
                    raise InterruptedError("plan recorded")
            with patch.object(host.Path, "home", return_value=home), \
                    patch.object(host, "machines", return_value={}), \
                    patch.object(host, "command", side_effect=stop_after_plan):
                with self.assertRaisesRegex(InterruptedError, "plan recorded"):
                    instance.setup("sandbox-host")
            self.assertEqual([{"location": str(home), "mountPoint": str(home), "writable": True}],
                             instance.record()["shares"])
            new_repository = home / "src/new-repository"
            new_repository.mkdir(parents=True)
            self.assertEqual(new_repository, host.bind_source(instance.record(), new_repository, True))

    def test_default_setup_keeps_external_scratch_without_sharing_its_parent(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            home = root / "home"
            home.mkdir()
            instance = host.Host(root / "external-state")
            def stop_after_plan(*args, **kwargs):
                if args[1] == "create":
                    raise InterruptedError("plan recorded")
            with patch.object(host.Path, "home", return_value=home), \
                    patch.object(host, "machines", return_value={}), \
                    patch.object(host, "command", side_effect=stop_after_plan):
                with self.assertRaisesRegex(InterruptedError, "plan recorded"):
                    instance.setup("sandbox-host")
            self.assertEqual({str(home), str(instance.state / "scratch")},
                             {share["location"] for share in instance.record()["shares"]})
            with self.assertRaisesRegex(ValueError, "outside"):
                host.bind_source(instance.record(), instance.state)

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
