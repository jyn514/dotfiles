from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
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
        args = type("Args", (), {
            "repo": str(self.repo), "prefix": "session", "output": str(output),
            "manifest": str(self.sandbox / "proxy-commands.json"),
        })
        sandbox_proxies.agent_args_main(args)
        generated = output.read_text(encoding="utf-8")
        self.assertIn("SANDBOX_PROXY_DIR=/run/sandbox-proxies", generated)
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
        args = type("Args", (), {"repo": str(self.repo), "output": str(snapshot)})
        sandbox_proxies.snapshot_main(args)
        self.write()
        self.assertIn("example", sandbox_proxies.load_manifest_file(snapshot)["commands"])

    def test_lock_holder_exits_when_launcher_owner_is_absent(self) -> None:
        self.write()
        ready = self.repo / "ready"
        release = self.repo / "release"
        result = subprocess.run([
            sys.executable, str(MODULE_PATH), "hold-lock", "--repo", str(self.repo),
            "--ready", str(ready), "--release", str(release), "--parent-pid", "1",
        ], timeout=2)
        self.assertEqual(0, result.returncode)
        self.assertTrue(ready.exists())

    def test_proxy_monitor_removes_agent_when_proxy_stops(self) -> None:
        state = self.repo / "state"
        state.write_text(json.dumps({"proxies": [{
            "name": "example", "container": "proxy", "volume": "volume", "image": "sha256:" + "0" * 64,
        }]}), encoding="utf-8")
        running = subprocess.CompletedProcess([], 0, stdout="true\n")
        stopped = subprocess.CompletedProcess([], 0, stdout="false\n")
        removed = subprocess.CompletedProcess([], 0, stdout="")
        with mock.patch.object(sandbox_proxies.subprocess, "run", side_effect=[running, running, stopped, removed]) as run:
            args = type("Args", (), {"state": str(state), "agent": "agent"})
            self.assertEqual(1, sandbox_proxies.monitor_main(args))
        self.assertEqual(["docker", "rm", "--force", "agent"], run.call_args_list[-1].args[0])


if __name__ == "__main__":
    unittest.main()
