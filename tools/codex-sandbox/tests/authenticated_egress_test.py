"""Behavioral tests for the shared authenticated-egress instance owner."""
from contextlib import contextmanager
from pathlib import Path
from dataclasses import replace
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT))
import authenticated_egress as egress
import caddy_foundation as caddy
import sandbox_runtime


class Runtime:
    def __init__(self):
        self.commands = []
        self.volumes = []
        self.networks = []

    def create_owned_volume(self, *arguments): self.volumes.append(arguments)
    def create_public_service_network(self, *arguments, **keywords):
        self.networks.append((arguments, keywords))
    def run(self, arguments, **keywords):
        self.commands.append(arguments)
        return subprocess.CompletedProcess(arguments, 0, "", "")


class AuthenticatedEgressTest(unittest.TestCase):
    def plan(self, directory, domain):
        image = caddy.CaddyImageIdentity(
            caddy.IMAGE, caddy.INDEX, "linux/amd64", *caddy.PLATFORMS["linux/amd64"],
            caddy.PLATFORMS["linux/amd64"][1],
        )
        return egress.EgressPairPlan(
            domain=domain, service_owner="owner", caddy_name=domain + "-caddy",
            helper_name=domain + "-helper", socket_volume=domain + "-socket",
            configuration_path=Path(directory) / (domain + ".json"), configuration=b"{}\n",
            caddy_image=image, helper_image="helper@sha256:digest", uid=501, gid=20,
            application_network=domain + "-application",
            helper_network="none", public_networks=(("network", "application", domain + "-application"),),
            helper_mounts=("type=bind,src=/Users/jyn/.codex-sandbox-auth,dst=/run/credential,readonly",),
            helper_environment=(),
            helper_arguments=("--profile", domain), session_token="token",
        )

    def test_profiles_share_one_hardened_pair_lifecycle(self):
        for domain in ("codex", "zulip"):
            with self.subTest(domain=domain), tempfile.TemporaryDirectory(dir="/tmp") as directory:
                runtime = Runtime(); effects = []
                egress.start_egress_pair(
                    runtime, self.plan(directory, domain),
                    lambda status, operation: (effects.append(status), operation())[1],
                )
                self.assertEqual(effects, ["configuration", "socket-volume", "network",
                                           "helper-container", "caddy-container"])
                self.assertEqual(runtime.volumes, [(
                    domain + "-socket", 501, 20, "owner", domain, "profile-socket")])
                helper, proxy, readiness = runtime.commands
                self.assertIn("--cap-drop=ALL", helper)
                self.assertIn("--entrypoint", helper)
                credential = next(value for value in helper if value.startswith("type=bind,"))
                self.assertEqual("--mount", helper[helper.index(credential) - 1])
                self.assertIn("--cap-add=NET_BIND_SERVICE", proxy)
                self.assertEqual(proxy[-4:], ["caddy", "run", "--config", "/etc/caddy/caddy.json"])
                self.assertEqual(readiness[:2], ["exec", domain + "-caddy"])
                self.assertIn("--header=Authorization: Bearer token", readiness)

    def test_readiness_uses_each_instances_token(self):
        with tempfile.TemporaryDirectory(dir="/tmp") as directory:
            runtime = Runtime()
            plan = replace(self.plan(directory, "codex"), session_token="different-token")
            egress.start_egress_pair(runtime, plan, lambda status, operation: operation())
            self.assertIn("--header=Authorization: Bearer different-token", runtime.commands[-1])
            self.assertNotIn("--header=Authorization: Bearer token", runtime.commands[-1])
            self.assertIn("CADDY_PROFILE_TOKEN=different-token", runtime.commands[0])
            self.assertNotIn("CADDY_PROFILE_TOKEN=token", runtime.commands[0])

    def test_timing_spans_cover_each_effect_and_readiness_without_changing_order(self):
        with tempfile.TemporaryDirectory(dir="/tmp") as directory:
            spans = []

            @contextmanager
            def timing(operation):
                spans.append(("start", operation))
                try:
                    yield
                finally:
                    spans.append(("finish", operation))

            runtime = Runtime()
            egress.start_egress_pair(
                runtime, self.plan(directory, "codex"),
                lambda status, operation: operation(), timing=timing,
            )
            operations = ["configuration", "socket-volume", "network",
                          "helper-container", "caddy-container", "readiness"]
            self.assertEqual(
                [(boundary, operation) for operation in operations
                 for boundary in ("start", "finish")],
                spans,
            )
            self.assertEqual(3, len(runtime.commands))

    def test_pair_rejects_duplicate_or_invalid_admission_authority(self):
        with tempfile.TemporaryDirectory(dir="/tmp") as directory:
            plan = self.plan(directory, "codex")
            with self.assertRaisesRegex(ValueError, "owns the helper admission token"):
                replace(plan, helper_environment=("CADDY_PROFILE_TOKEN=other-token",))
            for token in ("", "line\nbreak", "x" * 4090):
                with self.subTest(token_class="empty" if not token else "invalid"):
                    with self.assertRaisesRegex(ValueError, "invalid authenticated-egress session token"):
                        replace(plan, session_token=token)

    def test_topology_derives_container_dependencies_from_network_attachments(self):
        with tempfile.TemporaryDirectory(dir="/tmp") as directory:
            zulip = self.plan(directory, "zulip")
            self.assertEqual(
                ("configuration", "socket-volume", "network"),
                zulip.resource_topology().dependencies["caddy-container"],
            )
            self.assertEqual(
                ("socket-volume",),
                zulip.resource_topology().dependencies["helper-container"],
            )

            codex = replace(
                self.plan(directory, "codex"),
                helper_network="codex-refresh",
                public_networks=(
                    ("application-network", "application", "codex-application"),
                    ("refresh-network", "refresh", "codex-refresh"),
                ),
            )
            self.assertEqual(
                ("socket-volume", "refresh-network"),
                codex.resource_topology().dependencies["helper-container"],
            )

    def test_runtime_normalizes_volume_authority_and_disabled_networks(self):
        class ContainerRuntime(sandbox_runtime.ContainerRuntime):
            def __init__(self): self.arguments = None
            def run(self, arguments, **keywords): self.arguments = arguments
        container = ContainerRuntime()
        container.create_owned_volume("socket", 501, 20, "owner", "zulip", "profile-socket")
        self.assertNotIn("--uid", container.arguments)
        self.assertNotIn("--gid", container.arguments)
        container_volume = {"Labels": {"dev.codex.service-owner": "owner",
            "dev.codex.credential-domain": "zulip", "dev.codex.resource-role": "profile-socket"}}
        self.assertTrue(container.owned_volume_matches(
            container_volume, "owner", "zulip", "profile-socket"))
        docker = object.__new__(sandbox_runtime.VMRuntime)
        docker_volume = {"Labels": {"dev.codex.volume-owner": "owner"}}
        self.assertTrue(docker.owned_volume_matches(
            docker_volume, "owner", "zulip", "profile-socket"))
        self.assertEqual(set(), docker.container_networks(
            {"NetworkSettings": {"Networks": {"none": {}}}}))


if __name__ == "__main__": unittest.main()
