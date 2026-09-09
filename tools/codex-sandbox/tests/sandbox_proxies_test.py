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


class ManifestTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.repo = Path(self.temporary.name)
        subprocess.run(["git", "init", "--quiet", str(self.repo)], check=True)
        (self.repo / ".jj" / "repo").mkdir(parents=True)
        self.sandbox = self.repo / ".agents" / "sandbox"
        self.sandbox.mkdir(parents=True)
        self.container_repo = Path("/src/example")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_explicit_arguments_preserve_caller_argv_and_report_errors(self) -> None:
        output = self.repo / "snapshot.json"
        arguments = ["snapshot", "--repo", str(self.repo), "--output", str(output)]
        with mock.patch.object(sys, "argv", ["caller", "unrelated-argument"]):
            self.assertEqual(0, sandbox_proxies.main(arguments))
            self.assertEqual({"version": 1, "commands": {}}, json.loads(output.read_text()))
            self.assertEqual(["caller", "unrelated-argument"], sys.argv)
            (self.sandbox / "proxy-commands.json").write_text("invalid JSON")
            with mock.patch("sys.stderr", new_callable=io.StringIO) as stderr:
                self.assertEqual(1, sandbox_proxies.main(arguments))
                self.assertIn("sandbox proxies:", stderr.getvalue())

    def write(self, commands: dict = None, **extra: object) -> None:
        manifest = {"version": 1, "commands": commands or {}, **extra}
        (self.sandbox / "proxy-commands.json").write_text(json.dumps(manifest), encoding="utf-8")

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

    def test_accepts_proxy_only_writable_repository_mount(self) -> None:
        self.write({"example": self.command(mounts=[{
            "source": ".", "target": ".", "proxy": "read-write",
        }])})
        mount = sandbox_proxies.load_manifest(self.repo)["commands"]["example"]["mounts"][0]
        self.assertEqual("read-write", mount["proxy"])

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
        target = sandbox_proxies.jj_container_path(
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
            sandbox_proxies.jj_container_path(
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
        target = sandbox_proxies.jj_container_path(
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
            {"source": ".git", "target": ".git"},
        ])})
        output = self.repo / "args"
        state = self.repo / "state"
        state.write_text(json.dumps({"proxies": [{
            "name": "example", "volume": "shared-example",
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
        self.assertNotIn("src=" + str(self.repo / ".git"), generated)

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
        state.write_text(json.dumps({"proxies": [
            {"name": name, "container": name, "image": "immutable"} for name in ("first", "second")]}))
        manifest = self.repo / "manifest.json"
        manifest.write_text('{"version":1,"commands":{}}')
        args = SimpleNamespace(repo=str(self.repo), state=str(state), manifest=str(manifest),
                               container_repo=str(self.container_repo))
        rendezvous = threading.Barrier(2)

        def validate(*_args):
            self.assertFalse((self.repo / "session.json").exists())
            rendezvous.wait(timeout=2)

        with mock.patch.object(sandbox_proxies, "runtime_directory", return_value=self.repo), \
                mock.patch.object(sandbox_proxies, "validate_live_proxy", side_effect=validate):
            self.assertEqual(0, sandbox_proxies.publish_main(args))
        metadata = json.loads((self.repo / "session.json").read_text())
        self.assertEqual({"first", "second"}, set(metadata["commands"]))

    def test_failed_publication_waits_for_other_checks_and_keeps_old_metadata(self) -> None:
        state = self.repo / "state.json"
        state.write_text(json.dumps({"proxies": [
            {"name": name, "container": name, "image": "immutable"} for name in ("bad", "slow")]}))
        manifest = self.repo / "manifest.json"
        manifest.write_text('{"version":1,"commands":{}}')
        published = self.repo / "session.json"
        published.write_text("previous metadata")
        args = SimpleNamespace(repo=str(self.repo), state=str(state), manifest=str(manifest),
                               container_repo=str(self.container_repo))
        started, failed, release, finished = (threading.Event() for _ in range(4))

        def validate(_owner, proxy, *_args):
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

    def test_local_zulip_falls_back_when_active_session_has_no_proxy(self) -> None:
        self.write()
        runtime = sandbox_proxies.runtime_directory(self.repo)
        (runtime / "session.json").write_text(json.dumps({
            "version": 1,
            "repository": sandbox_proxies.repository_identity(self.repo),
            "commands": {}, "state": {"proxies": []},
            "manifest": {"version": 1, "commands": {}},
        }), encoding="utf-8")
        args = type("Args", (), {
            "repo": str(self.repo), "command": "zulip", "wait": 0.1,
            "local": ["--", "/bin/sh", "-c", "exit 7"],
        })
        with (runtime / "session.lock").open("a+b") as lock:
            fcntl.flock(lock, fcntl.LOCK_SH)
            self.assertEqual(7, sandbox_proxies.route_main(args))

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

    def test_zulip_can_start_before_its_socket_is_ready(self) -> None:
        zuliprc = self.repo / "zuliprc"
        zuliprc.write_text("secret", encoding="utf-8")
        zuliprc.chmod(0o600)
        args = type("Args", (), {
            "prefix": "test", "state": str(self.repo / "state"), "network": "sandbox",
            "container_repo": str(self.container_repo), "zuliprc": str(zuliprc),
        })
        image = "sha256:" + "0" * 64
        state = {"proxies": []}
        running = subprocess.CompletedProcess([], 0, stdout="true\n")
        not_ready = subprocess.CompletedProcess([], 1, stderr="socket not ready\n")
        with mock.patch.object(sandbox_proxies, "_docker", return_value=running), \
                mock.patch.object(sandbox_proxies.subprocess, "run", return_value=not_ready), \
                mock.patch.object(sandbox_proxies, "proxy_logs", return_value=""), \
                mock.patch.object(sandbox_proxies.time, "monotonic", side_effect=[0, 0, 11]), \
                mock.patch.object(sandbox_proxies.time, "sleep"):
            proxy = sandbox_proxies.start_one_proxy(
                args, self.repo, "identity", {"zulip": image}, state,
                mock.MagicMock(), "zulip", self.command(argv=["zulip-proxy"], network=True),
            )
        self.assertEqual("zulip", proxy["name"])
        self.assertEqual([proxy], state["proxies"])

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

    def test_lock_holder_exits_when_launcher_owner_is_absent(self) -> None:
        self.write()
        ready = self.repo / "ready"
        coordinated = self.repo / "coordinated"
        release = self.repo / "release"
        result = subprocess.run([
            sys.executable, str(MODULE_PATH), "hold-lock", "--repo", str(self.repo),
            "--ready", str(ready), "--coordinated", str(coordinated),
            "--release", str(release), "--parent-pid", "1",
        ], timeout=2)
        self.assertEqual(0, result.returncode)
        self.assertTrue(ready.exists())

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

    def test_lock_holders_share_one_repository_session(self) -> None:
        self.write()
        runtime = sandbox_proxies.runtime_directory(self.repo)
        metadata = runtime / "session.json"
        processes = []
        controls = []
        try:
            for index in range(2):
                ready = self.repo / f"ready-{index}"
                coordinated = self.repo / f"coordinated-{index}"
                release = self.repo / f"release-{index}"
                process = subprocess.Popen([
                    sys.executable, str(MODULE_PATH), "hold-lock", "--repo", str(self.repo),
                    "--ready", str(ready), "--coordinated", str(coordinated),
                    "--release", str(release), "--parent-pid", str(os.getpid()),
                ])
                processes.append(process)
                controls.append((ready, coordinated, release))
                deadline = time.monotonic() + 2
                while not ready.exists() and time.monotonic() < deadline:
                    time.sleep(0.01)
                self.assertTrue(ready.exists())
                if index == 0:
                    metadata.write_text(json.dumps({
                        "version": 1,
                        "repository": sandbox_proxies.repository_identity(self.repo),
                        "state": {"proxies": []}, "commands": {},
                        "manifest": {"version": 1, "commands": {}},
                    }), encoding="utf-8")
                coordinated.touch()

            controls[0][2].touch()
            self.assertEqual(0, processes[0].wait(timeout=2))
            self.assertTrue(metadata.exists())
            controls[1][2].touch()
            self.assertEqual(0, processes[1].wait(timeout=2))
            self.assertTrue(metadata.exists())
        finally:
            for _, coordinated, release in controls:
                coordinated.touch()
                release.touch()
            for process in processes:
                if process.poll() is None:
                    process.terminate()
                    process.wait(timeout=2)

    def test_attach_reuses_published_proxy_state_and_manifest(self) -> None:
        self.write({"example": self.command()})
        runtime = sandbox_proxies.runtime_directory(self.repo)
        shared_state = {"proxies": [{
            "name": "example", "volume": "shared-example", "container": "shared-example",
            "image": "sha256:" + "0" * 64,
        }]}
        shared_manifest = sandbox_proxies.serializable_manifest(
            sandbox_proxies.load_manifest(self.repo)
        )
        (runtime / "session.json").write_text(json.dumps({
            "version": 1,
            "repository": sandbox_proxies.repository_identity(self.repo),
            "container_repository": str(self.container_repo),
            "commands": {}, "state": shared_state, "manifest": shared_manifest,
        }), encoding="utf-8")
        state = self.repo / "attached-state"
        manifest = self.repo / "attached-manifest"
        manifest.write_text(json.dumps(shared_manifest), encoding="utf-8")
        session = self.repo / "attached-session"
        session.write_text("shared\n", encoding="utf-8")
        args = type("Args", (), {
            "repo": str(self.repo), "container_repo": str(self.container_repo),
            "session": str(session), "state": str(state), "manifest": str(manifest),
        })
        with mock.patch.object(sandbox_proxies, "start_main") as start, \
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
        state = {"runtime": {"provider": "podman"}, "proxies": [
            {"container": "owned-container", "volume": "owned-volume"}]}
        owner = mock.Mock()
        owner.run.return_value = subprocess.CompletedProcess([], 0, stdout="")
        with mock.patch.object(sandbox_proxies, "OUTER_RUNTIME") as current, \
                mock.patch.object(sandbox_proxies, "state_runtime", return_value=owner) as recorded:
            sandbox_proxies.stop_state(state)
        recorded.assert_called_once_with(state)
        current.run.assert_not_called()
        self.assertIn(["volume", "rm", "owned-volume"], [call.args[0] for call in owner.run.call_args_list])

    def test_reset_keeps_metadata_when_engine_reports_surviving_resources(self) -> None:
        self.write()
        metadata = sandbox_proxies.runtime_directory(self.repo) / "session.json"
        state = {"runtime": {"provider": "podman"}, "proxies": [{"container": "survivor", "volume": "owned-volume"}]}
        contents = json.dumps({"version": 2, "state": state})
        metadata.write_text(contents)
        owner = mock.Mock()
        owner.run.return_value = subprocess.CompletedProcess([], 0, stdout="survivor\n")
        with mock.patch.object(sandbox_proxies, "state_runtime", return_value=owner):
            with self.assertRaisesRegex(sandbox_proxies.ConfigError, "remain after cleanup"):
                sandbox_proxies.reset_main(type("Args", (), {"repo": str(self.repo)}))
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
                    "state": {"runtime": {"provider": "podman"}, "proxies": []}}
        args = type("Args", (), {"container_repo": str(self.container_repo)})
        with mock.patch.object(sandbox_proxies, "runtime_identity", return_value={"provider": "lima"}), \
                mock.patch.object(sandbox_proxies, "containers_running") as running:
            self.assertIsNone(sandbox_proxies.cached_session_state(args, self.repo, metadata, manifest))
        running.assert_not_called()

    def test_route_uses_published_owner_despite_different_current_default(self) -> None:
        self.write()
        directory = sandbox_proxies.runtime_directory(self.repo)
        state = {"runtime": {"provider": "podman"}, "proxies": []}
        (directory / "session.json").write_text(json.dumps({
            "version": 2, "repository": sandbox_proxies.repository_identity(self.repo),
            "state": state, "commands": {"example": {"container": "owned", "image": "immutable"}}}))
        owner = mock.Mock()
        repository = sandbox_proxies.repository_identity(self.repo)
        owner.forward_proxy.return_value = 7
        args = type("Args", (), {"repo": str(self.repo), "command": "example", "wait": 1, "local": ["local"]})
        with (directory / "session.lock").open("a+b") as lock:
            fcntl.flock(lock, fcntl.LOCK_SH)
            with mock.patch.object(sandbox_proxies, "OUTER_RUNTIME") as current, \
                    mock.patch.object(sandbox_proxies, "repository_identity", return_value=repository), \
                    mock.patch.object(sandbox_proxies, "state_runtime", return_value=owner) as recorded, \
                    mock.patch.object(sandbox_proxies, "validate_live_proxy") as validate:
                self.assertEqual(7, sandbox_proxies.route_main(args))
        recorded.assert_called_once_with(state)
        self.assertIs(owner, validate.call_args.args[0])
        current.forward_proxy.assert_not_called()
        owner.forward_proxy.assert_called_once_with("owned")

    def test_live_identity_requires_native_image_as_well_as_labels(self) -> None:
        owner = mock.Mock()
        owner.run.return_value.stdout = "true repository example\n"
        owner.container_matches_image.return_value = False
        proxy = {"container": "owned", "image": "immutable"}
        with self.assertRaisesRegex(sandbox_proxies.ConfigError, "native image"):
            sandbox_proxies.validate_live_proxy(owner, proxy, "repository", "example")
        owner.container_matches_image.return_value = True
        sandbox_proxies.validate_live_proxy(owner, proxy, "repository", "example")
        owner.run.return_value.stdout = "true another-repository example\n"
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
        session = self.repo / "session"
        session.write_text("new\n", encoding="utf-8")
        args = type("Args", (), {
            "repo": str(self.repo), "container_repo": str(self.container_repo),
            "session": str(session), "state": str(self.repo / "state"),
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

    def test_shared_session_rejects_changed_cached_proxies(self) -> None:
        self.write()
        runtime = sandbox_proxies.runtime_directory(self.repo)
        (runtime / "session.json").write_text(json.dumps({
            "version": 1,
            "repository": sandbox_proxies.repository_identity(self.repo),
            "state": {"proxies": []}, "manifest": {"version": 1, "commands": {"old": {}}},
        }), encoding="utf-8")
        session = self.repo / "session"
        session.write_text("shared\n", encoding="utf-8")
        manifest = self.repo / "manifest"
        manifest.write_text(json.dumps({"version": 1, "commands": {}}), encoding="utf-8")
        args = type("Args", (), {
            "repo": str(self.repo), "container_repo": str(self.container_repo),
            "session": str(session), "state": str(self.repo / "state"),
            "manifest": str(manifest),
        })
        with self.assertRaisesRegex(sandbox_proxies.ConfigError, "restart after active"):
            sandbox_proxies.attach_main(args)

    def test_attach_does_not_replace_invalid_active_session(self) -> None:
        self.write()
        session = self.repo / "attached-session"
        session.write_text("shared\n", encoding="utf-8")
        manifest = self.repo / "manifest"
        manifest.write_text(json.dumps({"version": 1, "commands": {}}), encoding="utf-8")
        args = type("Args", (), {
            "repo": str(self.repo), "container_repo": str(self.container_repo),
            "session": str(session), "state": str(self.repo / "state"),
            "manifest": str(manifest),
        })
        with mock.patch.object(sandbox_proxies, "start_main") as start:
            with self.assertRaisesRegex(sandbox_proxies.ConfigError, "changed or is unavailable"):
                sandbox_proxies.attach_main(args)
        start.assert_not_called()

    def test_proxy_monitor_removes_agent_when_shared_service_stops(self) -> None:
        cases = (
            ({"proxies": [{
                "name": "example", "container": "proxy", "volume": "volume",
                "image": "sha256:" + "0" * 64,
            }]}, "proxy"),
            ({"proxies": [], "auth": {"container": "auth-proxy", "key": "secret"}}, "auth-proxy"),
        )
        running = subprocess.CompletedProcess([], 0, stdout="true\n")
        for contents, stopped in cases:
            with self.subTest(stopped=stopped):
                state = self.repo / "state"
                state.write_text(json.dumps(contents), encoding="utf-8")

                class WaitProcess:
                    def __init__(self, arguments: list[str], **_: object) -> None:
                        read_fd, self.write_fd = os.pipe()
                        self.stdout = os.fdopen(read_fd, "r", encoding="utf-8")
                        if arguments[-1] == stopped:
                            os.close(self.write_fd)
                            self.write_fd = -1

                    def terminate(self) -> None:
                        if self.write_fd != -1:
                            os.close(self.write_fd)
                            self.write_fd = -1

                    def wait(self, **_kwargs) -> int:
                        return 0

                with mock.patch.object(sandbox_proxies.subprocess, "run", return_value=running) as run, \
                        mock.patch.object(sandbox_proxies.subprocess, "Popen", WaitProcess):
                    args = type("Args", (), {"state": str(state), "agent": "agent"})
                    self.assertEqual(1, sandbox_proxies.monitor_main(args))
                self.assertEqual(
                    ["docker", "rm", "--force", "agent"], run.call_args_list[-1].args[0],
                )

    def test_standalone_monitor_never_passes_agent_input_to_engine_children(self) -> None:
        state = self.repo / "monitor-state.json"
        state.write_text(json.dumps({"proxies": [{"name": "proxy", "container": "proxy"}]}))
        log = self.repo / "monitor-input.jsonl"
        result = subprocess.run([
            sys.executable, str(Path(__file__).with_name("monitor_stdin_fixture.py")),
            "monitor", str(state)], input="reserved for the agent", text=True,
            capture_output=True, timeout=10,
            env={**os.environ, "MONITOR_INPUT_LOG": str(log)})
        self.assertEqual(1, result.returncode, result.stderr)
        calls = [json.loads(line) for line in log.read_text().splitlines()]
        self.assertEqual({"inspect", "wait", "rm"}, {call["operation"] for call in calls})
        self.assertTrue(all(call["input"] == "" for call in calls), calls)

    def test_terminated_monitor_reaps_its_wait_children(self) -> None:
        state = self.repo / "monitor-state.json"
        state.write_text(json.dumps({"proxies": [{"name": "proxy", "container": "proxy"}]}))
        log = self.repo / "monitor-input.jsonl"
        process = subprocess.Popen([
            sys.executable, str(Path(__file__).with_name("monitor_stdin_fixture.py")),
            "monitor", str(state)], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            env={**os.environ, "MONITOR_INPUT_LOG": str(log), "MONITOR_STAY_RUNNING": "1"})
        children = []
        try:
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                if log.exists():
                    calls = [json.loads(line) for line in log.read_text().splitlines()]
                    children = [call["pid"] for call in calls if call["operation"] == "wait"]
                    if len(children) == 2:
                        break
                time.sleep(0.01)
            self.assertEqual(2, len(children))
            process.terminate()
            process.wait(timeout=5)
            calls = [json.loads(line) for line in log.read_text().splitlines()]
            self.assertNotIn("rm", [call["operation"] for call in calls])
            for child in children:
                with self.assertRaises(ProcessLookupError):
                    os.kill(child, 0)
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
            for child in children:
                try:
                    os.kill(child, 15)
                except ProcessLookupError:
                    pass

    def test_guest_monitor_distinguishes_cancellation_from_lost_supervision(self) -> None:
        for cancel in (False, True):
            with self.subTest(cancel=cancel):
                log = self.repo / f"guest-monitor-{cancel}.jsonl"
                process = subprocess.Popen([
                    sys.executable, str(Path(__file__).with_name("monitor_stdin_fixture.py")), "guest"],
                    stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                    env={**os.environ, "MONITOR_INPUT_LOG": str(log), "MONITOR_STAY_RUNNING": "1"})
                children = []
                try:
                    deadline = time.monotonic() + 5
                    while time.monotonic() < deadline:
                        if log.exists():
                            calls = [json.loads(line) for line in log.read_text().splitlines()]
                            children = [call["pid"] for call in calls if call["operation"] == "wait"]
                            if len(children) == 2:
                                break
                        time.sleep(0.01)
                    self.assertEqual(2, len(children))
                    if cancel:
                        process.stdin.write(b"q")
                    process.stdin.close()
                    process.wait(timeout=5)
                    self.assertEqual(143 if cancel else 1, process.returncode, process.stderr.read())
                    calls = [json.loads(line) for line in log.read_text().splitlines()]
                    self.assertEqual(not cancel, any(call["operation"] == "rm" for call in calls))
                    self.assertTrue(all(call["input"] == "" for call in calls))
                    for child in children:
                        with self.assertRaises(ProcessLookupError):
                            os.kill(child, 0)
                finally:
                    if process.poll() is None:
                        process.kill()
                        process.wait()
                    process.stdin.close()
                    process.stderr.close()
                    for child in children:
                        try:
                            os.kill(child, 15)
                        except ProcessLookupError:
                            pass

    def test_proxy_stop_kills_and_removes_containers_before_volumes(self) -> None:
        state = {
            "auth": {"container": "auth-proxy", "key": "secret"},
            "proxies": [{
                "name": "example", "container": "proxy", "volume": "volume",
                "image": "sha256:" + "0" * 64,
            }],
        }
        with mock.patch.object(sandbox_proxies.subprocess, "run") as run:
            sandbox_proxies.stop_state(state)
        calls = [call.args[0] for call in run.call_args_list]
        self.assertCountEqual([
            ["docker", "kill", "auth-proxy"],
            ["docker", "kill", "proxy"],
        ], calls[:2])
        self.assertCountEqual([
            ["docker", "rm", "auth-proxy"],
            ["docker", "rm", "proxy"],
        ], calls[2:4])
        self.assertEqual(["docker", "container", "ls", "--all", "--format", "{{.Names}}"], calls[4])
        self.assertEqual(["docker", "volume", "rm", "volume"], calls[5])
        self.assertEqual(["docker", "volume", "ls", "--format", "{{.Name}}"], calls[6])

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
