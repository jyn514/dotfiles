from __future__ import annotations

import importlib.util
import fcntl
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[3]
MODULE_PATH = ROOT / "tools" / "codex-sandbox" / "sandbox-proxies.py"
SPEC = importlib.util.spec_from_file_location("sandbox_proxies", MODULE_PATH)
assert SPEC and SPEC.loader
sandbox_proxies = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(sandbox_proxies)
from docker_runtime import Docker
import sandbox_runtime


class RecordedEffectTest(unittest.TestCase):
    def test_ambiguous_effect_is_durably_unknown(self) -> None:
        record = {"resource-status": {"container": "absent"}}
        observed = []
        def fail(): raise OSError("outcome unknown")
        with self.assertRaises(OSError):
            sandbox_proxies._recorded_effect(
                record, "container", lambda: observed.append(record["resource-status"]["container"]),
                threading.Event(), fail, "zulip")
        self.assertEqual(observed, ["intended", "unknown"])
        self.assertEqual(record["resource-status"]["container"], "unknown")

    def test_cancellation_after_effect_retains_created_recovery_authority(self) -> None:
        record = {"resource-status": {"container": "absent"}}
        cancelled = threading.Event()
        def create(): cancelled.set()
        with self.assertRaisesRegex(sandbox_proxies.ConfigError, "startup cancelled"):
            sandbox_proxies._recorded_effect(record, "container", lambda: None,
                                              cancelled, create, "zulip")
        self.assertEqual(record["resource-status"]["container"], "created")


class ZulipHardeningTest(unittest.TestCase):
    def snapshot(self):
        return {"Config": {"User": "501:20", "Entrypoint": None,
                           "Cmd": ["caddy", "run", "--config", "/etc/caddy/caddy.json"],
                           "Labels": {"dev.codex.service-role": "zulip-caddy"}},
                "HostConfig": {"NetworkMode": "zulip-app", "ReadonlyRootfs": True,
                               "Privileged": False, "CapAdd": ["CAP_NET_BIND_SERVICE"], "CapDrop": ["ALL"],
                               "SecurityOpt": ["no-new-privileges"], "PidsLimit": 64,
                               "Memory": 256 * 1024 * 1024, "NanoCpus": 1_000_000_000,
                               "Ulimits": [{"Name": "nofile", "Soft": 256, "Hard": 256}]}}

    def accepted(self, snapshot):
        return sandbox_proxies._zulip_container_hardened(
            snapshot, role="zulip-caddy", uid=501, gid=20, network="zulip-app",
            entrypoint=None, command=["caddy", "run", "--config", "/etc/caddy/caddy.json"])

    def test_accepts_exact_declared_hardening(self) -> None:
        self.assertTrue(self.accepted(self.snapshot()))

    def test_rejects_cap_privilege_and_nofile_tampering(self) -> None:
        for field, value in (("CapAdd", None), ("CapAdd", ["NET_ADMIN"]), ("Privileged", True),
                             ("Ulimits", [{"Name": "nofile", "Soft": 1024, "Hard": 1024}])):
            snapshot = self.snapshot(); snapshot["HostConfig"][field] = value
            with self.subTest(field=field): self.assertFalse(self.accepted(snapshot))

    def test_rejects_extra_or_changed_pair_mounts(self) -> None:
        socket = {"Destination": "/run/profile-helper", "Source": "/vol/socket", "RW": False,
                  "Type": "volume", "Name": "socket"}
        caddy = {"Mounts": [socket, {"Destination": "/etc/caddy/caddy.json", "Source": "/state/caddy.json",
                                     "RW": False, "Type": "bind", "Name": None}]}
        helper_socket = {**socket, "RW": True}
        helper = {"Mounts": [helper_socket, {"Destination": "/run/secrets/zuliprc", "Source": "/home/u/.zuliprc",
                                              "RW": False, "Type": "bind", "Name": None}]}
        check = lambda: sandbox_proxies._zulip_mounts_exact(
            caddy, helper, socket_name="socket", socket_source="/vol/socket",
            config_source="/state/caddy.json", credential_source="/home/u/.zuliprc")
        self.assertTrue(check())
        caddy["Mounts"].append({"Destination": "/tmp/extra", "Source": "/tmp/x", "RW": False,
                                "Type": "bind", "Name": None})
        self.assertFalse(check())
        caddy["Mounts"].pop(); helper["Mounts"][0]["RW"] = False
        self.assertFalse(check())

    def test_rejects_network_and_runtime_limit_tampering(self) -> None:
        for field, value in (("NetworkMode", "bridge"), ("ReadonlyRootfs", False),
                             ("PidsLimit", 65), ("Memory", 0), ("NanoCpus", 0)):
            snapshot = self.snapshot(); snapshot["HostConfig"][field] = value
            with self.subTest(field=field): self.assertFalse(self.accepted(snapshot))


