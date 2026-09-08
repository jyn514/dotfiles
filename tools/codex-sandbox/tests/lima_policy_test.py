import hashlib
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

import lima_network_integration as fixture


SOURCE = Path(__file__).resolve().parents[1] / "lima/public-only"
loader = importlib.machinery.SourceFileLoader("public_only", str(SOURCE))
spec = importlib.util.spec_from_loader(loader.name, loader)
policy = importlib.util.module_from_spec(spec)
loader.exec_module(policy)
pin_spec = importlib.util.spec_from_file_location("pin_rootless", SOURCE.with_name("pin-rootless-network.py"))
pin = importlib.util.module_from_spec(pin_spec)
pin_spec.loader.exec_module(pin)


class PolicyFailureTests(unittest.TestCase):
    def setUp(self):
        self.raw = json.dumps({"version": 2, "ipv6": "disabled", "dns": "10.0.2.3",
                               "prohibited": ["10.0.0.0/8", "192.168.0.0/16"]}).encode()
        self.source = Mock()
        self.source.read_bytes.return_value = self.raw
        self.source.lstat.return_value = types.SimpleNamespace(st_mode=stat.S_IFREG | 0o644, st_uid=0)
        self.config = {"cniVersion": "1.0.0", "policyDigest": hashlib.sha256(self.raw).hexdigest(),
                       "prevResult": {"interfaces": [{"name": "eth0"}],
                                      "ips": [{"address": "10.233.81.2/24"}]}}

    def invoke(self, command="ADD"):
        with patch.dict(os.environ, CNI_COMMAND=command), patch.object(policy, "POLICY", self.source), \
                patch.object(policy.json, "load", return_value=self.config), \
                patch.object(policy, "verify_resolver"):
            return policy.main()

    def test_stale_policy_never_touches_namespace(self):
        self.config["policyDigest"] = "old policy"
        with patch.object(policy, "in_namespace") as namespace:
            with self.assertRaisesRegex(ValueError, "stale"):
                self.invoke()
            namespace.assert_not_called()

    def test_writable_or_symlink_policy_is_rejected_before_namespace_access(self):
        for mode in (stat.S_IFREG | 0o666, stat.S_IFLNK | 0o777):
            with self.subTest(mode=mode), patch.object(policy, "in_namespace") as namespace:
                self.source.lstat.return_value.st_mode = mode
                with self.assertRaisesRegex(ValueError, "root-owned"):
                    self.invoke()
                namespace.assert_not_called()

    def test_partial_route_failure_cannot_return_success(self):
        # A later route fails after earlier mutations succeeded. CNI must abort
        # startup; DEL must leave remaining restrictions until namespace teardown.
        with patch.object(policy, "in_namespace", side_effect=["", "", "", subprocess.CalledProcessError(2, "ip")]):
            with self.assertRaises(subprocess.CalledProcessError):
                self.invoke()
        with patch.object(policy, "in_namespace") as namespace:
            self.assertIsNone(self.invoke("DEL"))
            namespace.assert_not_called()

    def test_check_detects_lost_route(self):
        with patch.object(policy, "in_namespace", return_value='[{"dst":"10.0.0.0/8"}]'):
            with self.assertRaisesRegex(ValueError, "incomplete"):
                self.invoke("CHECK")

    def test_success_preserves_previous_interface_and_dns_result(self):
        self.config["prevResult"]["dns"] = {"nameservers": ["10.233.81.1"]}
        with patch.object(policy, "in_namespace"), patch.object(policy, "check_routes"), \
                patch.object(policy, "default_route", return_value=("10.233.81.1", "eth0")), \
                patch.object(policy, "allow_dns"), patch.object(policy, "check_dns"):
            self.assertEqual(self.config["prevResult"], self.invoke())

    def test_changed_rootlesskit_resolver_is_rejected(self):
        for network in ({"driver": "slirp4netns", "dns": ["10.0.3.3"]},
                        {"driver": "pasta", "dns": ["10.0.2.3"]}):
            with self.subTest(network=network), patch.dict(os.environ, ROOTLESSKIT_STATE_DIR="/run/owned"), \
                    patch.object(policy.subprocess, "run", return_value=types.SimpleNamespace(
                        stdout=json.dumps({"networkDriver": network}))), \
                    patch.dict(os.environ, CNI_COMMAND="ADD"), patch.object(policy, "POLICY", self.source), \
                    patch.object(policy.json, "load", return_value=self.config), \
                    patch.object(policy, "in_namespace") as namespace:
                with self.assertRaisesRegex(ValueError, "differs"):
                    policy.main()
                namespace.assert_not_called()

    def test_unrestricted_dns_host_rule_is_rejected(self):
        broad_rule = [{"priority": 1053, "src": "all", "dst": "10.0.2.3", "table": "1053"}]
        with patch.object(policy, "in_namespace", return_value=json.dumps(broad_rule)):
            with self.assertRaisesRegex(ValueError, "selectors differ"):
                policy.check_dns("10.0.2.3", "10.233.81.1", "eth0")

    def test_partial_dns_installation_cannot_return_success(self):
        def namespace(*args):
            if "add" in args and "udp" in args:
                raise subprocess.CalledProcessError(2, args)
            return "[]"

        with patch.object(policy, "in_namespace", side_effect=namespace):
            with self.assertRaises(subprocess.CalledProcessError):
                policy.allow_dns("10.0.2.3", "10.233.81.1", "eth0")


