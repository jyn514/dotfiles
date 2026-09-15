"""Behavioral tests for the shared authenticated-egress instance owner."""
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
            helper_environment=("CADDY_PROFILE_TOKEN=token",),
            helper_arguments=("--profile", domain),
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
        class Podman(sandbox_runtime.Podman):
            def __init__(self): self.arguments = None
            def run(self, arguments, **keywords): self.arguments = arguments
        podman = Podman()
        podman.create_owned_volume("socket", 501, 20, "owner", "zulip", "profile-socket")
        self.assertNotIn("--uid", podman.arguments)
        self.assertNotIn("--gid", podman.arguments)
        podman_volume = {"Labels": {"dev.codex.service-owner": "owner",
            "dev.codex.credential-domain": "zulip", "dev.codex.resource-role": "profile-socket"}}
        self.assertTrue(podman.owned_volume_matches(
            podman_volume, "owner", "zulip", "profile-socket"))
        docker = object.__new__(sandbox_runtime.VMRuntime)
        docker_volume = {"Labels": {"dev.codex.volume-owner": "owner"}}
        self.assertTrue(docker.owned_volume_matches(
            docker_volume, "owner", "zulip", "profile-socket"))
        self.assertEqual(set(), docker.container_networks(
            {"NetworkSettings": {"Networks": {"none": {}}}}))


if __name__ == "__main__": unittest.main()
