#!/usr/bin/env python3

import os
from pathlib import Path
import subprocess
import sys
import threading
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import image_resolver
import owned_images
from sandbox_runtime import Image


FIXTURE = Path(__file__).parent / "fixtures" / "resolver_protocol.py"


class Runtime:
    provider = "test-engine"

    def __init__(self):
        self.inspected = []

    def build_platform(self):
        return "linux/test"

    def builder_environment(self):
        return os.environ.copy()

    def builder_image(self, reference):
        self.inspected.append(reference)
        return "verified:" + reference

    def inspect_image(self, reference):
        return Image(reference, reference, reference, reference)

    def verify_builder_image(self, reference):
        return self.inspect_image(self.builder_image(reference))


class ImageResolverTest(unittest.TestCase):
    def resolve(self, mode="valid", names={"base", "proxy"}):
        runtime = Runtime()
        previous = os.environ.get("RESOLVER_FIXTURE")
        os.environ["RESOLVER_FIXTURE"] = mode
        try:
            result = image_resolver.resolve_command(runtime, Path.cwd(), [sys.executable, str(FIXTURE)], names)
        finally:
            if previous is None:
                os.environ.pop("RESOLVER_FIXTURE", None)
            else:
                os.environ["RESOLVER_FIXTURE"] = previous
        return runtime, result

    def test_validates_complete_exact_result_then_inspects_images(self):
        runtime, result = self.resolve()
        self.assertEqual({"base", "proxy"}, set(result))
        self.assertEqual(2, len(runtime.inspected))

    def test_rejects_extra_name_before_inspection(self):
        runtime = Runtime()
        previous = os.environ.get("RESOLVER_FIXTURE")
        os.environ["RESOLVER_FIXTURE"] = "extra"
        try:
            with self.assertRaisesRegex(image_resolver.ResolverError, "exactly match"):
                image_resolver.resolve_command(runtime, Path.cwd(), [sys.executable, str(FIXTURE)], {"base"})
        finally:
            if previous is None:
                os.environ.pop("RESOLVER_FIXTURE", None)
            else:
                os.environ["RESOLVER_FIXTURE"] = previous
        self.assertEqual([], runtime.inspected)

    def test_rejects_duplicate_json_fields(self):
        with self.assertRaisesRegex(image_resolver.ResolverError, "duplicate JSON field"):
            self.resolve("duplicate", {"base"})

    def test_bounds_stdout(self):
        with self.assertRaisesRegex(image_resolver.ResolverError, "stdout exceeds"):
            self.resolve("large", {"base"})

    def test_reports_nonzero_status_and_stderr(self):
        with self.assertRaisesRegex(image_resolver.ResolverError, "status 23: fixture failed"):
            self.resolve("error", {"base"})

    def test_timeout_kills_descendant_after_resolver_parent_exits(self):
        with mock.patch.object(image_resolver, "TIMEOUT", 0.1), \
                mock.patch.object(image_resolver, "KILL_TIMEOUT", 0.1):
            with self.assertRaises(subprocess.TimeoutExpired):
                self.resolve("exited-parent", {"base"})

    def test_agent_composition_builds_only_for_a_missing_complete_identity(self):
        runtime = type("AgentRuntime", (), {})()
        runtime.provider = "test-engine"
        runtime.build_platform = lambda: "linux/arm64"
        runtime.upstream_image = lambda reference: reference + "@sha256:" + "e" * 64
        runtime.inspect_image = lambda reference: Image(
            reference, "sha256:" + "a" * 64, "sha256:" + "b" * 64,
            "sha256:" + "c" * 64,
        )
        runtime.image_if_available = lambda _tag: None
        built = []
        runtime.build = lambda tag, dockerfile, context, *, build_args: (
            built.append((tag, dockerfile, context, build_args)) or
            Image("agent@sha256:" + "d" * 64, "sha256:" + "d" * 64,
                  "sha256:" + "e" * 64, "sha256:" + "f" * 64)
        )
        self.assertEqual(
            "agent@sha256:" + "d" * 64,
            owned_images.resolve_agent(runtime, 501, 20, "base@sha256:" + "a" * 64),
        )
        self.assertEqual(1, len(built))
        self.assertIn("BASE_IMAGE=base@sha256:", built[0][3][-1])

    def test_agent_composition_propagates_engine_errors_without_building(self):
        runtime = type("AgentRuntime", (), {})()
        runtime.provider = "test-engine"
        runtime.build_platform = lambda: "linux/arm64"
        runtime.upstream_image = lambda reference: reference + "@sha256:" + "e" * 64
        runtime.inspect_image = lambda reference: Image(
            reference, "sha256:" + "a" * 64, "sha256:" + "b" * 64,
            "sha256:" + "c" * 64,
        )
        runtime.image_if_available = lambda _tag: (_ for _ in ()).throw(OSError("engine unavailable"))
        runtime.build = lambda *_args, **_kwargs: self.fail("engine error became a build")
        with self.assertRaisesRegex(OSError, "engine unavailable"):
            owned_images.resolve_agent(runtime, 501, 20, "base@sha256:" + "a" * 64)

    def test_project_and_installed_helper_resolvers_overlap(self):
        project_started = threading.Event()
        helper_started = threading.Event()

        def project(*_args, **_kwargs):
            project_started.set()
            self.assertTrue(helper_started.wait(1))
            return {"base": Image("base", "base", "base", "base")}

        def helper(*_args, **_kwargs):
            helper_started.set()
            self.assertTrue(project_started.wait(1))
            return {"auth": "helper"}

        runtime = mock.Mock(provider="lima-docker")
        runtime.bake.return_value = {}
        runtime.run_builders.return_value = {}
        policy = {"base": "base", "resolver": {"kind": "bake", "file": "docker-bake.hcl"}}
        auth = [str(owned_images.ROOT / "tools/codex-sandbox/auth-proxy/image")]
        with mock.patch.object(image_resolver, "resolve_policy", side_effect=project), \
                mock.patch("bake.resolve", side_effect=helper):
            prepared = image_resolver.prepare_launch_images(
                runtime, Path.cwd(), {}, include_base=True,
                auth_builder=(auth, Path.cwd()), image_policy=policy,
            )
        self.assertEqual("base", prepared.base)
        self.assertEqual("helper", prepared.auth)


if __name__ == "__main__":
    unittest.main()
