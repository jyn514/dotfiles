"""Exercise native adapters through real pytest/xdist in a disposable repository."""

from collections import Counter
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from xml.etree import ElementTree


ROOT = Path(__file__).resolve().parents[2]


class NativeSuitesTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="native-suites-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        sources = [
            ROOT / "dev/test", ROOT / "dev/pytest", ROOT / "dev/test-environment", ROOT / "dev/test-environment.clj",
            ROOT / "dev/integration-tests.txt",
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
        for tool in ("pytest", "python3", "bb", "bb-override", "node", "bun", "cargo", "npm",
                     "java", "jj", "rg"):
            (self.binaries / tool).symlink_to(fixture)
        container = self.root / "dev/setup/container-test"
        container.parent.mkdir()
        container.symlink_to(fixture)
        self.host_home = self.root / "host-home"
        self.host_home.mkdir()
        for source in ("tools/pi-codex-goal", "tools/pi-session-search"):
            (self.root / source).mkdir(parents=True)
        sdk = self.root / "installed-pi"
        sdk.mkdir()
        (sdk / "package.json").write_text('{"name":"@earendil-works/pi-coding-agent"}\n')
        typebox = self.root / "installed-typebox"
        typebox.mkdir()
        (typebox / "package.json").write_text('{"name":"typebox"}\n')
        typebox_entry = typebox / "index.js"
        typebox_entry.touch()
        self.log = self.root / "commands.jsonl"
        self.pytest_report = self.root / "pytest-report.xml"
        self.environment = os.environ | {
            "HOME": str(self.host_home), "PATH": f"{self.binaries}:{os.environ['PATH']}",
            "TEST_REAL_PYTHON": sys.executable,
            "TEST_NATIVE_FIXTURE": str(self.root / "tests/fixtures/native_suite_command.py"),
            "TEST_NATIVE_LOG": str(self.log),
            "TEST_TYPEBOX_ENTRY": str(typebox_entry),
            "PI_PACKAGE_DIR": str(sdk),
            "DOTFILES_TEST_BB_REAL": str(self.binaries / "bb-override"),
            "DOTFILES_TEST_JJ_REAL": str(self.binaries / "jj"),
            "DOTFILES_TEST_JAVA_REAL": str(self.binaries / "java"),
            "DOTFILES_TEST_PYTHON3_REAL": str(self.binaries / "python3"),
            "DOTFILES_TEST_RG_REAL": str(self.binaries / "rg"),
            "DOTFILES_TEST_CARGO_HOME": str(self.root / "cargo-home"),
            "JJ_REAL": "must-not-leak", "JJ_PROXY_TEST_JJ": "must-be-overridden",
            "PYTEST_ADDOPTS": f"--junitxml={self.pytest_report}",
            "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "",
        }
        for key in ("TEST_NATIVE_BARRIER", "TEST_NATIVE_HOLD", "TEST_NATIVE_JOBS",
                    "TEST_NATIVE_PI_STATUS"):
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

    def assert_native_coverage(self):
        native = [event for event in self.events() if event["kind"] == "native"]
        expected_adapters = Counter({path.stem: 1 for path in
                                     (self.root / "tests/native").glob("test_native_*.py")})
        report = ElementTree.parse(self.pytest_report)
        executed_adapters = Counter(
            case.attrib["classname"].rsplit(".", 1)[-1]
            for case in report.findall(".//testcase")
            if case.attrib.get("classname", "").startswith("tests.native.test_native_")
        )
        self.assertEqual(expected_adapters, executed_adapters)
        self.assertEqual(len(native), len({event["home"] for event in native}))
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
        result = self.run_command([self.root / "dev/test", "--native", "--jobs", "2"])
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assert_native_coverage()
        self.assertTrue(any(event["kind"] == "postcheck" and event["argv"] == ["dev/check-shell.py"]
                            for event in self.events()))
        self.assertIn("All checks passed", result.stdout)

    def test_native_failure_reports_output_and_blocks_repository_and_container_checks(self):
        result = self.run_command([self.root / "dev/test", "--native", "--jobs", "2", "--containers"],
                                  env={"TEST_NATIVE_JOBS": "1", "TEST_NATIVE_PI_STATUS": "29"})
        self.assertEqual(1, result.returncode, result.stdout + result.stderr)
        self.assert_native_coverage()
        output = result.stdout + result.stderr
        self.assertIn("NATIVE_PI_STDOUT_SENTINEL", output)
        self.assertIn("NATIVE_PI_STDERR_SENTINEL", output)
        failed = [case.attrib["classname"].rsplit(".", 1)[-1]
                  for case in ElementTree.parse(self.pytest_report).findall(".//testcase")
                  if case.find("failure") is not None]
        self.assertEqual(["test_native_pi_bun"], failed)
        downstream = [event for event in self.events() if event["kind"] in ("postcheck", "container")]
        self.assertEqual([{"kind": "postcheck", "argv": [str(self.root / "tools/codex-sandbox/owned_images.py")]}],
                         downstream)
        self.assertNotIn("All checks", output)

    def run_with_held_native_suites(self, native_jobs):
        release = self.root / "release-native-suites"
        release.unlink(missing_ok=True)
        command = [
            self.root / "dev/test-environment", sys.executable, "-m", "pytest",
            "-q", "-p", "no:cacheprovider", "-n", "3", "--dist", "loadfile",
            "tests/native/test_native_agent_split.py",
            "tests/native/test_native_pi_bun.py",
            "tests/native/test_native_pi_to_codex.py",
        ]
        process = subprocess.Popen(
            command, cwd=self.root,
            env=self.environment | {"TEST_NATIVE_HOLD": str(release),
                                    "TEST_NATIVE_JOBS": str(native_jobs)},
            text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            events = self.events() if self.log.exists() else []
            if len([event for event in events if event["kind"] == "started"]) == native_jobs:
                break
            time.sleep(0.01)
        else:
            process.kill()
            stdout, stderr = process.communicate()
            self.fail(f"native suites did not fill {native_jobs} slots:\n{stdout}\n{stderr}")
        time.sleep(0.1)
        events = self.events()
        self.assertEqual(native_jobs, len([event for event in events if event["kind"] == "started"]))
        self.assertIsNone(process.poll(), "a waiting native suite must not finish before a slot is released")
        release.touch()
        stdout, stderr = process.communicate(timeout=10)
        self.assertEqual(0, process.returncode, stdout + stderr)
        return self.events()

    def test_native_admission_limits_cross_worker_subprocesses_and_honors_override(self):
        for native_jobs in (1, 2):
            with self.subTest(native_jobs=native_jobs):
                if self.log.exists():
                    self.log.unlink()
                events = self.run_with_held_native_suites(native_jobs)
                self.assertEqual(3, len([event for event in events if event["kind"] == "started"]))
                self.assertEqual(3, len([event for event in events if event["kind"] == "finished"]))

    def test_native_admission_rejects_invalid_job_counts(self):
        for value in ("0", "not-a-number"):
            with self.subTest(value=value):
                result = self.run_command([
                    self.root / "dev/test-environment", sys.executable, "-m", "pytest",
                    "-q", "-p", "no:cacheprovider", "tests/native/test_native_agent_split.py",
                ], env={"TEST_NATIVE_JOBS": value})
                self.assertNotEqual(0, result.returncode)
                self.assertIn("TEST_NATIVE_JOBS must be a positive integer", result.stdout + result.stderr)

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