class ManifestTest(unittest.TestCase):
    def test_launcher_metadata_is_reused_only_for_its_repository(self):
        paths = sandbox_proxies.git_metadata_paths(self.repo)
        identity = sandbox_proxies.repository_identity(self.repo)
        with mock.patch.object(sandbox_proxies, 'REPOSITORY_METADATA', None):
            sandbox_proxies.use_repository_metadata(self.repo, paths)
            with mock.patch.object(sandbox_proxies.subprocess, 'run') as run:
                self.assertEqual(sandbox_proxies.git_metadata_paths(self.repo), paths)
                self.assertEqual(sandbox_proxies.repository_identity(self.repo), identity)
                run.assert_not_called()
                other = self.repo / 'other'
                other.mkdir()
                run.side_effect = RuntimeError('discover other repository')
                with self.assertRaisesRegex(RuntimeError, 'discover other'):
                    sandbox_proxies.git_metadata_paths(other)

    def test_supplied_metadata_keeps_mount_delimiter_validation(self):
        bad = self.repo / 'bad,metadata'
        bad.mkdir()
        with self.assertRaisesRegex(sandbox_proxies.ConfigError, 'delimiter'):
            sandbox_proxies.use_repository_metadata(self.repo, (bad, bad))

    def test_empty_jj_git_root_cannot_select_the_callers_repository(self) -> None:
        workspace = self.repo / "workspace"
        workspace.mkdir()
        with mock.patch.object(sandbox_proxies.subprocess, "run", return_value=SimpleNamespace(stdout="")):
            with self.assertRaisesRegex(sandbox_proxies.ConfigError, "invalid Git metadata path"):
                sandbox_proxies.git_metadata_paths(workspace)

    def test_embedded_helper_keeps_the_callers_runtime(self):
        owner = mock.Mock()
        action = mock.Mock(return_value=7)
        args = SimpleNamespace(action='attach', function=action)
        with mock.patch.object(sandbox_proxies, 'OUTER_RUNTIME'), \
                mock.patch.object(sandbox_proxies, 'parse_args', return_value=args), \
                mock.patch.object(sandbox_proxies, 'image_runtime', side_effect=AssertionError('reinitialized')):
            self.assertEqual(sandbox_proxies.main([], runtime=owner), 7)
            self.assertIs(sandbox_proxies.OUTER_RUNTIME, owner)
            action.assert_called_once_with(args)

    def test_prepared_images_are_verified_without_rerunning_builders(self):
        with tempfile.TemporaryDirectory() as directory:
            prepared = Path(directory) / 'images.json'
            prepared.write_text(json.dumps({'example': 'image@sha256:prepared'}))
            owner = mock.Mock()
            owner.verify_builder_image.side_effect = lambda value: SimpleNamespace(reference=value)
            with mock.patch.object(sandbox_proxies, 'OUTER_RUNTIME', owner), mock.patch('subprocess.run') as run:
                images = sandbox_proxies.resolve_images(Path(directory), {'commands': {'example': {}}}, prepared)
                self.assertEqual(images, {'example': 'image@sha256:prepared'})
                owner.verify_builder_image.assert_called_once_with('image@sha256:prepared')
                run.assert_not_called()
                with self.assertRaisesRegex(sandbox_proxies.ConfigError, 'manifest'):
                    sandbox_proxies.resolve_images(Path(directory), {'commands': {}}, prepared)

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.repo = Path(self.temporary.name)
        self.home_patch = mock.patch.dict(os.environ, {"HOME": str(self.repo)})
        self.home_patch.start()
        subprocess.run(["git", "init", "--quiet", str(self.repo)], check=True)
        (self.repo / ".jj" / "repo").mkdir(parents=True)
        self.sandbox = self.repo / ".agents" / "sandbox"
        self.sandbox.mkdir(parents=True)
        self.container_repo = Path("/src/example")

    def tearDown(self) -> None:
        self.home_patch.stop()
        self.temporary.cleanup()

    def test_runtime_directory_uses_shared_home_when_xdg_runtime_is_elsewhere(self) -> None:
        with mock.patch.dict(os.environ, {"XDG_RUNTIME_DIR": str(self.repo / "unshared-run")}):
            runtime = sandbox_proxies.runtime_directory(self.repo)
        self.assertEqual(self.repo / ".cache" / "codex-sandbox-proxies" /
                         sandbox_proxies.repository_identity(self.repo), runtime)
        self.assertEqual(0o700, runtime.stat().st_mode & 0o777)

    def test_explicit_arguments_preserve_caller_argv_and_report_errors(self) -> None:
        output = self.repo / "snapshot.json"
        arguments = ["snapshot", "--repo", str(self.repo), "--output", str(output)]
        with mock.patch.object(sys, "argv", ["caller", "unrelated-argument"]):
            self.assertEqual(0, sandbox_proxies.main(arguments))
            self.assertEqual(
                {"version": 1, "capabilities": {
                    "host-editor": True, "zulip": True,
                    "nested-containers": False, "flower-r2": False, "agent-room": False,
                }, "commands": {}},
                json.loads(output.read_text()),
            )
            self.assertEqual(["caller", "unrelated-argument"], sys.argv)
            (self.sandbox / "proxy-commands.json").write_text("invalid JSON")
            with mock.patch("sys.stderr", new_callable=io.StringIO) as stderr:
                self.assertEqual(1, sandbox_proxies.main(arguments))
                self.assertIn("sandbox proxies:", stderr.getvalue())

    def write(self, commands: dict = None, **extra: object) -> None:
        manifest = {"version": 1, "commands": commands or {}, **extra}
        (self.sandbox / "proxy-commands.json").write_text(json.dumps(manifest), encoding="utf-8")

    @staticmethod
    def managed_proxy(name: str, image: str = "sha256:" + "0" * 64) -> dict:
        owner = (name.encode().hex() + "0" * 32)[:32]
        return {
            "name": name, "volume": f"shared-{name}", "container": f"shared-{name}",
            "image": image, "service-owner": owner,
            "implementation-identity": "sha256:" + "1" * 64,
            "state-schema": 1, "lifecycle-state": "ready",
            "identity-parameters": {"uid": 501, "gid": 20, "network": "none"},
            "resource-status": {"volume": "created", "container": "created", "forward": "absent"},
        }

    @staticmethod
    def pair_auth() -> dict:
        runtime = {"provider": "container"}
        return {
            "container": "codex-auth", "helper-container": "codex-auth-helper",
            "socket-volume": "codex-auth-socket", "key": "a.b.c",
            "image": "caddy@sha256:" + "1" * 64, "service-owner": "a" * 32,
            "implementation-identity": "sha256:" + "2" * 64,
            "helper-implementation": "sha256:" + "4" * 64,
            "caddy-image-chain": {"provenance": "caddy:2.11.4-alpine",
                "index_digest": "sha256:" + "5" * 64, "platform": "linux/amd64",
                "manifest_digest": "sha256:" + "1" * 64,
                "configuration_digest": "sha256:" + "6" * 64,
                "runtime_image_id": "sha256:" + "6" * 64},
            "configuration": {"path": "/state/caddy.json", "digest": "sha256:" + "7" * 64},
            "state-schema": 1, "lifecycle-state": "failed", "credential-domain": "codex",
            "network": "codex-application", "networks": {"agent-link": "codex-public-only",
                "application": "codex-application", "refresh": "codex-refresh"},
            "refresh-attachment": {"container": "codex-auth-helper", "network": "codex-refresh"},
            "network-owner": {"kind": "admitted-runtime-public-egress", "runtime": runtime},
            "endpoint": {"container": "codex-auth", "port": 8787},
            "credential-volume": {"kind": "bind", "target": "/var/lib/codex-auth",
                                  "identity": "sha256:" + "3" * 64, "lifetime": "shared-session"},
            "token-lifetime": "shared-session", "runtime-owner": runtime,
            "resource-status": {"caddy-container": "unknown", "helper-container": "unknown",
                "socket-volume": "unknown", "application-network": "unknown",
                "refresh-network": "unknown", "refresh-attachment": "unknown"},
        }

    def schema4(self, commands: dict[str, dict], *, services=None, helper=None) -> dict:
        policy = sandbox_proxies.serializable_manifest({"version": 1, "commands": commands})
        records = services if services is not None else {
            name: sandbox_proxies._service_record(name, self.managed_proxy(name), {"provider": "container"})
            for name in commands
        }
        return {
            "version": 4, "repository": sandbox_proxies.repository_identity(self.repo),
            "container_repository": str(self.container_repo),
            "runtime-owner": {"provider": "container"},
            "accepted": {"policy": policy, "source-present": True,
                         "broker-roles": (["codex-broker"] if "codex-broker" in records else []),
                         "images": {"agent": "agent", "helper": helper,
                                    "services": {name: value["container"]["image"] for name, value in records.items()}},
                         "image-bound-parameters": {"uid": 501, "gid": 20}},
            "services": records,
        }

    @staticmethod
    def command(**updates: object) -> dict:
        command = {
            "image-command": [".agents/sandbox/build-example"],
            "argv": ["example-proxy", "serve"],
            "workdir": ".",
            "network": False,
            "mounts": [],
        }
        command.update(updates)
        return command

    def test_accepts_version_one_manifest(self) -> None:
        self.write({"example": self.command()})
        manifest = sandbox_proxies.load_manifest(self.repo)
        self.assertEqual(["example-proxy", "serve"], manifest["commands"]["example"]["argv"])

    def test_default_services_and_explicit_opt_outs(self) -> None:
        for capabilities in ({}, {"host-editor": False}, {"zulip": False},
                             {"host-editor": False, "zulip": False}):
            with self.subTest(capabilities=capabilities):
                self.write(version=2, capabilities=capabilities)
                selected = sandbox_proxies.load_manifest(self.repo)["capabilities"]
                self.assertEqual({
                    "host-editor": True, "zulip": True,
                    "nested-containers": False, "flower-r2": False, "agent-room": False,
                    **capabilities,
                }, selected)

    def test_missing_sandbox_uses_default_services(self) -> None:
        self.sandbox.rmdir()
        selected = sandbox_proxies.load_optional_manifest(self.repo)["capabilities"]
        self.assertTrue(selected["host-editor"])
        self.assertTrue(selected["zulip"])

    def test_version_two_selects_capabilities_and_binds_bake_images(self) -> None:
        self.sandbox.joinpath("proxy-commands.json").write_text(json.dumps({
            "version": 2,
            "capabilities": {"host-editor": True, "flower-r2": False},
            "images": {
                "resolver": {"kind": "bake", "file": ".agents/sandbox/docker-bake.hcl"},
                "base": "base",
            },
            "commands": {"example": {
                **self.command(), "image": "example",
            }},
        }))
        data = json.loads(self.sandbox.joinpath("proxy-commands.json").read_text())
        data["commands"]["example"].pop("image-command")
        self.sandbox.joinpath("proxy-commands.json").write_text(json.dumps(data))

        manifest = sandbox_proxies.load_manifest(self.repo)

        self.assertTrue(manifest["capabilities"]["host-editor"])
        self.assertFalse(manifest["capabilities"]["nested-containers"])
        self.assertEqual("example", manifest["commands"]["example"]["image-target"])
        snapshot = self.repo / "snapshot.json"
        sandbox_proxies.snapshot_main(SimpleNamespace(
            repo=str(self.repo), output=str(snapshot), jj_image_command=None,
        ))
        accepted = sandbox_proxies.load_manifest_file(snapshot)
        self.assertEqual("example", accepted["commands"]["example"]["image-target"])

    def test_conventional_bake_file_supplies_policy_without_manifest(self) -> None:
        bake = self.sandbox / "docker-bake.hcl"
        bake.write_text('target "base" { context = ".agents/sandbox/base" }\n')
        output = self.repo / "snapshot.json"
        arguments = ["snapshot", "--repo", str(self.repo), "--output", str(output)]
        self.assertEqual(0, sandbox_proxies.main(arguments))
        manifest = json.loads(output.read_text())
        self.assertEqual(1, manifest["version"])
        self.assertEqual({}, manifest["commands"])
        self.assertEqual("base", manifest["images"]["base"])
        self.assertEqual(
            {"kind": "bake", "file": ".agents/sandbox/docker-bake.hcl"},
            manifest["images"]["resolver"],
        )

    def test_bake_resolver_defaults_to_conventional_file(self) -> None:
        self.sandbox.joinpath("proxy-commands.json").write_text(json.dumps({
            "version": 2,
            "images": {"resolver": {"kind": "bake"}, "base": "base"},
        }))
        manifest = sandbox_proxies.load_manifest(self.repo)
        self.assertEqual(
            {"kind": "bake", "file": ".agents/sandbox/docker-bake.hcl"},
            manifest["images"]["resolver"],
        )

    def test_conventional_bake_file_remains_protected_configuration(self) -> None:
        bake = self.sandbox / "docker-bake.hcl"
        bake.symlink_to(self.repo / "outside.hcl")
        with self.assertRaisesRegex(sandbox_proxies.ConfigError, "symlink"):
            sandbox_proxies.load_optional_manifest(self.repo)

    def test_version_two_rejects_undeclared_capability_and_command_without_resolver(self) -> None:
        path = self.sandbox / "proxy-commands.json"
        path.write_text(json.dumps({"version": 2, "capabilities": {"shell": True}}))
        with self.assertRaisesRegex(sandbox_proxies.ConfigError, "capabilities"):
            sandbox_proxies.load_manifest(self.repo)
        command = self.command()
        command.pop("image-command")
        command["image"] = "example"
        path.write_text(json.dumps({"version": 2, "commands": {"example": command}}))
        with self.assertRaisesRegex(sandbox_proxies.ConfigError, "explicit image resolver"):
            sandbox_proxies.load_manifest(self.repo)

    def test_docker_prepares_once_and_revalidates_serialized_references(self) -> None:
        owner = mock.Mock(provider='lima-docker')
        images = {'one': 'first@sha256:one', 'two': 'second@sha256:two'}
        preparation = mock.Mock(return_value=SimpleNamespace(proxies=images))
        owner.verify_builder_image.side_effect = lambda value: SimpleNamespace(reference=value)
        manifest = {'commands': {'one': {'image-target': 'first'}, 'two': {'image-target': 'second'}}}
        with mock.patch.object(sandbox_proxies, 'OUTER_RUNTIME', owner), \
                mock.patch('image_resolver.prepare_launch_images', preparation):
            self.assertEqual(sandbox_proxies.resolve_images(self.repo, manifest), images)
            preparation.assert_called_once_with(owner, self.repo, manifest['commands'])
            owner.verify_builder_image.assert_not_called()
            prepared = self.repo / 'images.json'
            prepared.write_text(json.dumps(images))
            preparation.reset_mock()
            self.assertEqual(sandbox_proxies.resolve_images(self.repo, manifest, prepared), images)
            self.assertEqual(owner.verify_builder_image.call_count, 2)
            preparation.assert_not_called()
            owner.verify_builder_image.side_effect = ValueError('engine changed')
            with self.assertRaisesRegex(ValueError, 'engine changed'):
                sandbox_proxies.resolve_images(self.repo, manifest, prepared)

    def test_bake_target_survives_manifest_normalization(self):
        command = self.command(**{'image-target': 'bb-bug'})
        for legacy in (True, False):
            if not legacy:
                command.pop('image-command')
            self.write({'bug': command})
            manifest = sandbox_proxies.serializable_manifest(sandbox_proxies.load_manifest(self.repo))
            self.assertEqual(manifest['commands']['bug']['image-target'], 'bb-bug')
        command['image-target'] = '../outside'
        self.write({'bug': command})
        with self.assertRaisesRegex(sandbox_proxies.ConfigError, 'image-target'):
            sandbox_proxies.load_manifest(self.repo)

    def test_accepts_proxy_only_writable_repository_mount(self) -> None:
        self.write({"example": self.command(mounts=[{
            "source": ".", "target": ".", "proxy": "read-write",
        }])})
        mount = sandbox_proxies.load_manifest(self.repo)["commands"]["example"]["mounts"][0]
        self.assertEqual("read-write", mount["proxy"])

    def test_git_builtin_mount_resolves_non_colocated_jj_metadata(self) -> None:
        repo = Path(self.temporary.name + "-noncolocated")
        self.addCleanup(shutil.rmtree, repo, True)
        subprocess.run(["jj", "git", "init", "--no-colocate", str(repo)],
                       check=True, capture_output=True, text=True)
        sandbox = repo / ".agents" / "sandbox"
        sandbox.mkdir(parents=True)
        declaration = {"builtin": "git", "proxy": "read-write", "agent": "read-only"}
        (sandbox / "proxy-commands.json").write_text(json.dumps({
            "version": 1, "commands": {"bug": self.command(mounts=[declaration])},
        }), encoding="utf-8")

        self.assertFalse((repo / ".git").exists())
        command = sandbox_proxies.load_manifest(repo)["commands"]["bug"]
        self.assertEqual(declaration, command["mounts"][0])
        self.assertEqual(declaration, sandbox_proxies.serializable_manifest({
            "version": 1, "commands": {"bug": command},
        })["commands"]["bug"]["mounts"][0])
        git_dir = sandbox_proxies.git_metadata_paths(repo)[1]
        target = sandbox_proxies.metadata_container_path(repo, git_dir, self.container_repo)
        arguments = sandbox_proxies.proxy_repository_mount_args(
            repo, self.container_repo, "bug", command,
        )
        self.assertIn(f"type=bind,src={git_dir},dst={target}", arguments)
        self.assertNotIn(f"src={repo / '.git'}", " ".join(arguments))
        self.assertEqual(
            ["--env", f"SANDBOX_GIT_DIR={target}"],
            sandbox_proxies.proxy_git_environment_args(repo, self.container_repo, command),
        )

    def test_git_builtin_rejects_duplicate_or_unsafe_declarations(self) -> None:
        valid = {"builtin": "git", "proxy": "read-write", "agent": "read-only"}
        invalid = (
            ([valid, valid], "duplicate"),
            ([{**valid, "source": ".git"}], "built-in fields"),
            ([{**valid, "agent": "read-write"}], "access mode"),
            ([{**valid, "agent": "hidden"}], "access mode"),
            ([{**valid, "builtin": "unknown"}], "built-in fields"),
        )
        for mounts, message in invalid:
            with self.subTest(mounts=mounts):
                self.write({"bug": self.command(mounts=mounts)})
                with self.assertRaisesRegex(sandbox_proxies.ConfigError, message):
                    sandbox_proxies.load_manifest(self.repo)

    def test_git_builtin_maps_external_backing_for_linked_jj_workspace(self) -> None:
        main = self.repo / "main"
        workspace = main / ".workspaces" / "other"
        subprocess.run(["jj", "git", "init", "--colocate", str(main)],
                       check=True, capture_output=True, text=True)
        workspace.parent.mkdir()
        result = subprocess.run(
            ["jj", "-R", str(main), "workspace", "add", "--no-colocate", str(workspace)],
            capture_output=True, text=True,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        command = self.command(mounts=[{
            "builtin": "git", "proxy": "read-write", "agent": "read-only",
        }])
        container_repo = Path("/src/main/.workspaces/other")

        self.assertFalse((workspace / ".git").exists())
        arguments = sandbox_proxies.proxy_repository_mount_args(
            workspace, container_repo, "bug", command,
        )
        backing = (main / ".git").resolve()
        self.assertIn(f"type=bind,src={backing},dst=/src/main/.git", arguments)
        self.assertEqual(
            ["--env", "SANDBOX_GIT_DIR=/src/main/.git"],
            sandbox_proxies.proxy_git_environment_args(workspace, container_repo, command),
        )

    def test_git_builtin_read_only_proxy_mount(self) -> None:
        self.write({"bug": self.command(mounts=[{
            "builtin": "git", "proxy": "read-only", "agent": "read-only",
        }])})
        command = sandbox_proxies.load_manifest(self.repo)["commands"]["bug"]
        arguments = sandbox_proxies.proxy_repository_mount_args(
            self.repo, self.container_repo, "bug", command,
        )
        self.assertIn(
            f"type=bind,src={(self.repo / '.git').resolve()},dst=/src/example/.git,readonly",
            arguments,
        )

    def test_git_builtin_rejects_colliding_explicit_mount_target(self) -> None:
        self.write({"bug": self.command(mounts=[
            {"builtin": "git", "proxy": "read-write", "agent": "read-only"},
            {"source": ".git", "target": ".git", "proxy": "read-write"},
        ])})
        command = sandbox_proxies.load_manifest(self.repo)["commands"]["bug"]
        with self.assertRaisesRegex(sandbox_proxies.ConfigError, "duplicate container mount destination"):
            sandbox_proxies.proxy_repository_mount_args(
                self.repo, self.container_repo, "bug", command,
            )

    def test_generates_writable_repository_when_root_override_is_declared(self) -> None:
        self.write({"jj": self.command(mounts=[
            {"source": ".", "target": ".", "proxy": "read-write"},
        ])})
        command = sandbox_proxies.load_manifest(self.repo)["commands"]["jj"]
        arguments = sandbox_proxies.proxy_repository_mount_args(
            self.repo, self.container_repo, "jj", command,
        )
        mounts = arguments[1::2]
        self.assertIn(
            f"type=bind,src={self.repo.resolve()},dst=/src/example,bind-nonrecursive=true",
            mounts,
        )
        self.assertNotIn(
            f"type=bind,src={self.repo.resolve()},dst=/src/example,readonly,bind-nonrecursive=true",
            mounts,
        )
        self.assertIn(
            f"type=bind,src={(self.repo / '.git').resolve()},dst=/src/example/.git",
            mounts,
        )
        self.assertIn(
            f"type=bind,src={(self.repo / '.jj/repo').resolve()},dst=/src/example/.jj/repo",
            mounts,
        )

    def test_linked_worktree_keeps_repository_at_agent_path(self) -> None:
        main = self.repo
        worktree = Path(self.temporary.name + "-worktree")
        self.addCleanup(shutil.rmtree, worktree, True)
        (main / "tracked").write_text("tracked\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(main), "add", "tracked"], check=True)
        subprocess.run([
            "git", "-C", str(main), "-c", "user.name=Test", "-c", "user.email=test@example.com",
            "-c", "core.hooksPath=",
            "commit", "--quiet", "-m", "initial",
        ], check=True)
        subprocess.run(["git", "-C", str(main), "worktree", "add", "--quiet", str(worktree)], check=True)
        (worktree / ".jj" / "repo").mkdir(parents=True)
        command = self.command(mounts=[{"source": ".", "target": ".", "proxy": "read-write"}])
        arguments = sandbox_proxies.proxy_repository_mount_args(
            worktree, self.container_repo, "jj", command,
        )
        self.assertIn(
            f"type=bind,src={worktree.resolve()},dst=/src/example,bind-nonrecursive=true",
            arguments,
        )
        common_dir = sandbox_proxies.git_metadata_paths(worktree)[1]
        target = sandbox_proxies.metadata_container_path(
            worktree, common_dir, self.container_repo,
        )
        self.assertIn(f"type=bind,src={common_dir},dst={target}", arguments)

    def test_nested_repository_allows_sibling_metadata_beneath_source_root(self) -> None:
        host_root = self.repo / "host-source"
        nested_repository = host_root / "team" / "project"
        sibling = host_root / "shared"
        nested_repository.mkdir(parents=True)
        sibling.mkdir()
        self.assertEqual(
            Path("/src/shared"),
            sandbox_proxies.metadata_container_path(
                nested_repository, sibling, Path("/src/team/project"),
            ),
        )

    def test_external_jj_repository_pointer_mounts_only_metadata(self) -> None:
        external = Path(self.temporary.name + "-jj-repo")
        external.mkdir()
        self.addCleanup(shutil.rmtree, external, True)
        shutil.rmtree(self.repo / ".jj" / "repo")
        relative = os.path.relpath(external, self.repo / ".jj")
        (self.repo / ".jj" / "repo").write_text(relative + "\n", encoding="utf-8")
        command = self.command(mounts=[{"source": ".", "target": ".", "proxy": "read-write"}])
        arguments = sandbox_proxies.proxy_repository_mount_args(
            self.repo, self.container_repo, "jj", command,
        )
        self.assertIn(
            f"type=bind,src={self.repo.resolve()},dst=/src/example,bind-nonrecursive=true",
            arguments,
        )
        target = sandbox_proxies.metadata_container_path(
            self.repo, external, self.container_repo,
        )
        self.assertIn(f"type=bind,src={external.resolve()},dst={target}", arguments)
        self.assertNotIn(f"src={self.repo.parent},dst=/src/example", " ".join(arguments))

    def test_rejects_agent_authority_on_repository_root(self) -> None:
        self.write({"example": self.command(mounts=[{
            "source": ".", "target": ".", "proxy": "read-write", "agent": "read-only",
        }])})
        with self.assertRaisesRegex(sandbox_proxies.ConfigError, "proxy-only"):
            sandbox_proxies.load_manifest(self.repo)

    def test_rejects_unknown_fields(self) -> None:
        self.write({"example": self.command(surprise=True)})
        with self.assertRaisesRegex(sandbox_proxies.ConfigError, "missing or unknown"):
            sandbox_proxies.load_manifest(self.repo)

    def test_rejects_duplicate_json_fields(self) -> None:
        (self.sandbox / "proxy-commands.json").write_text(
            '{"version":1,"version":1,"commands":{}}', encoding="utf-8"
        )
        with self.assertRaisesRegex(sandbox_proxies.ConfigError, "duplicate JSON field"):
            sandbox_proxies.load_manifest(self.repo)

    def test_rejects_escaping_and_duplicate_targets(self) -> None:
        mounts = [
            {"source": "state", "target": "../outside", "proxy": "read-write"},
        ]
        self.write({"example": self.command(mounts=mounts)})
        with self.assertRaisesRegex(sandbox_proxies.ConfigError, "beneath"):
            sandbox_proxies.load_manifest(self.repo)

        mounts[0]["target"] = "state"
        mounts.append({"source": "other", "target": "state", "agent": "hidden"})
        self.write({"example": self.command(mounts=mounts)})
        with self.assertRaisesRegex(sandbox_proxies.ConfigError, "duplicate"):
            sandbox_proxies.load_manifest(self.repo)

    def test_omitted_modes_inherit_existing_views(self) -> None:
        self.write({"example": self.command(mounts=[{"source": ".git", "target": ".git"}])})
        mount = sandbox_proxies.load_manifest(self.repo)["commands"]["example"]["mounts"][0]
        self.assertIsNone(mount["proxy"])
        self.assertIsNone(mount["agent"])

    def test_rejects_writable_agent_mount_below_protected_metadata(self) -> None:
        self.write({"example": self.command(mounts=[{
            "source": ".git/objects", "target": ".git/objects", "agent": "read-write",
        }])})
        with self.assertRaisesRegex(sandbox_proxies.ConfigError, "protected repository metadata"):
            sandbox_proxies.load_manifest(self.repo)

    def test_rejects_intermediate_symlink_in_mount_path(self) -> None:
        outside = self.repo / "outside"
        outside.mkdir()
        state = self.repo / "state"
        state.mkdir()
        (state / "link").symlink_to(outside)
        with self.assertRaisesRegex(sandbox_proxies.ConfigError, "symlinked component"):
            sandbox_proxies.checked_repository_path(
                self.repo, "state/link", "command example mount source"
            )

    def test_rejects_symlink_and_hard_link_in_protected_configuration(self) -> None:
        self.write()
        target = self.sandbox / "support"
        target.write_text("support", encoding="utf-8")
        (self.sandbox / "linked").symlink_to(target)
        with self.assertRaisesRegex(sandbox_proxies.ConfigError, "symlink"):
            sandbox_proxies.load_manifest(self.repo)
        (self.sandbox / "linked").unlink()
        os.link(target, self.sandbox / "hard-linked")
        with self.assertRaisesRegex(sandbox_proxies.ConfigError, "hard link"):
            sandbox_proxies.load_manifest(self.repo)

    def test_agent_arguments_protect_config_and_declared_paths(self) -> None:
        self.write({"example": self.command(mounts=[
            {"source": "state", "target": "state", "agent": "read-only"},
            {"source": "secret", "target": "secret", "agent": "hidden"},
            {"builtin": "git", "proxy": "read-write", "agent": "read-only"},
        ])})
        output = self.repo / "args"
        state = self.repo / "state"
        state.write_text(json.dumps({"proxies": [{
            "name": "example", "volume": "shared-example",
            "session-token": "secret.not.for-agent",
        }]}), encoding="utf-8")
        args = type("Args", (), {
            "repo": str(self.repo), "container_repo": str(self.container_repo),
            "state": str(state), "output": str(output),
            "manifest": str(self.sandbox / "proxy-commands.json"),
        })
        sandbox_proxies.agent_args_main(args)
        generated = output.read_text(encoding="utf-8")
        self.assertIn("SANDBOX_PROXY_DIR=/run/sandbox-proxies", generated)
        self.assertIn(f"JJ_PROXY_REPO={self.container_repo}", generated)
        self.assertIn("src=shared-example,dst=/run/sandbox-proxies/example,readonly", generated)
        self.assertIn("dst=/run/sandbox-proxies/example,readonly", generated)
        self.assertIn("dst=/src/example/state,readonly", generated)
        self.assertIn("/src/example/secret:ro,noexec", generated)
        self.assertNotIn("dst=/src,readonly", generated)
        self.assertNotIn("src=" + str(self.repo / ".git"), generated)
        self.assertNotIn("secret.not.for-agent", generated)

    def test_finalize_publishes_before_generating_agent_arguments(self) -> None:
        args = object()
        calls = []
        with mock.patch.object(
            sandbox_proxies, "publish_main", side_effect=lambda value: calls.append(("publish", value)),
        ), mock.patch.object(
            sandbox_proxies, "agent_args_main", side_effect=lambda value: calls.append(("args", value)) or 0,
        ):
            self.assertEqual(0, sandbox_proxies.finalize_main(args))
        self.assertEqual([("publish", args), ("args", args)], calls)

    def test_publication_checks_proxies_concurrently_before_writing_metadata(self) -> None:
        state = self.repo / "state.json"
        images = {name: "sha256:" + "0" * 64 for name in ("first", "second")}
        state.write_text(json.dumps({"runtime": {"provider": "container"},
            "proxies": [self.managed_proxy(name, image) for name, image in images.items()],
            "accepted": {"source-present": True, "agent-image": "agent", "helper-image": None,
                         "parameters": {"uid": 501, "gid": 20}, "proxy-images": images}}))
        manifest = self.repo / "manifest.json"
        manifest.write_text(json.dumps({"version": 1, "commands": {name: self.command() for name in images}}))
        args = SimpleNamespace(repo=str(self.repo), state=str(state), manifest=str(manifest),
                               container_repo=str(self.container_repo))
        rendezvous = threading.Barrier(2)

        def validate(*_args, **_kwargs):
            self.assertFalse((self.repo / "session.json").exists())
            rendezvous.wait(timeout=2)

        with mock.patch.object(sandbox_proxies, "runtime_directory", return_value=self.repo), \
                mock.patch.object(sandbox_proxies, "validate_live_proxy", side_effect=validate):
            self.assertEqual(0, sandbox_proxies.publish_main(args))
        metadata = json.loads((self.repo / "session.json").read_text())
        self.assertEqual(4, metadata["version"])
        self.assertEqual({"first", "second"}, set(metadata["services"]))
        self.assertEqual(0o600, metadata_path_mode := ((self.repo / "session.json").stat().st_mode & 0o777))

    def test_failed_publication_waits_for_other_checks_and_keeps_old_metadata(self) -> None:
        state = self.repo / "state.json"
        images = {name: "sha256:" + "0" * 64 for name in ("bad", "slow")}
        state.write_text(json.dumps({"runtime": {"provider": "container"},
            "proxies": [self.managed_proxy(name, image) for name, image in images.items()],
            "accepted": {"source-present": True, "agent-image": "agent", "helper-image": None,
                         "parameters": {"uid": 501, "gid": 20}, "proxy-images": images}}))
        manifest = self.repo / "manifest.json"
        manifest.write_text(json.dumps({"version": 1, "commands": {name: self.command() for name in images}}))
        published = self.repo / "session.json"
        published.write_text("previous metadata")
        args = SimpleNamespace(repo=str(self.repo), state=str(state), manifest=str(manifest),
                               container_repo=str(self.container_repo))
        started, failed, release, finished = (threading.Event() for _ in range(4))

        def validate(_owner, proxy, *_args, **_kwargs):
            if proxy["name"] == "bad":
                self.assertTrue(started.wait(2))
                failed.set()
                raise sandbox_proxies.ConfigError("wrong identity")
            started.set()
            self.assertTrue(release.wait(2))
            finished.set()

        with mock.patch.object(sandbox_proxies, "runtime_directory", return_value=self.repo), \
                mock.patch.object(sandbox_proxies, "validate_live_proxy", side_effect=validate), \
                ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(sandbox_proxies.publish_main, args)
            try:
                self.assertTrue(failed.wait(2))
                self.assertFalse(future.done())
            finally:
                release.set()
            with self.assertRaisesRegex(sandbox_proxies.ConfigError, "wrong identity"):
                future.result(timeout=2)
        self.assertTrue(finished.is_set())
        self.assertEqual("previous metadata", published.read_text())

    def test_local_router_accepts_option_separator(self) -> None:
        self.write({"example": self.command()})
        stale = sandbox_proxies.runtime_directory(self.repo) / "session.json"
        stale.write_text("{}", encoding="utf-8")
        args = type("Args", (), {
            "repo": str(self.repo), "command": "example", "wait": 0.1,
            "local": ["--", "/bin/sh", "-c", "exit 7"],
        })
        self.assertEqual(7, sandbox_proxies.route_main(args))
        self.assertTrue(stale.exists(), "local fallback must preserve the recovery record")

    def test_local_router_accepts_trusted_zulip_without_repository_manifest(self) -> None:
        self.write()
        args = type("Args", (), {
            "repo": str(self.repo), "command": "zulip", "wait": 0.1,
            "local": ["--", "/bin/sh", "-c", "exit 7"],
        })
        self.assertEqual(7, sandbox_proxies.route_main(args))

    def test_active_session_zulip_never_falls_back_without_endpoint_authority(self) -> None:
        self.write()
        runtime = sandbox_proxies.runtime_directory(self.repo)
        (runtime / "session.json").write_text(json.dumps({
            "version": 1,
            "repository": sandbox_proxies.repository_identity(self.repo),
            "commands": {}, "state": {"proxies": []},
            "manifest": {"version": 1, "commands": {}},
        }), encoding="utf-8")
        (runtime / "session.json").chmod(0o600)
        args = type("Args", (), {
            "repo": str(self.repo), "command": "zulip", "wait": 0.1,
            "local": ["--", "/bin/sh", "-c", "exit 7"],
        })
        with (runtime / "session.lock").open("a+b") as lock:
            fcntl.flock(lock, fcntl.LOCK_SH)
            with self.assertRaisesRegex(sandbox_proxies.ConfigError, "schema-4 authority"):
                sandbox_proxies.route_main(args)

    def test_snapshot_is_independent_of_later_manifest_edits(self) -> None:
        self.write({"example": self.command()})
        snapshot = self.repo / "snapshot"
        args = type("Args", (), {
            "repo": str(self.repo), "output": str(snapshot), "jj_image_command": None,
        })
        sandbox_proxies.snapshot_main(args)
        self.write()
        self.assertIn("example", sandbox_proxies.load_manifest_file(snapshot)["commands"])

    def test_snapshot_adds_trusted_jj_without_local_manifest(self) -> None:
        builder = self.repo / "trusted-jj-image"
        builder.write_text("#!/bin/sh\n", encoding="utf-8")
        builder.chmod(0o700)
        snapshot = self.repo / "snapshot"
        args = type("Args", (), {
            "repo": str(self.repo), "output": str(snapshot),
            "jj_image_command": str(builder.resolve()),
        })
        sandbox_proxies.snapshot_main(args)
        command = sandbox_proxies.load_manifest_file(snapshot)["commands"]["jj"]
        self.assertEqual([str(builder.resolve())], command["image-command"])
        self.assertEqual("read-write", command["mounts"][0]["proxy"])

    def test_snapshot_adds_trusted_zulip_with_secure_credentials(self) -> None:
        builder = self.repo / "trusted-zulip-image"
        builder.write_text("#!/bin/sh\n", encoding="utf-8")
        builder.chmod(0o700)
        zuliprc = self.repo / "zuliprc"
        zuliprc.write_text("[api]\nkey=secret\n", encoding="utf-8")
        zuliprc.chmod(0o600)
        snapshot = self.repo / "snapshot"
        args = type("Args", (), {
            "repo": str(self.repo), "output": str(snapshot), "jj_image_command": None,
            "zulip_image_command": str(builder.resolve()), "zuliprc": str(zuliprc),
        })
        sandbox_proxies.snapshot_main(args)
        command = sandbox_proxies.load_manifest_file(snapshot)["commands"]["zulip"]
        self.assertEqual([str(builder.resolve())], command["image-command"])
        self.assertTrue(command["network"])
        self.assertEqual([], command["mounts"])

    def test_zulip_opt_out_skips_credentials_and_builder(self) -> None:
        self.write(version=2, capabilities={"zulip": False})
        snapshot = self.repo / "snapshot"
        args = SimpleNamespace(
            repo=str(self.repo), output=str(snapshot), jj_image_command=None,
            zulip_image_command=str(self.repo / "missing-builder"),
            zuliprc=str(self.repo / "missing-credentials"),
        )
        sandbox_proxies.snapshot_main(args)
        policy = sandbox_proxies.load_manifest_file(snapshot)
        self.assertNotIn("zulip", policy["commands"])
        self.assertFalse(policy["capabilities"]["zulip"])
        self.write(version=2)
        self.assertFalse(sandbox_proxies.load_manifest_file(snapshot)["capabilities"]["zulip"])

    def test_zulip_name_is_reserved_even_when_disabled(self) -> None:
        self.write({"zulip": self.command()}, capabilities={"zulip": False})
        args = SimpleNamespace(
            repo=str(self.repo), output=str(self.repo / "snapshot"), jj_image_command=None,
        )
        with self.assertRaisesRegex(sandbox_proxies.ConfigError, "override trusted command: zulip"):
            sandbox_proxies.snapshot_main(args)

    def test_rejects_insecure_zulip_credentials(self) -> None:
        zuliprc = self.repo / "zuliprc"
        zuliprc.write_text("secret", encoding="utf-8")
        zuliprc.chmod(0o644)
        with self.assertRaisesRegex(sandbox_proxies.ConfigError, "mode 0600"):
            sandbox_proxies.zuliprc_mount_args(zuliprc)

    def test_mounts_zulip_credentials_only_in_proxy(self) -> None:
        zuliprc = self.repo / "zuliprc"
        zuliprc.write_text("secret", encoding="utf-8")
        zuliprc.chmod(0o600)
        arguments = sandbox_proxies.zuliprc_mount_args(zuliprc)
        self.assertEqual("--mount", arguments[0])
        self.assertIn(f"src={zuliprc.resolve()},dst=/run/secrets/zuliprc,readonly", arguments[1])

    def test_proxy_readiness_timeout_reports_forwarder_error(self) -> None:
        state_path = self.repo / "state"
        args = type("Args", (), {
            "prefix": "test", "state": str(state_path), "network": "sandbox",
            "container_repo": str(self.container_repo), "zuliprc": None,
        })
        command = self.command()
        image = "sha256:" + "0" * 64
        not_ready = subprocess.CompletedProcess(
            [], 1, stderr="usage: example-proxy serve\n",
        )
        running = subprocess.CompletedProcess([], 0, stdout="true\n")

        with mock.patch.object(sandbox_proxies, "_docker", return_value=running), \
                mock.patch.object(sandbox_proxies.subprocess, "run", return_value=not_ready), \
                mock.patch.object(sandbox_proxies, "proxy_logs", return_value=""), \
                mock.patch.object(sandbox_proxies.time, "monotonic", side_effect=[0, 0, 11]), \
                mock.patch.object(sandbox_proxies.time, "sleep"):
            with self.assertRaisesRegex(
                sandbox_proxies.ConfigError,
                "proxy example did not become ready:\\nusage: example-proxy serve",
            ):
                sandbox_proxies.start_one_proxy(
                    args, self.repo, "identity", {"example": image},
                    {"proxies": []}, mock.MagicMock(), "example", command,
                )

    def test_zulip_profile_uses_distinct_application_network_and_fixed_routes(self) -> None:
        config = json.loads(sandbox_proxies.generate_caddy_config(
            "zulip", "chat.example.com", token="a.b.c"))
        routes = config["apps"]["http"]["servers"]["egress"]["routes"]
        self.assertIn("/api/v1/messages", routes[1]["match"][0]["expression"])
        self.assertIn("/api/v1/streams", routes[1]["match"][0]["expression"])
        self.assertIn("/api/v1/users/me/", routes[1]["match"][0]["expression"])
        self.assertEqual(routes[-1]["handle"][0]["status_code"], 404)
        self.assertEqual("test-zulip-application", "test" + "-zulip-application")

    def test_snapshot_rejects_optional_symlinked_sandbox_directory(self) -> None:
        self.sandbox.rmdir()
        self.sandbox.symlink_to(self.repo / "outside")
        (self.repo / "outside").mkdir()
        args = type("Args", (), {
            "repo": str(self.repo), "output": str(self.repo / "snapshot"),
            "jj_image_command": None,
        })
        with self.assertRaisesRegex(sandbox_proxies.ConfigError, "symlinked or invalid"):
            sandbox_proxies.snapshot_main(args)

    def test_snapshot_rejects_dangling_manifest_symlink(self) -> None:
        (self.sandbox / "proxy-commands.json").symlink_to(self.repo / "missing")
        args = type("Args", (), {
            "repo": str(self.repo), "output": str(self.repo / "snapshot"),
            "jj_image_command": None,
        })
        with self.assertRaisesRegex(sandbox_proxies.ConfigError, "must not be symlinked"):
            sandbox_proxies.snapshot_main(args)

    def test_snapshot_rejects_local_override_of_trusted_jj(self) -> None:
        self.write({"jj": self.command()})
        builder = self.repo / "trusted-jj-image"
        builder.write_text("#!/bin/sh\n", encoding="utf-8")
        builder.chmod(0o700)
        args = type("Args", (), {
            "repo": str(self.repo), "output": str(self.repo / "snapshot"),
            "jj_image_command": str(builder.resolve()),
        })
        with self.assertRaisesRegex(sandbox_proxies.ConfigError, "may not override"):
            sandbox_proxies.snapshot_main(args)

    def test_atomic_write_interruption_preserves_previous_session(self) -> None:
        path = self.repo / "session.json"
        path.write_text("previous")
        with mock.patch.object(sandbox_proxies.os, "replace", side_effect=OSError("interrupted")):
            with self.assertRaisesRegex(OSError, "interrupted"):
                sandbox_proxies.write_atomic(path, "partial")
        self.assertEqual("previous", path.read_text())
        self.assertEqual([], list(self.repo.glob(".session.json.*")))

    def test_reset_final_holder_cleans_schema4_and_removes_publication(self) -> None:
        self.write({"example": self.command()})
        runtime = sandbox_proxies.runtime_directory(self.repo)
        metadata_path = runtime / "session.json"
        metadata = self.schema4({"example": self.command()})
        metadata_path.write_text(json.dumps(metadata))
        metadata_path.chmod(0o600)
        args = SimpleNamespace(repo=str(self.repo))
        with mock.patch.object(sandbox_proxies, "stop_state") as stop:
            self.assertEqual(0, sandbox_proxies.reset_main(args))
        self.assertEqual(["example"], [p["name"] for p in stop.call_args.args[0]["proxies"]])
        self.assertFalse(metadata_path.exists())

    def test_reset_stops_and_forgets_persistent_session(self) -> None:
        self.write()
        runtime = sandbox_proxies.runtime_directory(self.repo)
        metadata = runtime / "session.json"
        state = {"proxies": []}
        metadata.write_text(json.dumps({
            "version": 1,
            "repository": sandbox_proxies.repository_identity(self.repo),
            "state": state,
        }), encoding="utf-8")
        args = type("Args", (), {"repo": str(self.repo)})
        with mock.patch.object(sandbox_proxies, "stop_state") as stop:
            self.assertEqual(0, sandbox_proxies.reset_main(args))
        stop.assert_called_once_with(state)
        self.assertFalse(metadata.exists())

    def test_attach_reuses_published_proxy_state_and_manifest(self) -> None:
        self.write({"example": self.command()})
        runtime = sandbox_proxies.runtime_directory(self.repo)
        commands = sandbox_proxies.load_manifest(self.repo)["commands"]
        metadata = self.schema4(commands)
        shared_state = sandbox_proxies.session_state(metadata)
        shared_manifest = metadata["accepted"]["policy"]
        (runtime / "session.json").write_text(json.dumps(metadata), encoding="utf-8")
        (runtime / "session.json").chmod(0o600)
        state = self.repo / "attached-state"
        manifest = self.repo / "attached-manifest"
        manifest.write_text("checkout policy must not be read", encoding="utf-8")
        args = type("Args", (), {
            "repo": str(self.repo), "container_repo": str(self.container_repo),
            "shared": True, "state": str(state), "manifest": str(manifest),
            "uid": 501, "gid": 20, "agent_image": "agent", "helper_image": None,
        })
        owner = mock.Mock(provider="container")
        owner.builder_image.side_effect = lambda image: "builder:" + image
        owner.inspect_image.return_value = "inspected-helper"
        owner.verify_builder_image.return_value = "inspected-helper"
        owner.container_matches_image.return_value = True
        with mock.patch.object(sandbox_proxies, "OUTER_RUNTIME", owner), \
                mock.patch.object(sandbox_proxies, "runtime_identity", return_value=shared_state["runtime"]), \
                mock.patch.object(sandbox_proxies, "start_main") as start, \
                mock.patch.object(sandbox_proxies, "publish_main") as publish, \
                mock.patch.object(sandbox_proxies, "resolve_images") as resolve, \
                mock.patch.object(sandbox_proxies, "validate_live_proxy"), \
                mock.patch.object(sandbox_proxies, "containers_running", return_value=True):
            self.assertEqual(0, sandbox_proxies.attach_main(args))
        start.assert_not_called()
        publish.assert_not_called()
        resolve.assert_not_called()
        self.assertEqual(shared_state, json.loads(state.read_text(encoding="utf-8")))
        self.assertEqual(shared_manifest, json.loads(manifest.read_text(encoding="utf-8")))

        with mock.patch.object(sandbox_proxies, "OUTER_RUNTIME", owner), \
                mock.patch.object(sandbox_proxies, "runtime_identity", return_value=shared_state["runtime"]), \
                mock.patch.object(sandbox_proxies, "containers_running", return_value=False):
            with self.assertRaisesRegex(sandbox_proxies.ConfigError, "stopped proxy"):
                sandbox_proxies.accepted_session(args, self.repo, json.loads((runtime / "session.json").read_text()))

    def test_session_reader_rejects_symlink_and_reads_opened_inode_during_replacement(self) -> None:
        target = self.repo / "target"
        target.write_text('{"generation":"old"}')
        target.chmod(0o600)
        link = self.repo / "session-link"
        link.symlink_to(target)
        with self.assertRaisesRegex(sandbox_proxies.ConfigError, "unavailable"):
            sandbox_proxies._read_session(link)
        replacement = self.repo / "replacement"
        replacement.write_text('{"generation":"new"}')
        replacement.chmod(0o600)
        original_fdopen = os.fdopen
        def replace_after_open(descriptor, *args, **kwargs):
            os.replace(replacement, target)
            return original_fdopen(descriptor, *args, **kwargs)
        with mock.patch.object(sandbox_proxies.os, "fdopen", side_effect=replace_after_open):
            self.assertEqual("old", sandbox_proxies._read_session(target)["generation"])
        self.assertEqual("new", json.loads(target.read_text())["generation"])

    def test_session_reader_rejects_mode_and_owner(self) -> None:
        path = self.repo / "session.json"
        path.write_text("{}")
        with self.assertRaisesRegex(sandbox_proxies.ConfigError, "mode 0600"):
            sandbox_proxies._read_session(path)
        path.chmod(0o600)
        with mock.patch.object(sandbox_proxies.os, "getuid", return_value=os.getuid() + 1):
            with self.assertRaisesRegex(sandbox_proxies.ConfigError, "current uid"):
                sandbox_proxies._read_session(path)

    def test_empty_schema4_round_trips_publication_join_state_and_recovery(self) -> None:
        owner = mock.Mock(provider="lima")
        owner.host.state = Path("/recorded/lima")
        owner.record = {"instance": "owned-vm", "generation": "g", "namespace": "default",
                        "vm_identity": "v", "network_digest": "d"}
        identity = sandbox_runtime.runtime_identity(owner)
        state_path = self.repo / "empty-state"
        state_path.write_text(json.dumps({
            "proxies": [], "runtime": identity,
            "accepted": {"source-present": False, "agent-image": "agent",
                         "helper-image": None, "parameters": {"uid": 501, "gid": 20},
                         "proxy-images": {}},
        }))
        manifest_path = self.repo / "empty-manifest"
        manifest_path.write_text('{"version":1,"commands":{}}')
        args = SimpleNamespace(repo=str(self.repo), state=str(state_path), manifest=str(manifest_path),
                               container_repo=str(self.container_repo))
        with mock.patch.object(sandbox_proxies, "runtime_directory", return_value=self.repo), \
                mock.patch.object(sandbox_proxies, "OUTER_RUNTIME", owner):
            self.assertEqual(0, sandbox_proxies.publish_main(args))
        metadata = sandbox_proxies._read_session(self.repo / "session.json")
        self.assertEqual({}, metadata["services"])
        self.assertEqual({"runtime": identity, "proxies": [],
                          "trusted-services": sandbox_proxies.SESSION_LIFECYCLE_SCHEMA},
                         sandbox_proxies.session_state(metadata))
        join_args = SimpleNamespace(container_repo=str(self.container_repo), uid=501, gid=20,
                                    agent_image="agent", helper_image=None)
        owner.verify_builder_image.return_value = SimpleNamespace(reference="agent")
        with mock.patch.object(sandbox_proxies, "OUTER_RUNTIME", owner):
            state, accepted = sandbox_proxies.accepted_session(join_args, self.repo, metadata)
        self.assertEqual([], state["proxies"])
        self.assertEqual({}, accepted["images"]["proxies"])
        with mock.patch.object(sandbox_runtime, "image_runtime", return_value=owner) as reconstruct, \
                mock.patch.object(sandbox_proxies, "_stop_legacy_state") as cleanup:
            sandbox_proxies.stop_state(state)
        reconstruct.assert_called_once_with("lima", Path(identity["state"]))
        cleanup.assert_called_once_with(state, owner)

    def test_schema4_strictly_parses_policy_and_broker_selection(self) -> None:
        args = SimpleNamespace(uid=501, gid=20)
        malformed = self.schema4({"example": self.command()})
        malformed["accepted"]["policy"]["unknown"] = True
        with self.assertRaisesRegex(sandbox_proxies.ConfigError, "accepted policy"):
            sandbox_proxies._accepted_schema4(malformed, expected_parameters={"uid": 501, "gid": 20})
        helper_only = self.schema4({}, helper="sha256:" + "4" * 64)
        sandbox_proxies._accepted_schema4(
            helper_only, expected_parameters={"uid": 501, "gid": 20})
        missing = self.schema4({})
        missing["accepted"]["broker-roles"] = ["codex-broker"]
        with self.assertRaisesRegex(sandbox_proxies.ConfigError, "service set"):
            sandbox_proxies._accepted_schema4(missing, expected_parameters={"uid": 501, "gid": 20})
        unsolicited = self.schema4({})
        proxy = self.managed_proxy("extra")
        proxy["family"] = "authenticated-egress"
        proxy["credential-domain"] = "zulip"
        # An unsolicited broker cannot be admitted merely by appearing in services.
        unsolicited["services"]["extra"] = sandbox_proxies._service_record(
            "extra", proxy, {"provider": "container"})
        unsolicited["accepted"]["images"]["services"]["extra"] = proxy["image"]
        with self.assertRaises(sandbox_proxies.ConfigError):
            sandbox_proxies._accepted_schema4(unsolicited, expected_parameters={"uid": 501, "gid": 20})

    def test_publication_rejects_duplicate_proxy_roles_before_projection(self) -> None:
        proxy = self.managed_proxy("same")
        state = self.repo / "duplicate-state"
        state.write_text(json.dumps({"runtime": {"provider": "container"}, "proxies": [proxy, dict(proxy)],
            "accepted": {"source-present": True, "agent-image": "agent", "helper-image": None,
                         "parameters": {"uid": 501, "gid": 20},
                         "proxy-images": {"same": proxy["image"]}}}))
        manifest = self.repo / "duplicate-manifest"
        manifest.write_text(json.dumps({"version": 1, "commands": {"same": self.command()}}))
        args = SimpleNamespace(repo=str(self.repo), state=str(state), manifest=str(manifest),
                               container_repo=str(self.container_repo))
        with self.assertRaisesRegex(sandbox_proxies.ConfigError, "duplicate service roles"):
            sandbox_proxies.publish_main(args)

    def test_schema4_rejects_partial_and_cross_bound_authority(self) -> None:
        command = {"example": self.command()}
        args = SimpleNamespace(uid=501, gid=20)
        cases = []
        partial = self.schema4(command)
        partial["services"] = {}
        cases.append(partial)
        wrong_image = self.schema4(command)
        wrong_image["accepted"]["images"]["services"]["example"] = "sha256:" + "9" * 64
        cases.append(wrong_image)
        wrong_implementation = self.schema4(command)
        wrong_implementation["services"]["example"]["recovery"]["implementation-identity"] = "sha256:" + "2" * 64
        cases.append(wrong_implementation)
        wrong_endpoint = self.schema4(command)
        wrong_endpoint["services"]["example"]["endpoints"][0]["container"] = "attacker"
        cases.append(wrong_endpoint)
        unknown_endpoint = self.schema4(command)
        unknown_endpoint["services"]["example"]["endpoints"][0]["unknown"] = True
        cases.append(unknown_endpoint)
        unknown_recovery = self.schema4(command)
        unknown_recovery["services"]["example"]["recovery"]["unknown"] = True
        cases.append(unknown_recovery)
        unknown_runtime = self.schema4(command)
        unknown_runtime["services"]["example"]["runtime-owner"]["unknown"] = True
        cases.append(unknown_runtime)
        for metadata in cases:
            with self.subTest(metadata=metadata):
                with self.assertRaises(sandbox_proxies.ConfigError):
                    sandbox_proxies._accepted_schema4(metadata, expected_parameters={"uid": 501, "gid": 20})

    def test_schema4_rejects_forward_owner_and_runtime_disagreement(self) -> None:
        first, second = self.managed_proxy("first"), self.managed_proxy("second")
        first["forwarding"] = {"owner": first["service-owner"], "socket": "first"}
        first["volume-owner"] = first["service-owner"]
        first["resource-status"]["forward"] = "created"
        services = {
            "first": sandbox_proxies._service_record("first", first, {"provider": "container"}),
            "second": sandbox_proxies._service_record("second", second, {"provider": "lima", "state": "/tmp/lima", "instance": "i", "generation": "g", "namespace": "n", "vm_identity": "v", "network_digest": "d"}),
        }
        metadata = self.schema4({"first": self.command(), "second": self.command()}, services=services)
        metadata["services"]["first"]["endpoints"][0]["forward"]["owner"] = "another-owner"
        with self.assertRaisesRegex(sandbox_proxies.ConfigError, "forwarding owner"):
            sandbox_proxies._accepted_schema4(metadata, expected_parameters={"uid": 501, "gid": 20})
        first["forwarding"]["owner"] = first["service-owner"]
        services = {
            "first": sandbox_proxies._service_record("first", first, {"provider": "container"}),
            "second": sandbox_proxies._service_record("second", second, {"provider": "lima", "state": "/tmp/lima", "instance": "i", "generation": "g", "namespace": "n", "vm_identity": "v", "network_digest": "d"}),
        }
        metadata = self.schema4({"first": self.command(), "second": self.command()}, services=services)
        with self.assertRaisesRegex(sandbox_proxies.ConfigError, "runtime owner"):
            sandbox_proxies.session_state(metadata)

    def test_active_schema3_join_is_rejected_without_mutation_or_policy_load(self) -> None:
        metadata = {"version": 3, "state": {"runtime": {"provider": "container"}, "proxies": []}}
        before = json.dumps(metadata, sort_keys=True)
        args = SimpleNamespace(container_repo=str(self.container_repo))
        with mock.patch.object(sandbox_proxies, "load_manifest", side_effect=AssertionError("policy loaded")):
            with self.assertRaisesRegex(sandbox_proxies.ConfigError, "not schema 4"):
                sandbox_proxies.accepted_session(args, self.repo, metadata)
        self.assertEqual(before, json.dumps(metadata, sort_keys=True))

    def test_schema3_remains_available_for_stale_recovery(self) -> None:
        owner = mock.Mock(provider="lima")
        owner.host.state = Path("/recorded/lima")
        owner.record = {"instance": "owned-vm", "generation": "g", "namespace": "default",
                        "vm_identity": "v", "network_digest": "d"}
        identity = sandbox_runtime.runtime_identity(owner)
        state = {"runtime": identity, "proxies": []}
        self.assertIs(state, sandbox_proxies.session_state({"version": 3, "state": state}))
        with mock.patch.object(sandbox_runtime, "image_runtime", return_value=owner) as reconstruct, \
                mock.patch.object(sandbox_proxies, "_stop_legacy_state") as cleanup:
            sandbox_proxies.stop_state(state)
        reconstruct.assert_called_once_with("lima", Path(identity["state"]))
        cleanup.assert_called_once_with(state, owner)

    def test_new_schema_requires_an_explicit_owner_and_legacy_is_podman(self) -> None:
        with self.assertRaisesRegex(sandbox_proxies.ConfigError, "missing its runtime"):
            sandbox_proxies.session_state({"version": 2, "state": {"proxies": []}})
        with self.assertRaisesRegex(sandbox_proxies.ConfigError, "legacy"):
            sandbox_proxies.session_state({"version": 1, "state": {"runtime": {"provider": "lima"}}})

    def test_reset_retains_recovery_metadata_when_recorded_vm_is_unavailable(self) -> None:
        self.write()
        metadata = sandbox_proxies.runtime_directory(self.repo) / "session.json"
        contents = json.dumps({"version": 2, "state": {"runtime": {"provider": "lima"}, "proxies": []}})
        metadata.write_text(contents)
        with mock.patch.object(sandbox_proxies, "state_runtime", side_effect=ValueError("missing VM")):
            with self.assertRaisesRegex(ValueError, "missing VM"):
                sandbox_proxies.reset_main(type("Args", (), {"repo": str(self.repo)}))
        self.assertEqual(contents, metadata.read_text())

    def test_proxy_cleanup_uses_recorded_owner_when_default_changes(self) -> None:
        state = {"runtime": {"provider": "container"}, "proxies": [
            {"container": "owned-container", "volume": "owned-volume"}]}
        owner = mock.Mock()
        owner.run.return_value = subprocess.CompletedProcess([], 0, stdout="")
        with mock.patch.object(sandbox_proxies, "OUTER_RUNTIME") as current, \
                mock.patch.object(sandbox_proxies, "state_runtime", return_value=owner) as recorded:
            sandbox_proxies.stop_state(state)
        recorded.assert_called_once_with(state, recovery=True)
        current.run.assert_not_called()
        self.assertIn(["volume", "rm", "owned-volume"], [call.args[0] for call in owner.run.call_args_list])

    def test_reset_keeps_metadata_when_engine_reports_surviving_resources(self) -> None:
        self.write()
        metadata = sandbox_proxies.runtime_directory(self.repo) / "session.json"
        state = {"runtime": {"provider": "container"}, "proxies": [{"container": "survivor", "volume": "owned-volume"}]}
        contents = json.dumps({"version": 2, "state": state})
        metadata.write_text(contents)
        owner = mock.Mock()
        owner.run.return_value = subprocess.CompletedProcess([], 0, stdout="survivor\n")
        with mock.patch.object(sandbox_proxies, "state_runtime", return_value=owner):
            with self.assertRaisesRegex(sandbox_proxies.ConfigError, "remain after cleanup"):
                sandbox_proxies.reset_main(type("Args", (), {"repo": str(self.repo)}))
        self.assertEqual(contents, metadata.read_text())

    def test_cleanup_reports_survivors_with_engine_errors_and_keeps_metadata(self) -> None:
        self.write()
        metadata = sandbox_proxies.runtime_directory(self.repo) / "session.json"
        for kind in ("containers", "volumes"):
            with self.subTest(kind=kind):
                state = {"runtime": {"provider": "container"}, "proxies": [
                    {"container": "proxy", "volume": "busy-volume"},
                    {"container": "gone", "volume": "gone-volume"},
                ]}
                contents = json.dumps({"version": 2, "state": state})
                metadata.write_text(contents)

                def run(arguments, **kwargs):
                    output, error, status = "", "", 0
                    if arguments[:2] == ["container", "ls"] and kind == "containers":
                        output = "proxy\n"
                    elif arguments[:2] == ["volume", "ls"]:
                        output = "busy-volume\n"
                    elif arguments == ["rm", "proxy"]:
                        error, status = "container is running", 1
                    elif arguments == ["volume", "rm", "busy-volume"]:
                        error, status = "volume is in use - [stopped-agent-1, stopped-agent-2]", 1
                    elif arguments[0] in ("kill", "rm"):
                        error, status = "No such container", 1
                    # Match subprocess: discarded stderr is unavailable to the caller.
                    return subprocess.CompletedProcess(arguments, status, stdout=output,
                        stderr=error if kwargs.get("capture_output") else None)

                owner = mock.Mock()
                owner.run.side_effect = run
                with mock.patch.object(sandbox_proxies, "state_runtime", return_value=owner):
                    with self.assertRaises(sandbox_proxies.ConfigError) as raised:
                        sandbox_proxies.reset_main(SimpleNamespace(repo=str(self.repo)))
                diagnostic = str(raised.exception)
                self.assertIn("retaining recovery metadata", diagnostic)
                self.assertIn(
                    "reset removes stopped matching agent containers",
                    diagnostic,
                )
                self.assertIn(
                    "run `python3 tools/codex-sandbox/sandbox-proxies.py reset --repo <repository>`",
                    diagnostic,
                )
                if kind == "volumes":
                    self.assertIn("busy-volume: volume is in use - [stopped-agent-1, stopped-agent-2]", diagnostic)
                else:
                    self.assertIn("proxy: container is running", diagnostic)
                self.assertNotIn("No such container", diagnostic)
                self.assertEqual(contents, metadata.read_text())

    def test_local_fallback_preserves_stale_session_recovery_record(self) -> None:
        self.write({"example": self.command()})
        metadata = sandbox_proxies.runtime_directory(self.repo) / "session.json"
        contents = json.dumps({"version": 2, "state": {"runtime": {"provider": "lima"}}})
        metadata.write_text(contents)
        args = type("Args", (), {"repo": str(self.repo), "command": "example", "local": ["local"]})
        repository = sandbox_proxies.repository_identity(self.repo)
        manifest = sandbox_proxies.load_manifest(self.repo)
        with mock.patch.object(sandbox_proxies, "repository_identity", return_value=repository), \
                mock.patch.object(sandbox_proxies, "load_manifest", return_value=manifest), \
                mock.patch.object(sandbox_proxies.subprocess, "run", return_value=subprocess.CompletedProcess([], 7)):
            self.assertEqual(7, sandbox_proxies.route_main(args))
        self.assertEqual(contents, metadata.read_text())

    def test_matching_repository_cannot_reuse_another_provider(self) -> None:
        self.write()
        manifest = sandbox_proxies.load_manifest(self.repo)
        metadata = {"version": 2, "repository": sandbox_proxies.repository_identity(self.repo),
                    "container_repository": str(self.container_repo),
                    "manifest": sandbox_proxies.serializable_manifest(manifest),
                    "state": {"runtime": {"provider": "container"}, "proxies": []}}
        args = type("Args", (), {"container_repo": str(self.container_repo)})
        with mock.patch.object(sandbox_proxies, "runtime_identity", return_value={"provider": "lima"}), \
                mock.patch.object(sandbox_proxies, "containers_running") as running:
            self.assertIsNone(sandbox_proxies.cached_session_state(args, self.repo, metadata, manifest))
        running.assert_not_called()

    def test_docker_cached_proxy_reuses_one_live_snapshot_and_rejects_stopped_container(self):
        self.write({'example': self.command()})
        manifest = sandbox_proxies.load_manifest(self.repo)
        identity = sandbox_proxies.repository_identity(self.repo)
        proxy = {'name': 'example', 'container': 'container', 'image': 'immutable',
                 'volume-owner': 'owner', 'forwarding': {'owner': 'owner', 'target': '/socket'}}
        state = {'runtime': {'provider': 'lima-docker'}, 'proxies': [proxy]}
        metadata = {'version': 2, 'repository': identity, 'container_repository': str(self.container_repo),
                    'manifest': sandbox_proxies.serializable_manifest(manifest), 'state': state}
        args = type('Args', (), {'container_repo': str(self.container_repo)})
        owner = mock.Mock(provider='lima-docker')
        snapshot = {'State': {'Running': True}}
        owner.inspect_container.return_value = snapshot
        owner.container_matches_image.return_value = True
        owner.proxy_forward_record.return_value = proxy['forwarding']
        with mock.patch.object(sandbox_proxies, 'OUTER_RUNTIME', owner), \
                mock.patch.object(sandbox_proxies, 'runtime_identity', return_value=state['runtime']), \
                mock.patch.object(sandbox_proxies, 'containers_running', side_effect=AssertionError('duplicate inspect')), \
                mock.patch('lima.proxy_forward.check') as check:
            self.assertEqual(sandbox_proxies.cached_session_state(args, self.repo, metadata, manifest), state)
            owner.inspect_container.assert_called_once_with('container')
            self.assertIs(owner.container_matches_image.call_args.kwargs['snapshot'], snapshot)
            self.assertIs(owner.proxy_forward_record.call_args.kwargs['snapshot'], snapshot)
            check.assert_called_once_with('owner')
            owner.container_matches_image.return_value = False
            self.assertIsNone(sandbox_proxies.cached_session_state(args, self.repo, metadata, manifest))
            owner.container_matches_image.return_value = True
            owner.proxy_forward_record.return_value = {'owner': 'changed'}
            self.assertIsNone(sandbox_proxies.cached_session_state(args, self.repo, metadata, manifest))
            snapshot['State']['Running'] = False
            self.assertIsNone(sandbox_proxies.cached_session_state(args, self.repo, metadata, manifest))

    def test_route_uses_published_owner_despite_different_current_default(self) -> None:
        self.write()
        directory = sandbox_proxies.runtime_directory(self.repo)
        state = {"runtime": {"provider": "container"}, "proxies": []}
        proxy = self.managed_proxy("example")
        proxy["container"] = "owned"
        metadata = self.schema4({"example": self.command()}, services={
            "example": sandbox_proxies._service_record("example", proxy, state["runtime"]),
        })
        (directory / "session.json").write_text(json.dumps(metadata))
        (directory / "session.json").chmod(0o600)
        owner = mock.Mock()
        repository = sandbox_proxies.repository_identity(self.repo)
        owner.forward_proxy.return_value = 7
        owner.inspect_container.return_value = {"State": {"Running": True}}
        args = type("Args", (), {"repo": str(self.repo), "command": "example", "wait": 1, "local": ["local"]})
        with (directory / "session.lock").open("a+b") as lock:
            fcntl.flock(lock, fcntl.LOCK_SH)
            with mock.patch.object(sandbox_proxies, "OUTER_RUNTIME") as current, \
                    mock.patch.object(sandbox_proxies, "repository_identity", return_value=repository), \
                    mock.patch.object(sandbox_proxies, "state_runtime", return_value=owner) as recorded, \
                    mock.patch.object(sandbox_proxies, "validate_live_proxy") as validate:
                self.assertEqual(7, sandbox_proxies.route_main(args))
        recorded.assert_called_once_with(sandbox_proxies.session_state(metadata))
        self.assertIs(owner, validate.call_args.args[0])
        current.forward_proxy.assert_not_called()
        owner.forward_proxy.assert_called_once_with("owned")

    def test_live_identity_requires_native_image_as_well_as_labels(self) -> None:
        owner = sandbox_proxies.ContainerRuntime()
        owner.inspect_image = mock.Mock(return_value=SimpleNamespace(config='sha256:expected'))
        raw = {'Image': 'sha256:another', 'Config': {'Labels': {
            'dev.codex.sandbox-proxy': 'true', 'dev.codex.repository': 'repository',
            'dev.codex.command': 'example'}}}
        owner.run = mock.Mock(side_effect=lambda *a, **kw: SimpleNamespace(stdout=json.dumps([raw])))
        proxy = {"container": "owned", "image": "immutable"}
        with self.assertRaisesRegex(sandbox_proxies.ConfigError, "native image"):
            sandbox_proxies.validate_live_proxy(owner, proxy, "repository", "example")
        raw['Image'] = 'sha256:expected'
        sandbox_proxies.validate_live_proxy(owner, proxy, "repository", "example")
        raw['Config']['Labels']['dev.codex.repository'] = 'another-repository'
        with self.assertRaisesRegex(sandbox_proxies.ConfigError, "repository identity"):
            sandbox_proxies.validate_live_proxy(owner, proxy, "repository", "example")

    def test_exclusive_session_rebuilds_changed_cached_proxies(self) -> None:
        self.write({"example": self.command()})
        runtime = sandbox_proxies.runtime_directory(self.repo)
        old_state = {"proxies": [{
            "name": "example", "volume": "shared-example", "container": "old-example",
            "image": "sha256:" + "0" * 64,
        }]}
        (runtime / "session.json").write_text(json.dumps({
            "version": 1,
            "repository": sandbox_proxies.repository_identity(self.repo),
            "state": old_state, "manifest": {"version": 1, "commands": {}},
        }), encoding="utf-8")
        (runtime / "session.json").chmod(0o600)
        args = type("Args", (), {
            "repo": str(self.repo), "container_repo": str(self.container_repo),
            "shared": False, "state": str(self.repo / "state"),
            "manifest": str(self.repo / "manifest"),
        })
        Path(args.manifest).write_text(json.dumps(
            sandbox_proxies.serializable_manifest(sandbox_proxies.load_manifest(self.repo))
        ), encoding="utf-8")
        with mock.patch.object(sandbox_proxies, "stop_state") as stop, \
                mock.patch.object(sandbox_proxies, "start_main") as start:
            self.assertEqual(0, sandbox_proxies.attach_main(args))
        stop.assert_called_once_with(old_state)
        start.assert_called_once_with(args)

    def test_exclusive_session_stops_changed_schema4_services_before_replacement(self) -> None:
        self.write({"example": self.command()})
        runtime = sandbox_proxies.runtime_directory(self.repo)
        metadata = self.schema4({"example": self.command()})
        (runtime / "session.json").write_text(json.dumps(metadata), encoding="utf-8")
        (runtime / "session.json").chmod(0o600)
        manifest = self.repo / "manifest"
        manifest.write_text(json.dumps(
            sandbox_proxies.serializable_manifest(sandbox_proxies.load_manifest(self.repo))
        ), encoding="utf-8")
        args = SimpleNamespace(
            repo=str(self.repo), container_repo=str(self.container_repo), shared=False,
            state=str(self.repo / "state"), manifest=str(manifest),
        )
        with mock.patch.object(sandbox_proxies, "cached_session_state", return_value=None), \
                mock.patch.object(sandbox_proxies, "stop_state") as stop, \
                mock.patch.object(sandbox_proxies, "start_main") as start:
            self.assertEqual(0, sandbox_proxies.attach_main(args))
        self.assertEqual(["example"], [
            proxy["name"] for proxy in stop.call_args.args[0]["proxies"]
        ])
        start.assert_called_once_with(args)

    def test_exclusive_session_preserves_replaced_vm_record_without_touching_new_vm(self) -> None:
        self.write({"example": self.command()})
        runtime = self.repo / "runtime"
        runtime.mkdir()
        old = {"provider": "lima-docker", "state": str(self.repo / "vm-state"),
               "instance": "sandbox-host-docker", "generation": "old", "namespace": "default",
               "vm_identity": "old-vm", "network_digest": "policy",
               "engine_id": "old-engine", "network_id": "old-network"}
        new = {**old, "generation": "new", "vm_identity": "new-vm",
               "engine_id": "new-engine", "network_id": "new-network"}
        metadata = self.schema4({"example": self.command()})
        metadata["runtime-owner"] = old
        metadata["services"]["example"]["runtime-owner"] = old
        original = json.dumps(metadata)
        session = runtime / "session.json"
        session.write_text(original)
        session.chmod(0o600)
        manifest = self.repo / "manifest"
        manifest.write_text(json.dumps(
            sandbox_proxies.serializable_manifest(sandbox_proxies.load_manifest(self.repo))))
        args = SimpleNamespace(repo=str(self.repo), container_repo=str(self.container_repo),
                               shared=False, state=str(self.repo / "state"), manifest=str(manifest))
        with mock.patch.object(sandbox_proxies, "runtime_directory", return_value=runtime), \
                mock.patch.object(sandbox_proxies, "runtime_identity", return_value=new), \
                mock.patch.object(sandbox_proxies, "cached_session_state", return_value=None), \
                mock.patch.object(sandbox_proxies, "stop_state") as stop, \
                mock.patch.object(sandbox_proxies, "start_main") as start:
            self.assertEqual(0, sandbox_proxies.attach_main(args))
        stop.assert_not_called()
        start.assert_called_once_with(args)
        self.assertFalse(session.exists())
        archived = list(runtime.glob("session.replaced-*.json"))
        self.assertEqual(1, len(archived))
        self.assertEqual(original, archived[0].read_text())
        self.assertEqual(0o600, archived[0].stat().st_mode & 0o777)

        session.write_text(original)
        session.chmod(0o600)
        policy_change = {**old, "network_digest": "new-policy"}
        with mock.patch.object(sandbox_proxies, "runtime_directory", return_value=runtime), \
                mock.patch.object(sandbox_proxies, "runtime_identity", return_value=policy_change), \
                mock.patch.object(sandbox_proxies, "cached_session_state", return_value=None), \
                mock.patch.object(sandbox_proxies, "stop_state", side_effect=RuntimeError("policy drift")) as stop, \
                mock.patch.object(sandbox_proxies, "start_main") as start:
            with self.assertRaisesRegex(RuntimeError, "policy drift"):
                sandbox_proxies.attach_main(args)
        stop.assert_called_once()
        start.assert_not_called()
        self.assertTrue(session.exists())

    def test_shared_session_rejects_changed_cached_proxies(self) -> None:
        self.write()
        runtime = sandbox_proxies.runtime_directory(self.repo)
        (runtime / "session.json").write_text(json.dumps({
            "version": 1,
            "repository": sandbox_proxies.repository_identity(self.repo),
            "state": {"proxies": []}, "manifest": {"version": 1, "commands": {"old": {}}},
        }), encoding="utf-8")
        (runtime / "session.json").chmod(0o600)
        manifest = self.repo / "manifest"
        manifest.write_text(json.dumps({"version": 1, "commands": {}}), encoding="utf-8")
        args = type("Args", (), {
            "repo": str(self.repo), "container_repo": str(self.container_repo),
            "shared": True, "state": str(self.repo / "state"),
            "manifest": str(manifest),
        })
        with self.assertRaisesRegex(sandbox_proxies.ConfigError, "restart after active"):
            sandbox_proxies.attach_main(args)

    def test_attach_does_not_replace_invalid_active_session(self) -> None:
        self.write()
        manifest = self.repo / "manifest"
        manifest.write_text(json.dumps({"version": 1, "commands": {}}), encoding="utf-8")
        args = type("Args", (), {
            "repo": str(self.repo), "container_repo": str(self.container_repo),
            "shared": True, "state": str(self.repo / "state"),
            "manifest": str(manifest),
        })
        with mock.patch.object(sandbox_proxies, "start_main") as start:
            with self.assertRaisesRegex(sandbox_proxies.ConfigError, "unavailable"):
                sandbox_proxies.attach_main(args)
        start.assert_not_called()

    def test_exclusive_attach_discards_unrecognized_cache(self) -> None:
        self.write()
        runtime = self.repo / "runtime"
        runtime.mkdir()
        cached = runtime / "session.json"
        cached.write_text("{}", encoding="utf-8")
        cached.chmod(0o600)
        manifest = self.repo / "manifest"
        manifest.write_text(json.dumps({"version": 1, "commands": {}}), encoding="utf-8")
        args = type("Args", (), {
            "repo": str(self.repo), "container_repo": str(self.container_repo),
            "shared": False, "state": str(self.repo / "state"),
            "manifest": str(manifest),
        })
        with mock.patch.object(sandbox_proxies, "runtime_directory", return_value=runtime), \
                mock.patch.object(sandbox_proxies, "start_main") as start:
            self.assertEqual(0, sandbox_proxies.attach_main(args))
        self.assertFalse(cached.exists())
        start.assert_called_once_with(args)

    def test_proxy_stop_kills_and_removes_containers_before_volumes(self) -> None:
        state = {"runtime": {"provider": "container"},
            "auth": {"container": "auth-proxy", "key": "secret", "image": "helper"},
            "proxies": [{
                "name": "example", "container": "proxy", "volume": "volume",
                "image": "sha256:" + "0" * 64,
            }],
        }
        completed = subprocess.CompletedProcess([], 0, stdout="", stderr="")
        owner = mock.Mock()
        owner.run.return_value = completed
        with mock.patch.object(sandbox_proxies, "state_runtime", return_value=owner):
            sandbox_proxies.stop_state(state)
        calls = [call.args[0] for call in owner.run.call_args_list]
        container_cleanup = [call for call in calls if call[:1] == ["kill"]]
        container_removal = [call for call in calls if call[:1] == ["rm"]]
        self.assertCountEqual([
            ["kill", "auth-proxy"],
            ["kill", "proxy"],
        ], container_cleanup)
        self.assertCountEqual([
            ["rm", "auth-proxy"],
            ["rm", "proxy"],
        ], container_removal)
        volume_removal = calls.index(["volume", "rm", "volume"])
        self.assertGreater(volume_removal, 3)

    def test_cleanup_cannot_delete_a_volume_rejected_during_creation(self) -> None:
        state = {"proxies": [{"container": "owned-container", "volume": "collision",
                               "volume-owner": "this-creator"}]}
        owner = mock.Mock()

        def run(arguments, **kwargs):
            output = ""
            if arguments[:2] == ["volume", "ls"]:
                output = "collision\n"
            elif arguments[:2] == ["volume", "inspect"]:
                output = json.dumps([{"Labels": {"dev.codex.volume-owner": "another-creator"}}])
            return subprocess.CompletedProcess(arguments, 0, stdout=output)

        owner.run.side_effect = run
        with mock.patch.object(sandbox_proxies, "state_runtime", return_value=owner):
            with self.assertRaisesRegex(sandbox_proxies.ConfigError, "another creator"):
                sandbox_proxies.stop_state(state)
        self.assertFalse(any(call.args[0][:2] == ["volume", "rm"]
                             for call in owner.run.call_args_list))

    def test_image_resolution_normalizes_bare_sha256_hash(self) -> None:
        digest = "0" * 64
        manifest = {"commands": {"example": self.command()}}
        completed = subprocess.CompletedProcess([], 0, stdout=digest + "\n")
        with mock.patch.object(sandbox_proxies.subprocess, "run", return_value=completed):
            images = sandbox_proxies.resolve_images(self.repo, manifest)
        self.assertEqual("sha256:" + digest, images["example"])

    def test_forward_failure_retains_registered_recovery_authority(self) -> None:
        state_path = self.repo / "state"
        args = SimpleNamespace(prefix="test", state=str(state_path), network="sandbox",
                               container_repo=str(self.container_repo), zuliprc=None)
        command = self.command()
        image = "sha256:" + "0" * 64
        runtime = mock.Mock(provider="lima-docker")
        runtime.proxy_forward_record.return_value = {
            "owner": "a" * 32, "target": "/run/sandbox-proxy/socket",
        }
        runtime.start_proxy_forward.side_effect = RuntimeError("forward failed")
        with mock.patch.object(sandbox_proxies, "OUTER_RUNTIME", runtime), \
                mock.patch.object(sandbox_proxies, "VMRuntime", object), \
                mock.patch.object(sandbox_proxies.uuid, "uuid4", return_value=SimpleNamespace(hex="a" * 32)), \
                mock.patch.object(sandbox_proxies, "_docker") as docker, \
                mock.patch.object(sandbox_proxies, "proxy_repository_mount_args", return_value=[]), \
                mock.patch.object(sandbox_proxies, "checked_repository_path"):
            with self.assertRaisesRegex(RuntimeError, "forward failed"):
                sandbox_proxies.start_one_proxy(
                    args, self.repo, "repository", {"example": image},
                    {"proxies": []}, threading.Lock(), "example", command,
                )
        recovery = json.loads(state_path.read_text())["proxies"][0]
        run_argv = docker.call_args_list[0].args
        self.assertEqual((image, "serve"), run_argv[-2:])
        self.assertEqual("example-proxy", run_argv[run_argv.index("--entrypoint") + 1])
        self.assertEqual("none", run_argv[run_argv.index("--network") + 1])
        self.assertEqual("failed", recovery["lifecycle-state"])
        self.assertEqual("a" * 32, recovery["forwarding"]["owner"])

    def test_jj_proxy_uses_rootless_container_root_for_private_metadata(self) -> None:
        state_path = self.repo / "state"
        args = SimpleNamespace(prefix="test", state=str(state_path), network="sandbox",
                               container_repo=str(self.container_repo), zuliprc=None)
        command = self.command(argv=["jj-proxy", "serve"])
        image = "sha256:" + "0" * 64
        completed = subprocess.CompletedProcess

        def docker(*arguments, capture=False):
            stdout = "true\n" if arguments[:2] == ("inspect", "--format") else ""
            return completed(arguments, 0, stdout=stdout)

        with mock.patch.object(sandbox_proxies, "OUTER_RUNTIME", mock.Mock(provider="container")), \
                mock.patch.object(sandbox_proxies, "_docker", side_effect=docker) as run, \
                mock.patch.object(sandbox_proxies, "subprocess") as subprocess_module, \
                mock.patch.object(sandbox_proxies, "proxy_repository_mount_args", return_value=[]), \
                mock.patch.object(sandbox_proxies, "proxy_git_environment_args", return_value=[]), \
                mock.patch.object(sandbox_proxies, "git_metadata_paths", return_value=(self.repo / ".git", self.repo / ".git")), \
                mock.patch.object(sandbox_proxies, "jj_repository_path", return_value=self.repo / ".jj"), \
                mock.patch.object(sandbox_proxies, "checked_repository_path"):
            subprocess_module.run.return_value = completed([], 0, stderr="")
            sandbox_proxies.start_one_proxy(
                args, self.repo, "repository", {"jj": image},
                {"proxies": []}, threading.Lock(), "jj", command,
            )

        run_argv = next(call.args for call in run.call_args_list if call.args[0] == "run")
        self.assertEqual("0:0", run_argv[run_argv.index("--user") + 1])

    def test_jj_proxy_uses_agent_identity_for_uidmapped_virtiofs(self) -> None:
        args = SimpleNamespace(prefix="test", state=str(self.repo / "state"), network="sandbox",
                               container_repo=str(self.container_repo), zuliprc=None)
        command = self.command(argv=["jj-proxy", "serve"])
        image = "sha256:" + "0" * 64
        completed = subprocess.CompletedProcess

        def docker(*arguments, capture=False):
            stdout = "true\n" if arguments[:2] == ("inspect", "--format") else ""
            return completed(arguments, 0, stdout=stdout)

        owner = mock.Mock(spec=Docker)
        owner.provider = "lima-docker"
        owner.record = {"virtiofs_map": {"guest_uid": 100999}}
        owner.proxy_forward_record = mock.Mock(side_effect=lambda _container, service: {"owner": service})
        owner.start_proxy_forward = mock.Mock()
        state = {"proxies": []}
        with mock.patch.object(sandbox_proxies, "OUTER_RUNTIME", owner), \
                mock.patch.object(sandbox_proxies, "_docker", side_effect=docker) as run, \
                mock.patch.object(sandbox_proxies, "subprocess") as subprocess_module, \
                mock.patch.object(sandbox_proxies, "proxy_repository_mount_args", return_value=[]), \
                mock.patch.object(sandbox_proxies, "proxy_git_environment_args", return_value=[]), \
                mock.patch.object(sandbox_proxies, "git_metadata_paths", return_value=(self.repo / ".git", self.repo / ".git")), \
                mock.patch.object(sandbox_proxies, "jj_repository_path", return_value=self.repo / ".jj"), \
                mock.patch.object(sandbox_proxies, "checked_repository_path"):
            subprocess_module.run.return_value = completed([], 0, stderr="")
            sandbox_proxies.start_one_proxy(args, self.repo, "repository", {"jj": image},
                                            state, threading.Lock(), "jj", command)

        run_argv = next(call.args for call in run.call_args_list if call.args[0] == "run")
        self.assertEqual(f"{os.getuid()}:{os.getgid()}", run_argv[run_argv.index("--user") + 1])
        self.assertEqual({"uid": os.getuid(), "gid": os.getgid(), "network": "none"},
                         state["proxies"][0]["identity-parameters"])

    def test_failed_alias_cleanup_retains_recovery_and_blocks_resource_removal(self) -> None:
        service_owner = "a" * 32
        proxy = {
            "name": "example", "container": "container", "volume": "volume",
            "image": "sha256:" + "1" * 64,
            "service-owner": service_owner, "volume-owner": service_owner,
            "implementation-identity": "sha256:" + "0" * 64, "state-schema": 1,
            "lifecycle-state": "failed",
            "identity-parameters": {"uid": 501, "gid": 20, "network": "none"},
            "resource-status": {"volume": "created", "container": "created", "forward": "created"},
            "forwarding": {"owner": service_owner, "target": "/owned/socket"},
        }
        state = {"runtime": {"provider": "lima-docker"}, "proxies": [proxy]}
        original = json.dumps(state, sort_keys=True)
        owner = mock.Mock(provider="lima-docker")
        owner.stop_proxy_forward.side_effect = RuntimeError("alias still live")
        with mock.patch.object(sandbox_proxies, "state_runtime", return_value=owner):
            with self.assertRaisesRegex(sandbox_proxies.ConfigError, "retaining recovery metadata"):
                sandbox_proxies.stop_state(state)
        self.assertEqual(original, json.dumps(state, sort_keys=True))
        self.assertFalse(any(call.args[0][0] in {"kill", "rm"}
                             for call in owner.run.call_args_list))

    def test_managed_podman_cleanup_rejects_preexisting_mismatched_volume(self) -> None:
        service_owner = "a" * 32
        command = self.command()
        image = "sha256:" + "1" * 64
        resolved = sandbox_proxies._command_proxy_resolved(
            "example", command, image, "none", 501, 20,
        )
        proxy = {
            "name": "example", "container": "container", "volume": "volume", "image": image,
            "service-owner": service_owner,
            "implementation-identity": resolved.implementation_identity, "state-schema": 1,
            "lifecycle-state": "failed",
            "identity-parameters": {"uid": 501, "gid": 20, "network": "none"},
            "resource-status": {"volume": "intended", "container": "intended", "forward": "absent"},
        }
        owner = mock.Mock(provider="container")
        def run(arguments, **_kwargs):
            output = ""
            if arguments[:2] == ["volume", "ls"]:
                output = "volume\n"
            elif arguments[:2] == ["volume", "inspect"]:
                output = json.dumps([{"Labels": {"dev.codex.service-owner": "b" * 32}}])
            return subprocess.CompletedProcess(arguments, 0, stdout=output, stderr="")
        owner.run.side_effect = run
        with mock.patch.object(sandbox_proxies, "state_runtime", return_value=owner):
            with self.assertRaisesRegex(sandbox_proxies.ConfigError, "retaining recovery metadata"):
                sandbox_proxies.stop_state({"runtime": {"provider": "container"}, "proxies": [proxy]})
        self.assertFalse(any(call.args[0][:2] == ["volume", "rm"] for call in owner.run.call_args_list))

    def test_adapter_identity_changes_when_owned_implementation_changes(self) -> None:
        source = sandbox_proxies.MODULE_PATH.read_bytes() if hasattr(sandbox_proxies, "MODULE_PATH") else MODULE_PATH.read_bytes()
        original = sandbox_proxies._command_proxy_adapter_bytes(source)
        changed = source.replace(
            b'proxy["lifecycle-state"] = "ready"',
            b'proxy["lifecycle-state"] = "READY"', 1,
        )
        self.assertNotEqual(original, sandbox_proxies._command_proxy_adapter_bytes(changed))
        outside = source.replace(b'"Generic sandbox proxy manifest', b'"Changed host coordination', 1)
        self.assertEqual(original, sandbox_proxies._command_proxy_adapter_bytes(outside))

    def test_managed_implementation_identity_rejects_command_mutation(self) -> None:
        command = self.command()
        image = "sha256:" + "1" * 64
        resolved = sandbox_proxies._command_proxy_resolved(
            "example", command, image, "none", 501, 20,
        )
        proxy = {
            "name": "example", "container": "container", "volume": "volume", "image": image,
            "service-owner": "a" * 32,
            "implementation-identity": resolved.implementation_identity, "state-schema": 1,
            "lifecycle-state": "ready",
            "identity-parameters": {"uid": 501, "gid": 20, "network": "none"},
            "resource-status": {"volume": "created", "container": "created", "forward": "absent"},
        }
        sandbox_proxies._validate_proxy_implementation(proxy, command)
        with self.assertRaisesRegex(sandbox_proxies.ConfigError, "implementation identity changed"):
            sandbox_proxies._validate_proxy_implementation(proxy, {**command, "argv": ["changed"]})

    def test_mixed_legacy_forwarding_remains_recoverable(self) -> None:
        legacy = {
            "name": "legacy", "container": "legacy-container", "volume": "legacy-volume",
            "image": "sha256:" + "1" * 64, "volume-owner": "b" * 32,
            "forwarding": {"owner": "b" * 32, "target": "/legacy/socket"},
        }
        owner = mock.Mock(provider="lima-docker")
        owner.run.return_value = subprocess.CompletedProcess([], 0, stdout="", stderr="")
        registry = sandbox_proxies._proxy_registry(owner, legacy)
        self.assertFalse(registry.cleanup(0).remaining)
        owner.stop_proxy_forward.assert_called_once_with(legacy["forwarding"])

    def test_codex_pair_record_is_complete_and_cross_bound_attachments_fail_closed(self) -> None:
        record = self.pair_auth()
        kind, parsed = sandbox_proxies.parse_auth_record(record, managed_required=True)
        self.assertEqual("managed", kind)
        self.assertEqual("codex-auth-helper", parsed["refresh-attachment"]["container"])
        for field in ("helper-container", "socket-volume", "caddy-image-chain", "configuration"):
            partial = dict(record)
            partial.pop(field)
            with self.assertRaisesRegex(ValueError, "fields"):
                sandbox_proxies.parse_auth_record(partial, managed_required=True)
        crossed = json.loads(json.dumps(record))
        crossed["refresh-attachment"]["container"] = crossed["container"]
        with self.assertRaisesRegex(ValueError, "pair"):
            sandbox_proxies.parse_auth_record(crossed, managed_required=True)
        for aliased_role in ("application", "refresh"):
            aliased = json.loads(json.dumps(record))
            aliased["networks"][aliased_role] = aliased["networks"]["agent-link"]
            if aliased_role == "refresh":
                aliased["refresh-attachment"]["network"] = aliased["networks"]["refresh"]
            with self.assertRaisesRegex(ValueError, "pair"):
                sandbox_proxies.parse_auth_record(aliased, managed_required=True)

    def test_codex_pair_rejects_substituted_network_role_labels(self) -> None:
        record = self.pair_auth()
        labels = {
            role: {"dev.codex.service-owner": record["service-owner"],
                   "dev.codex.credential-domain": "codex",
                   "dev.codex.network-role": role}
            for role in ("application", "refresh")
        }
        sandbox_proxies._validate_codex_network_labels(record, labels)
        substituted = json.loads(json.dumps(labels))
        substituted["application"]["dev.codex.network-role"] = "refresh"
        with self.assertRaisesRegex(sandbox_proxies.ConfigError, "ownership"):
            sandbox_proxies._validate_codex_network_labels(record, substituted)

    def test_managed_auth_record_cannot_downgrade_by_dropping_owner(self) -> None:
        record = {
            "container": "codex-auth", "key": "a.b.c", "image": "sha256:" + "1" * 64,
            "implementation-identity": "sha256:" + "2" * 64, "state-schema": 1,
            "lifecycle-state": "published", "credential-domain": "codex",
            "network": "codex-public-only", "network-owner": {"kind": "admitted-runtime-public-egress",
                              "runtime": {"provider": "container"}},
            "endpoint": {"container": "codex-auth", "port": 8787},
            "credential-volume": {"kind": "bind", "target": "/var/lib/codex-auth",
                                  "identity": "sha256:" + "3" * 64,
                                  "lifetime": "shared-session"},
            "token-lifetime": "shared-session", "runtime-owner": {"provider": "container"},
            "resource-status": {"container": "created"},
        }
        with self.assertRaisesRegex(ValueError, "fields"):
            sandbox_proxies.parse_auth_record(record)
        with self.assertRaisesRegex(ValueError, "cannot downgrade"):
            sandbox_proxies.parse_auth_record(
                {"container": "codex-auth", "key": "a.b.c", "image": "sha256:" + "1" * 64},
                managed_required=True,
            )

    def test_managed_auth_recovery_rejects_another_services_container(self) -> None:
        owner = mock.Mock(provider="container")
        owner.resource_owner_label.return_value = "dev.codex.service-owner"

        def run(arguments, **kwargs):
            if arguments[:2] == ["container", "ls"]:
                return subprocess.CompletedProcess(arguments, 0, stdout="codex-auth\n")
            if arguments[:2] == ["container", "inspect"]:
                return subprocess.CompletedProcess(arguments, 0, stdout="another-owner\n")
            return subprocess.CompletedProcess(arguments, 0, stdout="")

        owner.run.side_effect = run
        state = {
            "runtime": {"provider": "container"}, "proxies": [],
            "auth": {
                "container": "codex-auth", "helper-container": "codex-auth-helper",
                "socket-volume": "codex-auth-socket", "key": "a.b.c",
                "image": "caddy@sha256:" + "1" * 64,
                "service-owner": "a" * 32, "implementation-identity": "sha256:" + "2" * 64,
                "helper-implementation": "sha256:" + "4" * 64,
                "caddy-image-chain": {"provenance": "caddy:2.11.4-alpine",
                    "index_digest": "sha256:" + "5" * 64, "platform": "linux/amd64",
                    "manifest_digest": "sha256:" + "1" * 64,
                    "configuration_digest": "sha256:" + "6" * 64,
                    "runtime_image_id": "sha256:" + "6" * 64},
                "configuration": {"path": "/state/caddy.json", "digest": "sha256:" + "7" * 64},
                "state-schema": 1, "lifecycle-state": "failed", "credential-domain": "codex",
                "network": "codex-application", "networks": {"agent-link": "codex-public-only",
                    "application": "codex-application", "refresh": "codex-refresh"},
                "refresh-attachment": {"container": "codex-auth-helper", "network": "codex-refresh"},
                "network-owner": {"kind": "admitted-runtime-public-egress",
                                  "runtime": {"provider": "container"}},
                "endpoint": {"container": "codex-auth", "port": 8787},
                "credential-volume": {"kind": "bind", "target": "/var/lib/codex-auth",
                                      "identity": "sha256:" + "3" * 64,
                                      "lifetime": "shared-session"},
                "token-lifetime": "shared-session", "runtime-owner": {"provider": "container"},
                "resource-status": {"caddy-container": "unknown", "helper-container": "unknown",
                    "socket-volume": "unknown", "application-network": "unknown",
                    "refresh-network": "unknown", "refresh-attachment": "unknown"},
            },
        }
        with mock.patch.object(sandbox_proxies, "state_runtime", return_value=owner):
            with self.assertRaisesRegex(sandbox_proxies.ConfigError, "owner validation"):
                sandbox_proxies.stop_state(state)
        self.assertFalse(any(call.args[0][:1] in (["kill"], ["rm"])
                             for call in owner.run.call_args_list))

    def test_managed_auth_recovery_removes_the_complete_owned_pair(self) -> None:
        auth = self.pair_auth()
        resources = {
            "container": {auth["container"], auth["helper-container"]},
            "network": {auth["networks"]["application"], auth["networks"]["refresh"]},
            "volume": {auth["socket-volume"]},
        }
        removed = []
        lock = threading.Lock()
        owner = mock.Mock(provider="container")
        owner.resource_owner_label.return_value = "dev.codex.service-owner"

        def run(arguments, **_kwargs):
            kind = arguments[0]
            with lock:
                if kind in {"kill", "rm"}:
                    if kind == "rm":
                        resources["container"].discard(arguments[-1])
                        removed.append(("container", arguments[-1]))
                    output = ""
                elif arguments[1] == "ls":
                    output = "".join(name + "\n" for name in sorted(resources[kind]))
                elif arguments[1] == "inspect":
                    output = auth["service-owner"] + "\n"
                elif arguments[1] == "rm":
                    resources[kind].discard(arguments[-1])
                    removed.append((kind, arguments[-1]))
                    output = ""
                else:
                    output = ""
            return subprocess.CompletedProcess(arguments, 0, stdout=output, stderr="")

        owner.run.side_effect = run
        with mock.patch.object(sandbox_proxies, "state_runtime", return_value=owner):
            sandbox_proxies.stop_state({
                "runtime": {"provider": "container"}, "proxies": [], "auth": auth,
            })

        self.assertTrue(all(not names for names in resources.values()))
        self.assertCountEqual(
            [(kind, name) for kind, names in {
                "container": {auth["container"], auth["helper-container"]},
                "network": {auth["networks"]["application"], auth["networks"]["refresh"]},
                "volume": {auth["socket-volume"]},
            }.items() for name in names],
            removed,
        )

    def test_zulip_recovery_removes_caddy_before_its_application_network(self) -> None:
        owner = "a" * 32
        proxy = {
            "name": "zulip", "service-owner": owner,
            "volume": "agent-socket", "container": "agent-proxy",
            "socket-volume": "profile-socket", "helper-container": "profile-helper",
            "caddy-container": "zulip-caddy", "network": "zulip-application",
            "configuration": {
                "path": str(self.repo / "absent-caddy.json"),
                "digest": "sha256:" + "1" * 64,
            },
        }
        removed = []

        def remove(_runtime, kind, name, _owner, **_kwargs):
            if kind is sandbox_proxies.ResourceKind.NETWORK and "zulip-caddy" not in removed:
                raise RuntimeError("network has active endpoints")
            removed.append(name)

        with mock.patch.object(sandbox_proxies, "_managed_proxy_record", return_value=proxy), \
                mock.patch.object(sandbox_proxies, "resource_exists", return_value=True), \
                mock.patch.object(sandbox_proxies, "resource_presence",
                                  return_value=sandbox_proxies.ResourcePresence.OWNED), \
                mock.patch.object(sandbox_proxies, "remove_owned_resource", side_effect=remove), \
                mock.patch.object(sandbox_proxies.ResourceRegistry, "RETRY_DELAYS", ()):
            result = sandbox_proxies._proxy_registry(mock.Mock(provider="container"), proxy).cleanup(0)

        self.assertFalse(result.remaining)
        self.assertLess(removed.index("zulip-caddy"), removed.index("zulip-application"))

    def test_absent_auth_container_does_not_make_recovery_fail_forever(self) -> None:
        managed = {
            "name": "example", "container": "container", "volume": "volume",
            "image": "sha256:" + "1" * 64, "service-owner": "a" * 32,
            "implementation-identity": "sha256:" + "0" * 64, "state-schema": 1,
            "lifecycle-state": "failed",
            "identity-parameters": {"uid": 501, "gid": 20, "network": "none"},
            "resource-status": {"volume": "absent", "container": "absent", "forward": "absent"},
        }
        owner = mock.Mock(provider="container")
        owner.run.return_value = subprocess.CompletedProcess([], 0, stdout="", stderr="")
        state = {"runtime": {"provider": "container"}, "proxies": [managed],
                 "auth": {"container": "already-removed", "key": "legacy-key", "image": "helper"}}
        with mock.patch.object(sandbox_proxies, "state_runtime", return_value=owner), \
                mock.patch.object(sandbox_proxies, "_cleanup_proxy_service"):
            sandbox_proxies.stop_state(state)
        self.assertFalse(any(call.args[0][:1] == ["rm"] for call in owner.run.call_args_list))

    def test_managed_recovery_rejects_changed_owner_before_cleanup(self) -> None:
        proxy = {
            "name": "example", "container": "container", "volume": "volume",
            "image": "sha256:" + "1" * 64,
            "service-owner": "a" * 32, "volume-owner": "b" * 32,
            "implementation-identity": "sha256:" + "0" * 64, "state-schema": 1,
            "lifecycle-state": "failed",
            "identity-parameters": {"uid": 501, "gid": 20, "network": "none"},
            "resource-status": {"volume": "created", "container": "created", "forward": "absent"},
        }
        with mock.patch.object(sandbox_proxies, "state_runtime") as runtime:
            with self.assertRaisesRegex(sandbox_proxies.ConfigError, "owner changed"):
                sandbox_proxies.stop_state({"proxies": [proxy]})
        runtime.assert_not_called()

    def test_start_failure_cancels_and_joins_workers_before_cleanup(self) -> None:
        args = SimpleNamespace(repo=str(self.repo), manifest=str(self.repo / "manifest"),
                               state=str(self.repo / "state"))
        manifest = {"commands": {"fast": {}, "slow": {}}}
        released = threading.Event()
        slow_started = threading.Event()
        events = []

        def start(*call_args, **kwargs):
            name = call_args[-2]
            if name == "fast":
                self.assertTrue(slow_started.wait(2))
                raise KeyboardInterrupt()
            registry = sandbox_proxies.ResourceRegistry("a" * 32)
            registry.register(sandbox_proxies.OwnedResource(
                "volume:owned", "a" * 32,
                lambda: sandbox_proxies.ResourcePresence.OWNED,
                lambda: events.append("removed"),
            ))
            kwargs["handles"].append(
                sandbox_proxies.CommandProxyHandle(mock.Mock(), registry, {"name": "slow"})
            )
            slow_started.set()
            self.assertTrue(kwargs["cancelled"].wait(2))
            events.append("joined")
            released.set()
            raise RuntimeError("cancelled")

        with mock.patch.object(sandbox_proxies, "load_manifest_file", return_value=manifest), \
                mock.patch.object(sandbox_proxies, "resolve_images", return_value={}), \
                mock.patch.object(sandbox_proxies, "runtime_identity", return_value={"provider": "container"}), \
                mock.patch.object(sandbox_proxies, "repository_identity", return_value="repository"), \
                mock.patch.object(sandbox_proxies, "start_one_proxy", side_effect=start), \
                mock.patch.object(sandbox_proxies, "stop_state", side_effect=lambda state: events.append("cleanup")):
            with self.assertRaises(KeyboardInterrupt):
                sandbox_proxies.start_main(args)
        self.assertTrue(released.is_set())
        self.assertEqual(["joined", "removed"], events)

    def test_proxy_stop_ignores_empty_state_file(self) -> None:
        state = self.repo / "state"
        state.touch()
        args = type("Args", (), {"state": str(state)})
        with mock.patch.object(sandbox_proxies, "stop_state") as stop:
            self.assertEqual(0, sandbox_proxies.stop_main(args))
        stop.assert_not_called()

    def test_proxy_logs_are_bounded_and_include_stderr(self) -> None:
        completed = subprocess.CompletedProcess([], 1, stdout="proxy failure\n")
        with mock.patch.object(sandbox_proxies.subprocess, "run", return_value=completed) as run:
            self.assertEqual("proxy failure", sandbox_proxies.proxy_logs("proxy-jj"))
        self.assertEqual(
            ["docker", "logs", "--tail", "200", "proxy-jj"],
            run.call_args.args[0],
        )
        self.assertEqual(sandbox_proxies.subprocess.STDOUT, run.call_args.kwargs["stderr"])


if __name__ == "__main__":
    unittest.main()
