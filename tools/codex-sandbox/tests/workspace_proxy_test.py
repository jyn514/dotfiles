"""Accepted workspace authority reaches only the JJ service and its live mounts."""

from copy import deepcopy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock


DIRECTORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DIRECTORY))
SPEC = importlib.util.spec_from_file_location("workspace_proxy_helpers", DIRECTORY / "sandbox-proxies.py")
helpers = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(helpers)


class WorkspaceProxyTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.home = self.root / "home"
        (self.home / "src").mkdir(parents=True)
        self.environment = mock.patch.dict(os.environ, {"HOME": str(self.home)})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.records = [self.record(self.home / "src/project", "/src/project"),
                        self.record(self.root / "external-dotfiles", "/src/dotfiles-2")]
        self.repo = Path(self.records[0]["host_root"])
        self.authority = self.root / "workspaces.json"
        self.authority.write_text(json.dumps(self.records))

    def record(self, repo, guest):
        jj = os.environ.get("DOTFILES_TEST_JJ_REAL", "jj")
        subprocess.run([jj, "git", "init", "--colocate", str(repo)], cwd=self.root,
                       check=True, capture_output=True)
        backing = repo / ".jj/repo"
        lock = self.home / ".cache/codex-sandbox-proxies/request-locks" / (
            hashlib.sha256(os.fsencode(backing)).hexdigest() + ".lock")
        lock.parent.mkdir(parents=True, exist_ok=True)
        lock.touch()
        return {"host_root": str(repo), "guest_root": guest, "git_dir": str(repo / ".git"),
                "common_dir": str(repo / ".git"), "jj_repo": str(backing), "lock_file": str(lock)}

    def proxy(self):
        owner = "a" * 32
        return {"name": "jj", "volume": "test-jj", "container": "test-jj",
                "image": "sha256:" + "0" * 64, "service-owner": owner,
                "implementation-identity": "sha256:" + "1" * 64,
                "state-schema": 1, "lifecycle-state": "ready",
                "identity-parameters": {"uid": 501, "gid": 20, "network": "none"},
                "resource-status": {"volume": "created", "container": "created", "forward": "absent",
                                    "source-view": "created"},
                "workspaces": deepcopy(self.records),
                "workspace-source-view": str(self.home / ".cache/codex-sandbox-proxies" /
                    ("b" * 64) / ("jj-source-view-" + owner))}

    def metadata(self, *, authorized=True):
        proxy = self.proxy()
        if not authorized:
            del proxy["workspaces"], proxy["workspace-source-view"]
            del proxy["resource-status"]["source-view"]
        service = helpers._service_record("jj", proxy, {"provider": "container"})
        command = {"image-command": [".agents/sandbox/build-jj"], "argv": ["jj-proxy", "serve"],
                   "workdir": ".", "network": False, "mounts": []}
        accepted = {"policy": {"version": 1, "commands": {"jj": command}}, "source-present": True,
                    "broker-roles": [], "images": {"agent": "agent", "helper": None,
                    "services": {"jj": proxy["image"]}}, "image-bound-parameters": {"uid": 501, "gid": 20}}
        if authorized:
            accepted["workspaces"] = deepcopy(self.records)
        return {"version": 4, "repository": helpers.repository_identity(self.repo),
                "container_repository": "/src/project", "runtime-owner": {"provider": "container"},
                "accepted": accepted, "services": {"jj": service}}

    def test_authority_rejects_duplicate_or_nonactive_roots(self):
        args = SimpleNamespace(workspaces=self.authority, repo=self.repo, container_repo="/src/project")
        self.assertEqual(self.records, helpers.requested_workspaces(args))
        with self.assertRaisesRegex(helpers.ConfigError, "duplicate"):
            helpers.workspace_records([self.records[0], self.records[0]])
        args.container_repo = "/src/other"
        with self.assertRaisesRegex(helpers.ConfigError, "active repository"):
            helpers.requested_workspaces(args)

    def test_persisted_authority_can_be_read_after_sources_disappear(self):
        for record in self.records:
            record["host_root"] += "-removed"
        self.assertEqual(self.records, helpers.workspace_records(self.records))

    def test_schema_binds_session_and_service_to_the_same_workspaces(self):
        envelope = self.metadata()
        helpers._accepted_schema4(envelope, expected_parameters={"uid": 501, "gid": 20})
        envelope["services"]["jj"]["recovery"]["workspaces"] = self.records[:1]
        with self.assertRaisesRegex(helpers.ConfigError, "workspace authority differs"):
            helpers._accepted_schema4(envelope, expected_parameters={"uid": 501, "gid": 20})

    def test_join_cannot_promote_an_old_session_by_adding_worker_mounts(self):
        args = SimpleNamespace(workspaces=self.authority, repo=self.repo, container_repo="/src/project", uid=501, gid=20)
        with self.assertRaisesRegex(helpers.ConfigError, "workspace authority changed"):
            helpers.accepted_session(args, self.repo, self.metadata(authorized=False))

    def mounts(self):
        staging = self.root / "staging"
        staging.mkdir(exist_ok=True)
        with mock.patch.object(helpers.OUTER_RUNTIME, "nonrecursive_bind", "bind-nonrecursive=true"):
            args = helpers.shared_workspace_mount_args(self.records, staging)
        return [dict(field.split("=", 1) for field in arg.split(",") if "=" in field)
                | {"RW": "readonly" not in arg.split(",")} for arg in args[1::2]]

    def snapshot(self):
        return {"Config": {"Env": ["JJ_PROXY_REPO=/src/project", "JJ_PROXY_WORKSPACES=" + helpers.workspace_environment(self.records)]},
                "Mounts": [{"Destination": item["dst"], "Source": item["src"], "RW": item["RW"]}
                           for item in self.mounts()]}

    def test_missing_dotfiles_destination_is_scaffolded_without_host_placeholders(self):
        snapshot = self.snapshot()
        self.assertFalse((self.home / "src/dotfiles-2").exists())
        for record in self.records:
            worktree = next(item for item in snapshot["Mounts"] if item["Destination"] == record["guest_root"])
            self.assertEqual(record["host_root"], worktree["Source"])
            self.assertTrue(worktree["RW"])
        self.assertFalse(next(item for item in snapshot["Mounts"] if item["Destination"] == "/src")["RW"])
        helpers.validate_workspace_snapshot(self.proxy(), snapshot)

    def test_live_authority_rejects_changed_environment_and_mount_permissions(self):
        expected = self.snapshot()
        for mutation in ("environment", "readonly", "missing", "extra"):
            snapshot = deepcopy(expected)
            if mutation == "environment":
                snapshot["Config"]["Env"] = ["JJ_PROXY_WORKSPACES=[]"]
            elif mutation == "readonly":
                next(item for item in snapshot["Mounts"] if item["Destination"] == "/src/project")["RW"] = False
            elif mutation == "missing":
                snapshot["Mounts"] = [item for item in snapshot["Mounts"] if item["Destination"] != "/src/dotfiles-2"]
            else:
                snapshot["Mounts"].append({"Source": "/outside", "Destination": "/src/unlisted", "RW": True})
            with self.subTest(mutation=mutation), self.assertRaises(helpers.ConfigError):
                helpers.validate_workspace_snapshot(self.proxy(), snapshot)

    def test_recovery_cannot_remove_an_unrelated_directory_as_its_scaffold(self):
        proxy = self.proxy()
        helpers._managed_proxy_record(proxy)
        proxy["workspace-source-view"] = str(self.root)
        with self.assertRaisesRegex(helpers.ConfigError, "recovery path"):
            helpers._managed_proxy_record(proxy)

    def test_jj_startup_and_readiness_share_the_configured_lock_wait_budget(self):
        runtime = helpers.runtime_directory(self.repo)
        args = SimpleNamespace(_workspace_records=self.records, prefix="fixture", state=self.root / "state.json",
                               repo=str(self.repo), container_repo="/src/project", network="none")
        command = {"argv": ["jj-proxy", "serve"], "workdir": ".", "network": False, "mounts": []}
        clock = iter(range(0, 1000, 11))
        not_ready = subprocess.CompletedProcess([], 125, stderr="waiting for startup lock")
        ready = subprocess.CompletedProcess([], 0, stderr="")
        with mock.patch.object(helpers, "runtime_directory", return_value=runtime), \
                mock.patch.object(helpers, "_docker", return_value=SimpleNamespace(stdout="true")) as docker, \
                mock.patch.object(helpers.subprocess, "run", side_effect=[not_ready, ready]) as transport, \
                mock.patch.object(helpers.time, "monotonic", side_effect=lambda: next(clock)), \
                mock.patch.object(helpers.time, "sleep"), \
                mock.patch.object(helpers, "JJ_STARTUP_TIMEOUT_SECONDS", 31):
            proxy = helpers.start_one_proxy(args, self.repo, "repository", {"jj": "sha256:" + "0" * 64},
                                             {"proxies": []}, __import__("threading").Lock(), "jj", command)
        self.assertEqual("ready", proxy["lifecycle-state"])
        self.assertEqual(2, transport.call_count)
        run = next(call.args for call in docker.call_args_list if call.args[0] == "run")
        self.assertIn("JJ_PROXY_STARTUP_TIMEOUT_SECS=31", run)
        self.assertGreater(transport.call_args.kwargs["timeout"], 0)

    def test_scaffold_cleanup_preserves_persistent_request_locks(self):
        proxy = self.proxy()
        staging = Path(proxy["workspace-source-view"])
        staging.mkdir(parents=True)
        (staging / "placeholder").touch()
        runtime = helpers.ContainerRuntime()
        def absent(arguments, **kwargs):
            self.assertIn(arguments[0], ("container", "volume"))
            if arguments[1] == "inspect":
                return SimpleNamespace(returncode=125, stdout="")
            self.assertEqual("ls", arguments[1], "absent resources must not be removed")
            return SimpleNamespace(returncode=0, stdout="")
        runtime.run = mock.Mock(side_effect=absent)
        result = helpers._proxy_registry(runtime, proxy).cleanup(0)
        self.assertEqual([["container", "inspect"], ["container", "ls"],
                          ["volume", "inspect"], ["volume", "ls"]],
                         [call.args[0][:2] for call in runtime.run.call_args_list])
        self.assertEqual((), result.remaining)
        self.assertFalse(staging.exists())
        self.assertTrue(all(Path(record["lock_file"]).is_file() for record in self.records))


if __name__ == "__main__":
    unittest.main()
