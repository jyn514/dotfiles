from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "lib" / "sandbox-proxies.py"
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

    def tearDown(self) -> None:
        self.temporary.cleanup()

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
        arguments = sandbox_proxies.proxy_repository_mount_args(self.repo, "jj", command)
        mounts = arguments[1::2]
        self.assertIn(
            f"type=bind,src={self.repo.resolve()},dst=/src/work,bind-nonrecursive=true",
            mounts,
        )
        self.assertNotIn(
            f"type=bind,src={self.repo.resolve()},dst=/src/work,readonly,bind-nonrecursive=true",
            mounts,
        )

    def test_linked_worktree_keeps_repository_at_agent_path(self) -> None:
        main = self.repo
        worktree = Path(self.temporary.name + "-worktree")
        self.addCleanup(shutil.rmtree, worktree, True)
        (main / "tracked").write_text("tracked", encoding="utf-8")
        subprocess.run(["git", "-C", str(main), "add", "tracked"], check=True)
        subprocess.run([
            "git", "-C", str(main), "-c", "user.name=Test", "-c", "user.email=test@example.com",
            "commit", "--quiet", "-m", "initial",
        ], check=True)
        subprocess.run(["git", "-C", str(main), "worktree", "add", "--quiet", str(worktree)], check=True)
        (worktree / ".jj" / "repo").mkdir(parents=True)
        command = self.command(mounts=[{"source": ".", "target": ".", "proxy": "read-write"}])
        arguments = sandbox_proxies.proxy_repository_mount_args(worktree, "jj", command)
        self.assertIn(
            f"type=bind,src={worktree.resolve()},dst=/src/work,bind-nonrecursive=true",
            arguments,
        )
        common_dir = sandbox_proxies.git_metadata_paths(worktree)[1]
        target = sandbox_proxies.jj_container_path(worktree, common_dir)
        self.assertIn(f"type=bind,src={common_dir},dst={target}", arguments)

    def test_external_jj_repository_pointer_mounts_only_metadata(self) -> None:
        external = Path(self.temporary.name + "-jj-repo")
        external.mkdir()
        self.addCleanup(shutil.rmtree, external, True)
        shutil.rmtree(self.repo / ".jj" / "repo")
        relative = os.path.relpath(external, self.repo / ".jj")
        (self.repo / ".jj" / "repo").write_text(relative + "\n", encoding="utf-8")
        command = self.command(mounts=[{"source": ".", "target": ".", "proxy": "read-write"}])
        arguments = sandbox_proxies.proxy_repository_mount_args(self.repo, "jj", command)
        self.assertIn(
            f"type=bind,src={self.repo.resolve()},dst=/src/work,bind-nonrecursive=true",
            arguments,
        )
        target = sandbox_proxies.jj_container_path(self.repo, external)
        self.assertIn(f"type=bind,src={external.resolve()},dst={target}", arguments)
        self.assertNotIn(f"src={self.repo.parent},dst=/src/work", " ".join(arguments))

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
            "repo": str(self.repo), "state": str(state), "output": str(output),
            "manifest": str(self.sandbox / "proxy-commands.json"),
        })
        sandbox_proxies.agent_args_main(args)
        generated = output.read_text(encoding="utf-8")
        self.assertIn("SANDBOX_PROXY_DIR=/run/sandbox-proxies", generated)
        self.assertIn("src=shared-example,dst=/run/sandbox-proxies/example,readonly", generated)
        self.assertIn("dst=/run/sandbox-proxies/example,readonly", generated)
        self.assertIn("dst=/src/work/state,readonly", generated)
        self.assertIn("/src/work/secret:ro,noexec", generated)
        self.assertNotIn("src=" + str(self.repo / ".git"), generated)

    def test_local_router_accepts_option_separator(self) -> None:
        self.write({"example": self.command()})
        stale = sandbox_proxies.runtime_directory(self.repo) / "session.json"
        stale.write_text("{}", encoding="utf-8")
        args = type("Args", (), {
            "repo": str(self.repo), "command": "example", "wait": 0.1,
            "local": ["--", "/bin/sh", "-c", "exit 7"],
        })
        self.assertEqual(7, sandbox_proxies.route_main(args))
        self.assertFalse(stale.exists())

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
            self.assertFalse(metadata.exists())
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
            "repository": sandbox_proxies.repository_identity(self.repo),
            "commands": {}, "state": shared_state, "manifest": shared_manifest,
        }), encoding="utf-8")
        state = self.repo / "attached-state"
        manifest = self.repo / "attached-manifest"
        session = self.repo / "attached-session"
        session.write_text("shared\n", encoding="utf-8")
        args = type("Args", (), {
            "repo": str(self.repo), "session": str(session),
            "state": str(state), "manifest": str(manifest),
        })
        with mock.patch.object(sandbox_proxies, "start_main") as start, \
                mock.patch.object(sandbox_proxies, "publish_main") as publish:
            self.assertEqual(0, sandbox_proxies.attach_main(args))
        start.assert_not_called()
        publish.assert_not_called()
        self.assertEqual(shared_state, json.loads(state.read_text(encoding="utf-8")))
        self.assertEqual(shared_manifest, json.loads(manifest.read_text(encoding="utf-8")))

    def test_attach_does_not_replace_invalid_active_session(self) -> None:
        self.write()
        session = self.repo / "attached-session"
        session.write_text("shared\n", encoding="utf-8")
        args = type("Args", (), {
            "repo": str(self.repo), "session": str(session),
            "state": str(self.repo / "state"), "manifest": str(self.repo / "manifest"),
        })
        with mock.patch.object(sandbox_proxies, "start_main") as start:
            with self.assertRaisesRegex(sandbox_proxies.ConfigError, "missing or invalid"):
                sandbox_proxies.attach_main(args)
        start.assert_not_called()

    def test_proxy_monitor_removes_agent_when_proxy_stops(self) -> None:
        state = self.repo / "state"
        state.write_text(json.dumps({"proxies": [{
            "name": "example", "container": "proxy", "volume": "volume", "image": "sha256:" + "0" * 64,
        }]}), encoding="utf-8")
        running = subprocess.CompletedProcess([], 0, stdout="true\n")

        class WaitProcess:
            def __init__(self, arguments: list[str], **_: object) -> None:
                read_fd, self.write_fd = os.pipe()
                self.stdout = os.fdopen(read_fd, "r", encoding="utf-8")
                if arguments[-1] == "proxy":
                    os.close(self.write_fd)
                    self.write_fd = -1

            def terminate(self) -> None:
                if self.write_fd != -1:
                    os.close(self.write_fd)
                    self.write_fd = -1

            def wait(self) -> int:
                return 0

        with mock.patch.object(sandbox_proxies.subprocess, "run", return_value=running) as run, \
                mock.patch.object(sandbox_proxies.subprocess, "Popen", WaitProcess):
            args = type("Args", (), {"state": str(state), "agent": "agent"})
            self.assertEqual(1, sandbox_proxies.monitor_main(args))
        self.assertEqual(["docker", "rm", "--force", "agent"], run.call_args_list[-1].args[0])

    def test_proxy_stop_kills_before_removing_container(self) -> None:
        state = {"proxies": [{
            "name": "example", "container": "proxy", "volume": "volume",
            "image": "sha256:" + "0" * 64,
        }]}
        with mock.patch.object(sandbox_proxies.subprocess, "run") as run:
            sandbox_proxies.stop_state(state)
        self.assertEqual([
            ["docker", "kill", "proxy"],
            ["docker", "rm", "proxy"],
            ["docker", "volume", "rm", "volume"],
        ], [call.args[0] for call in run.call_args_list])

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
