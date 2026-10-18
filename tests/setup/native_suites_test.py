"""Exercise native adapters through real pytest/xdist in a disposable repository."""

from collections import Counter
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]


class NativeSuitesTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="native-suites-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        sources = [
            ROOT / "dev/test", ROOT / "dev/pytest", ROOT / "dev/test-environment", ROOT / "dev/test-environment.clj",
            ROOT / "pytest.ini", ROOT / "tests/fixtures/native_suite_command.sh",
            ROOT / "tests/fixtures/native_suite_command.py",
            *sorted((ROOT / "tests/native").glob("*.py")),
        ]
        for source in sources:
            destination = self.root / source.relative_to(ROOT)
            destination.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(["cp", source, destination], check=True)
            subprocess.run(["cmp", source, destination], check=True)
        self.binaries = self.root / "bin"
        self.binaries.mkdir()
        fixture = self.root / "tests/fixtures/native_suite_command.sh"
        for tool in ("pytest", "python3", "bb", "bb-override", "node", "bun", "cargo", "java", "jj", "rg"):
            (self.binaries / tool).symlink_to(fixture)
        container = self.root / "dev/setup/container-test"
        container.parent.mkdir()
        container.symlink_to(fixture)
        self.host_home = self.root / "host-home"
        self.host_home.mkdir()
        self.log = self.root / "commands.jsonl"
        self.environment = os.environ | {
            "HOME": str(self.host_home), "PATH": f"{self.binaries}:{os.environ['PATH']}",
            "TEST_REAL_PYTHON": sys.executable,
            "TEST_NATIVE_FIXTURE": str(self.root / "tests/fixtures/native_suite_command.py"),
            "TEST_NATIVE_LOG": str(self.log),
            "DOTFILES_TEST_BB_REAL": str(self.binaries / "bb-override"),
            "DOTFILES_TEST_JJ_REAL": str(self.binaries / "jj"),
            "DOTFILES_TEST_JAVA_REAL": str(self.binaries / "java"),
            "DOTFILES_TEST_RG_REAL": str(self.binaries / "rg"),
            "DOTFILES_TEST_CARGO_HOME": str(self.root / "cargo-home"),
            "JJ_REAL": "must-not-leak", "JJ_PROXY_TEST_JJ": "must-be-overridden",
            "PYTEST_ADDOPTS": "", "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "",
        }
        for key in ("TEST_NATIVE_BARRIER", "TEST_NATIVE_PI_STATUS"):
            self.environment.pop(key, None)
        # An outer xdist worker is not the identity of the nested controller.
        for key in tuple(self.environment):
            if key.startswith("PYTEST_XDIST_"):
                self.environment.pop(key)

    def run_command(self, command, *, env=None):
        return subprocess.run(command, cwd=self.root, env=self.environment | (env or {}),
                              text=True, capture_output=True, timeout=90)

    def events(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()]

    def assert_native_commands(self):
        native = [event for event in self.events() if event["kind"] == "native"]
        # Independent oracle: the approved serial inventory, retaining native grouping.
        expected = [
            ("bb", "tools/extract-chat/tests/extract_chat_test.clj"),
            ("bb", "-cp", "tools/agent-split/src", "tools/agent-split/tests/run.clj"),
            ("bb", "-cp", "tools/package-plan/src", "tools/package-plan/tests/run.clj"),
            ("node", "tools/extract-chat-share/tests/extract_chat_share_test.js"),
            ("node", "tools/codex-archive-old/tests/codex_archive_old_test.js"),
            ("node", "--test", "tools/codex-sandbox/tests/tool_worker_test.mjs"),
            ("node", "--test", "tools/codex-sandbox/tests/guest_skill_context_test.mjs"),
            ("node", "--test", "tests/agent-wrappers/jj-conflict.test.mjs"),
            ("node", "--test", "tests/pi/native_prompt_sections.mjs", "tests/pi/native_web_search.mjs",
             "tests/pi/native_subscription_usage.mjs", "tests/pi/native_validate_skill.mjs",
             "tests/pi/native_transport_diagnostics.mjs"),
            ("node", "--test", "tests/pi/native_footer.mjs"),
            ("node", "--test", "--test-isolation=none", "tests/pi/native_prompt_history.mjs"),
            ("node", "--test", "tests/pi/native_session_title.mjs", "tests/pi/native_session_reader_title.mjs"),
            ("bun", "test", "tests/pi"),
            ("bun", "test", "tools/codex-sandbox/tests/guest_tools_test.ts"),
            ("bun", "test", "tools/codex-sandbox/tests/session_handoff_test.ts"),
            ("bun", "test", "tools/codex-sandbox/tests/session_side_test.ts"),
            ("cargo", "test", "--manifest-path", "tools/jj-proxy/Cargo.toml",
             *([] if platform.system() == "Linux" else ["--lib", "--bins"])),
        ]
        self.assertEqual(Counter(expected), Counter((event["tool"], *event["argv"]) for event in native))
        self.assertEqual(len(expected), len({event["home"] for event in native}))
        self.assert_isolated(native)
        for event in native:
            if event["tool"] == "bb":
                self.assertEqual("bb-override", event["executable"])
            agent = "tools/agent-split/tests/run.clj" in event["argv"]
            self.assertEqual(str(self.binaries / "jj") if agent else None, event["jj_real"])
            if event["tool"] == "cargo":
                self.assertEqual(str(self.binaries / "jj"), event["jj_proxy_test_jj"])
        return native

    def assert_isolated(self, native):
        for event in native:
            self.assertEqual(str(self.root), event["cwd"])
            self.assertTrue(event["directories_exist"])
            home = Path(event["home"])
            self.assertNotEqual(self.host_home, home)
            self.assertFalse(home.exists(), f"native HOME leaked: {home}")
            for directory in event["xdg"].values():
                self.assertTrue(Path(directory).is_relative_to(home))
                self.assertFalse(Path(directory).exists())

    def test_runner_executes_each_native_suite_once_with_private_state(self):
        # Dispatch tests cover the default worker count; two suffice for this integration.
        result = self.run_command([self.root / "dev/test", "--jobs", "2"])
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assert_native_commands()
        self.assertTrue(any(event["kind"] == "postcheck" and event["argv"] == ["dev/check-shell.py"]
                            for event in self.events()))
        self.assertIn("17 passed", result.stdout)
        self.assertIn("All checks passed", result.stdout)

    def test_native_failure_reports_output_and_blocks_repository_and_container_checks(self):
        result = self.run_command([self.root / "dev/test", "--jobs", "2", "--containers"],
                                  env={"TEST_NATIVE_PI_STATUS": "29"})
        self.assertEqual(1, result.returncode, result.stdout + result.stderr)
        self.assert_native_commands()
        output = result.stdout + result.stderr
        self.assertIn("NATIVE_PI_STDOUT_SENTINEL", output)
        self.assertIn("NATIVE_PI_STDERR_SENTINEL", output)
        self.assertIn("1 failed, 16 passed", output)
        downstream = [event for event in self.events() if event["kind"] in ("postcheck", "container")]
        self.assertEqual([{"kind": "postcheck", "argv": [str(self.root / "tools/codex-sandbox/owned_images.py")]}],
                         downstream)
        self.assertNotIn("All checks", output)

    def run_rendezvous(self, jobs):
        barrier = self.root / "barrier"
        barrier.mkdir()
        return self.run_command([
            self.root / "dev/test-environment", sys.executable, "-m", "pytest",
            "-q", "-p", "no:cacheprovider", "-n", str(jobs), "--dist", "loadfile",
            "tests/native/test_native_agent_split.py", "tests/native/test_native_pi_bun.py",
        ], env={"TEST_NATIVE_BARRIER": str(barrier)})

    def test_loadfile_schedules_independent_adapters_concurrently(self):
        result = self.run_rendezvous(2)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        events = self.events()
        native = [event for event in events if event["kind"] == "native"]
        self.assertEqual(Counter(["bb", "bun"]), Counter(event["tool"] for event in native))
        self.assertEqual(2, len({event["home"] for event in native}))
        self.assert_isolated(native)
        lifecycle = [event for event in events if event["kind"] in ("started", "finished")]
        self.assertEqual(Counter(["bb", "bun"]), Counter(event["tool"] for event in lifecycle[:2]))
        self.assertEqual(["started", "started", "finished", "finished"],
                         [event["kind"] for event in lifecycle])
