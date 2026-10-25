from __future__ import annotations

import importlib.util
import io
import json
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock


MODULE_PATH = Path(__file__).resolve().parents[1] / "sandbox-proxies.py"
SPEC = importlib.util.spec_from_file_location("tic_capability_sandbox_proxies", MODULE_PATH)
assert SPEC and SPEC.loader
sandbox_proxies = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(sandbox_proxies)


class TicCapabilityTest(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.repo = Path(temporary.name)
        subprocess.run(["git", "init", "--quiet", str(self.repo)], check=True)
        self.sandbox = self.repo / ".agents" / "sandbox"
        self.sandbox.mkdir(parents=True)
        self.path = self.sandbox / "proxy-commands.json"

    def write(self, data: dict) -> None:
        self.path.write_text(json.dumps(data), encoding="utf-8")

    def snapshot(self) -> dict:
        output = self.repo / "accepted.json"
        sandbox_proxies.snapshot_main(SimpleNamespace(
            repo=str(self.repo), output=str(output), jj_image_command=None,
        ))
        return json.loads(output.read_text(encoding="utf-8"))

    @staticmethod
    def command(version: int) -> dict:
        return {
            **({"image": "tickets"} if version == 2 else {"image-command": ["build-tickets"]}),
            "argv": ["ticket-proxy"], "workdir": ".", "network": False, "mounts": [],
        }

    def test_missing_and_omitted_policy_defaults_on_independent_of_host_tools(self) -> None:
        for source in (None, {"version": 1, "commands": {}},
                       {"version": 1, "commands": {}, "capabilities": {}},
                       {"version": 2}, {"version": 2, "capabilities": {}},
                       {"version": 2, "capabilities": {"host-editor": True}}):
            with self.subTest(source=source):
                if source is not None:
                    self.write(source)
                else:
                    self.path.unlink(missing_ok=True)
                with mock.patch.object(sandbox_proxies.shutil, "which", return_value="/host/bin/ti") as which:
                    snapshot = self.snapshot()
                which.assert_not_called()
                self.assertEqual({"zulip": True, "nested-containers": False,
                                  "flower-r2": False, "tic": True}, snapshot["capabilities"])
                self.assertEqual({}, snapshot["commands"])
                self.assertNotIn("host-editor", snapshot["capabilities"])
        self.write({"version": 2})
        self.assertTrue(sandbox_proxies.load_manifest(self.repo)["capabilities"]["tic"])

    def test_v1_accepts_tic_booleans_but_rejects_invalid_values(self) -> None:
        for selected in (True, False):
            self.write({"version": 1, "capabilities": {"tic": selected}, "commands": {}})
            self.assertEqual(selected, self.snapshot()["capabilities"]["tic"])
        for value in (None, 0, "false"):
            with self.subTest(value=value):
                self.write({"version": 1, "capabilities": {"tic": value}, "commands": {}})
                with mock.patch.object(sandbox_proxies, "write_atomic") as publish:
                    with self.assertRaisesRegex(sandbox_proxies.ConfigError, "invalid capabilities"):
                        self.snapshot()
                publish.assert_not_called()

    def test_v2_boolean_validation_and_existing_version_validation(self) -> None:
        for value in (None, 0, 1, "true", [], {}):
            with self.subTest(value=value):
                self.write({"version": 2, "capabilities": {"tic": value}})
                with self.assertRaisesRegex(sandbox_proxies.ConfigError, "invalid capabilities"):
                    sandbox_proxies.load_manifest(self.repo)
        for version in (True, "2", 0, 3):
            with self.subTest(version=version):
                self.write({"version": version, "commands": {}})
                with self.assertRaises(sandbox_proxies.ConfigError):
                    sandbox_proxies.load_manifest(self.repo)

    def test_accepted_policy_never_acquires_new_tic_default_or_changes_other_capabilities(self) -> None:
        for version in (1, 2):
            for capabilities in (None, {}, {"tic": False}, {"tic": True}):
                with self.subTest(version=version, capabilities=capabilities):
                    data = {"version": version, "commands": {}}
                    if capabilities is not None:
                        data["capabilities"] = capabilities
                    with mock.patch.object(Path, "read_text", side_effect=AssertionError("source read")):
                        accepted = sandbox_proxies.load_accepted_manifest(data=data)
                    expected = capabilities or {}
                    if version == 2:
                        expected = {"zulip": True, "nested-containers": False, "flower-r2": False, **expected}
                    self.assertEqual(expected, accepted.get("capabilities", {}))

    def test_explicit_false_wins_in_every_new_policy_producer(self) -> None:
        for version in (1, 2):
            with self.subTest(version=version):
                self.write({"version": version, "commands": {}, "capabilities": {"tic": False}})
                self.assertFalse(sandbox_proxies.load_manifest(self.repo)["capabilities"]["tic"])
                self.assertFalse(sandbox_proxies.load_optional_manifest(self.repo)["capabilities"]["tic"])
                self.assertFalse(self.snapshot()["capabilities"]["tic"])

    def test_boolean_roundtrips_and_join_authority_contains_no_tic_service(self) -> None:
        for selected in (True, False):
            with self.subTest(selected=selected):
                self.write({"version": 2, "capabilities": {"tic": selected, "zulip": False}})
                source = sandbox_proxies.load_manifest(self.repo)
                roundtrip = sandbox_proxies.load_accepted_manifest(
                    data=sandbox_proxies.serializable_manifest(source))
                self.assertEqual(source, roundtrip)
                snapshot = self.snapshot()
                self.assertEqual(1, snapshot["version"])
                self.assertEqual(selected, snapshot["capabilities"]["tic"])
                self.assertEqual({"version", "capabilities", "commands"}, set(snapshot))
                self.assertEqual({}, snapshot["commands"])
                envelope = {
                    "version": 4, "repository": "accepted-repository",
                    "container_repository": "/src/example", "runtime-owner": {"provider": "container"},
                    "accepted": {
                        "policy": snapshot, "source-present": True, "broker-roles": [],
                        "images": {"agent": "agent", "helper": None, "services": {}},
                        "image-bound-parameters": {"uid": 501, "gid": 20},
                    }, "services": {},
                }
                # A join consumes accepted policy, not a changed source or native tool discovery.
                self.path.write_text("malformed replacement", encoding="utf-8")
                with mock.patch.object(Path, "read_text", side_effect=AssertionError("source read")), \
                        mock.patch.object(sandbox_proxies.shutil, "which", side_effect=AssertionError("host discovery")):
                    services, accepted = sandbox_proxies._accepted_schema4(
                        envelope, expected_parameters={"uid": 501, "gid": 20})
                self.assertEqual({}, services)
                self.assertEqual(snapshot, sandbox_proxies.serializable_manifest(accepted["policy"]))
                self.assertEqual({}, accepted["images"]["services"])
                self.assertEqual([], accepted["broker-roles"])

    def test_project_tic_collision_only_when_capability_selected(self) -> None:
        for version in (1, 2):
            for selected in (None, False, True):
                with self.subTest(version=version, selected=selected):
                    data = {"version": version, "commands": {"tic": self.command(version)}}
                    if version == 2:
                        data["images"] = {"resolver": {"kind": "command", "argv": ["resolve"]}, "base": "base"}
                    if selected is not None:
                        data["capabilities"] = {"tic": selected}
                    self.write(data)
                    if selected is True:
                        with self.assertRaisesRegex(sandbox_proxies.ConfigError, "tic.*conflicts"):
                            sandbox_proxies.load_manifest(self.repo)
                    else:
                        with mock.patch("sys.stderr", new_callable=io.StringIO) as warning:
                            policy = sandbox_proxies.load_manifest(self.repo)
                            snapshot = self.snapshot()
                        self.assertIn("tic", policy["commands"])
                        self.assertFalse(policy["capabilities"]["tic"])
                        self.assertFalse(snapshot["capabilities"]["tic"])
                        self.assertEqual(selected is None, "implicit default conflicts" in warning.getvalue())
                        self.assertIn("tic", sandbox_proxies.load_accepted_manifest(data=snapshot)["commands"])
        # Accepted authority cannot retain a contradictory recorded selection.
        data = {"version": 1, "commands": {"tic": self.command(1)}, "capabilities": {"tic": True}}
        with self.assertRaisesRegex(sandbox_proxies.ConfigError, "tic.*conflicts"):
            sandbox_proxies.load_accepted_manifest(data=data)


if __name__ == "__main__":
    unittest.main()
