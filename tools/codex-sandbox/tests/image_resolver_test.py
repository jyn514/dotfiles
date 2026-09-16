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
    def test_default_base_is_pulled_only_when_missing(self):
        for available in (False, True):
            with self.subTest(available=available):
                runtime = mock.Mock()
                base = Image('sha256:' + 'a' * 64, 'base', 'config', 'rootfs')
                local = {owned_images.DEFAULT_BASE: base} if available else {}
                runtime.image_if_available.side_effect = lambda ref: local.get(ref)
                runtime.inspect_image.side_effect = lambda ref: local[ref]
                runtime.run.side_effect = lambda *args, **kwargs: local.update(
                    {owned_images.DEFAULT_BASE: base})
                runtime.build.return_value = Image('agent', 'agent', 'config', 'rootfs')
                with mock.patch('bake._capture'), mock.patch('bake._pin_dockerfile'), \
                        mock.patch.object(owned_images, 'agent_cache_key', return_value='key'):
                    self.assertEqual('agent', owned_images.resolve_agent(
                        runtime, 501, 20, owned_images.DEFAULT_BASE))
                self.assertEqual(0 if available else 1, runtime.run.call_count)
                if not available:
                    self.assertEqual(['pull', owned_images.DEFAULT_BASE], runtime.run.call_args.args[0])
                self.assertIn('BASE_IMAGE=' + base.reference, runtime.build.call_args.kwargs['build_args'])

    def test_default_base_selection_follows_launcher_authority(self):
        runtime = mock.Mock()
        runtime.bake.return_value = {}
        runtime.run_builders.return_value = {}
        with mock.patch.object(owned_images, 'DEFAULT_BASE', 'replacement:base'):
            prepared = image_resolver.prepare_launch_images(
                runtime, Path('/nonexistent-project'), {}, include_base=True)
        self.assertEqual('replacement:base', prepared.base)

    def test_default_base_pull_failure_stops_composition(self):
        runtime = mock.Mock()
        runtime.image_if_available.return_value = None
        runtime.run.side_effect = OSError('pull failed')
        with mock.patch('bake._capture'), self.assertRaisesRegex(OSError, 'pull failed'):
            owned_images.resolve_agent(runtime, 501, 20, owned_images.DEFAULT_BASE)
        runtime.build.assert_not_called()

    def test_missing_project_base_is_not_pulled(self):
        runtime = mock.Mock()
        runtime.inspect_image.side_effect = OSError('project base missing')
        with mock.patch('bake._capture'), self.assertRaisesRegex(OSError, 'project base missing'):
            owned_images.resolve_agent(runtime, 501, 20, 'sha256:' + 'b' * 64)
        runtime.run.assert_not_called()
        runtime.build.assert_not_called()

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

    def test_reports_nonzero_status_after_streaming_stderr(self):
        with self.assertRaisesRegex(
                image_resolver.ResolverError,
                "status 23; see resolver output above",
        ):
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