class NetworkPinTests(unittest.TestCase):
    def test_incompatible_state_is_rejected_before_writing_configuration(self):
        cases = [({"CONTAINERD_ROOTLESS_ROOTLESSKIT_FLAGS": "--mtu=1500"}, "10.0.2.3", "custom"),
                 ({}, "10.0.3.3", "effective")]
        for environment, dns, message in cases:
            with self.subTest(message=message), tempfile.TemporaryDirectory() as directory:
                before = ["rootlesskit", "--net=slirp4netns", "--disable-host-loopback", "--state-dir=/run/owned"]
                def run(*args):
                    if args == ("rootlesskit", "--help"):
                        return "--cidr"
                    return json.dumps({"networkDriver": {"driver": "slirp4netns", "dns": [dns], "childIP": "10.0.2.100"}})

                with patch.object(pin.sys, "argv", ["pin", str(SOURCE.with_name("rootless-network.json"))]), \
                        patch.object(pin, "daemon_state", return_value=(before, environment)), \
                        patch.object(pin, "run", side_effect=run), patch.object(pin.Path, "home", return_value=Path(directory)):
                    with self.assertRaisesRegex(RuntimeError, message):
                        pin.main()
                self.assertEqual([], list(Path(directory).iterdir()))


class FixtureCleanupTests(unittest.TestCase):
    def test_cleanup_only_failure_is_not_success(self):
        failure = subprocess.CalledProcessError(1, "delete")
        with patch.object(fixture.sys, "argv", ["probe"]), \
                patch.object(fixture, "install_probe"), \
                patch.object(fixture, "command", side_effect=[None, None, failure]):
            with self.assertRaises(subprocess.CalledProcessError) as caught:
                fixture.main()
        self.assertIs(failure, caught.exception)

    def test_partial_creation_retains_primary_error_and_attempts_cleanup(self):
        failure = subprocess.CalledProcessError(3, "create")
        with patch.object(fixture.sys, "argv", ["probe"]), \
                patch.object(fixture, "command", side_effect=[failure, OSError("cleanup failed")]) as command:
            with self.assertRaises(subprocess.CalledProcessError) as caught:
                fixture.main()
        self.assertIs(failure, caught.exception)
        self.assertEqual("delete", command.call_args.args[1])


if __name__ == "__main__":
    unittest.main()
