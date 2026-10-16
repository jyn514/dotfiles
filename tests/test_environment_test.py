import json
import os
from pathlib import Path
import selectors
import signal
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
WRAPPER = ROOT / "dev" / "test-environment"
PROBE = ROOT / "tests" / "fixtures" / "test_environment_probe.py"
HOME_PRELOAD = ROOT / "dev/test-environment.clj"
PI_HOME_DEFAULT_NAMES = ("PI_CODING_AGENT_DIR", "PI_CODING_AGENT_SESSION_DIR")
STATE_NAMES = (
    *PI_HOME_DEFAULT_NAMES, "PI_SUBAGENT_TEMP_DIR",
    "XDG_CONFIG_HOME", "XDG_CACHE_HOME", "XDG_DATA_HOME",
    "XDG_STATE_HOME", "XDG_RUNTIME_DIR",
)
UNSET_NAMES = (
    *PI_HOME_DEFAULT_NAMES, "JJ_CONFIG",
    "XDG_CONFIG_DIRS", "XDG_DATA_DIRS", "PI_MODEL_FILE", "PI_MODEL_SESSION_ID", "PI_CALL_MODEL",
)


class TestEnvironmentTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.old_home = self.root / "inherited-home"
        self.old_home.mkdir()
        self.inherited = {
            key: value for key, value in os.environ.items()
            if not key.startswith("DOTFILES_TEST_")
            and key not in (*STATE_NAMES, "PI_PACKAGE_DIR", "HOME", "CARGO_HOME")
        }
        self.inherited["HOME"] = str(self.old_home)
        for name in STATE_NAMES:
            poisoned = self.old_home / name.lower()
            poisoned.mkdir()
            (poisoned / "existing-state").write_bytes(b"untouched\x00\xff\r\n")
            self.inherited[name] = str(poisoned)
        for name in UNSET_NAMES:
            self.inherited[name] = str(self.old_home / name.lower())
        (self.old_home / "existing-home").write_bytes(b"home state\x00\xfe")
        user_cargo = self.old_home / ".cargo"
        user_cargo.mkdir()
        (user_cargo / "config.toml").write_text('[net]\noffline = true\n')
        (user_cargo / "credentials.toml").write_text('[registry]\ntoken = "fixture-secret"\n')
        self.inherited["CARGO_HOME"] = str(user_cargo)
        self.cargo_home = self.root / "cargo-test-home"
        self.inherited["DOTFILES_TEST_CARGO_HOME"] = str(self.cargo_home)

    def snapshot(self, path: Path) -> dict:
        return {
            str(item.relative_to(path)): (
                item.stat().st_mode & 0o777,
                item.read_bytes() if item.is_file() else None,
            )
            for item in path.rglob("*")
        }

    def make_sdk(self, path: Path) -> Path:
        path.mkdir(parents=True)
        (path / "package.json").write_bytes(b'{"name":"fixture-sdk"}\n')
        (path / "sdk.js").write_bytes(b"// immutable SDK fixture\x00\xff\n")
        return path

    def installed_sdk_path(self) -> Path:
        return self.old_home / ".local/share/pi/node/node_modules/@earendil-works/pi-coding-agent"

    def run_probe(self, mode: str, *args: str, values=None, input=None):
        result = subprocess.run(
            [WRAPPER, sys.executable, PROBE, mode, *args],
            env=self.inherited | (values or {}),
            text=True, input=input, capture_output=True, check=False, timeout=15,
        )
        self.assertTrue(result.stdout, result.stderr)
        return result, json.loads(result.stdout)

    def assert_private_home(self, report, *, cleaned=True):
        home = Path(report["home"])
        self.assertNotEqual(self.old_home, home)
        self.assertTrue(report["home_exists"])
        self.assertEqual(0o700, report["home_mode"])
        self.assertEqual(0o700, report["runtime_mode"])
        for name in UNSET_NAMES:
            self.assertNotIn(name, report["environment"])
        for name, directory in report["state_paths"].items():
            path = Path(directory)
            self.assertTrue(path.is_absolute(), (name, directory))
            self.assertTrue(path.is_relative_to(home), (name, directory, home))
            # Pi creates its HOME-relative defaults lazily; only wrapper-owned
            # directories must already exist when the child starts.
            if name not in PI_HOME_DEFAULT_NAMES:
                self.assertTrue(report["state_exists_before_child_write"][name], name)
        if cleaned:
            self.assertFalse(home.exists(), f"wrapper leaked {home}")
        return home

    def run_environment(self, **values: str) -> dict[str, str]:
        result = subprocess.run(
            [WRAPPER, "env", "-0"], env=self.inherited | values,
            text=True, capture_output=True, check=False, timeout=15,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        return dict(entry.split("=", 1) for entry in result.stdout.rstrip("\0").split("\0"))

    def test_preserves_real_tools_without_exposing_sandbox_authority(self) -> None:
        environment = self.run_environment(
            BB_REAL="/private/bb", BB_SOURCE_ROOT="/private/source",
            JAVA_REAL="/private/java", JJ_REAL="/private/jj", RG_REAL="/private/rg",
            CLAUDECODE="1", CODEX_THREAD_ID="thread", JJ_AGENT="pi",
            PI_CODING_AGENT="true", CODEX_SIDECAR_KEY="secret",
            CODEX_SIDECAR_URL="http://proxy", SANDBOX_PROXY_DIR="/run/proxies",
            SANDBOX_PROXY_DEFAULT_DIR="/run/default-proxies",
        )
        self.assertEqual("/private/bb", environment["DOTFILES_TEST_BB_REAL"])
        self.assertEqual("/private/java", environment["DOTFILES_TEST_JAVA_REAL"])
        self.assertEqual("/private/jj", environment["DOTFILES_TEST_JJ_REAL"])
        self.assertEqual("/private/rg", environment["DOTFILES_TEST_RG_REAL"])
        self.assertEqual("/run/proxies", environment["DOTFILES_TEST_SANDBOX_PROXY_DIR"])
        self.assertEqual("/nonexistent", environment["SANDBOX_PROXY_DEFAULT_DIR"])
        for name in (
            "BB_REAL", "BB_SOURCE_ROOT", "JAVA_REAL", "JJ_REAL", "RG_REAL",
            "CLAUDECODE", "CODEX_THREAD_ID", "JJ_AGENT", "PI_CODING_AGENT",
            "CODEX_SIDECAR_KEY", "CODEX_SIDECAR_URL", "SANDBOX_PROXY_DIR",
        ):
            self.assertNotIn(name, environment)

    def mise_shim(self) -> dict[str, str]:
        shims = self.root / "shims"
        installed = self.root / "installed"
        shims.mkdir()
        installed.mkdir()
        (shims / "rg").symlink_to(ROOT / "tests/fixtures/mise")
        (installed / "rg").symlink_to(shutil.which("env"))
        self.inherited["PATH"] = str(shims) + os.pathsep + self.inherited["PATH"]
        return {
            "FIXTURE_MISE_CALL": str(self.root / "mise-home"),
            "FIXTURE_RG_PATH": str(installed / "rg"),
        }

    def test_mise_shim_resolves_before_home_isolation_and_child_uses_real_tool(self) -> None:
        values = self.mise_shim()
        result = subprocess.run(
            [WRAPPER, "rg", "-0"], env=self.inherited | values,
            text=True, capture_output=True, check=False, timeout=15,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        environment = dict(entry.split("=", 1) for entry in result.stdout.rstrip("\0").split("\0"))
        self.assertEqual(str(self.old_home), Path(values["FIXTURE_MISE_CALL"]).read_text())
        self.assertEqual(values["FIXTURE_RG_PATH"], environment["DOTFILES_TEST_RG_REAL"])
        self.assertNotEqual(str(self.old_home), environment["HOME"])
        self.assertFalse(Path(environment["HOME"]).exists())

    def test_mise_resolution_failure_prevents_child_start(self) -> None:
        values = self.mise_shim() | {"FIXTURE_MISE_FAIL": "1"}
        before = self.snapshot(self.old_home)
        result = subprocess.run(
            [WRAPPER, sys.executable, PROBE, "write", "0"],
            env=self.inherited | values, text=True, capture_output=True,
            check=False, timeout=15,
        )
        self.assertEqual(1, result.returncode, result.stderr)
        self.assertEqual("", result.stdout)
        self.assertIn("cannot resolve rg before isolation: fixture resolution failed", result.stderr)
        self.assertEqual(before, self.snapshot(self.old_home))

    def test_real_tool_override_does_not_consult_mise_shim(self) -> None:
        values = self.mise_shim() | {"FIXTURE_MISE_FAIL": "1", "RG_REAL": "/original/rg"}
        environment = self.run_environment(**values)
        self.assertEqual("/original/rg", environment["DOTFILES_TEST_RG_REAL"])
        self.assertFalse(Path(values["FIXTURE_MISE_CALL"]).exists())

    def test_nested_use_retains_the_original_real_tool(self) -> None:
        environment = self.run_environment(
            BB_REAL="/replacement/bb", DOTFILES_TEST_BB_REAL="/original/bb",
        )
        self.assertEqual("/original/bb", environment["DOTFILES_TEST_BB_REAL"])

    def make_tool(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        source = ROOT / "tests/fixtures/test_environment_tool.py"
        subprocess.run(["cp", str(source), str(path)], check=True)
        subprocess.run(["cmp", str(source), str(path)], check=True)
        path.chmod(0o755)
        return path

    def test_native_tool_selection_does_not_promote_sibling_commands(self) -> None:
        tools = ("bb", "java", "jj", "rg")
        public = self.root / "public"
        selected = {tool: self.make_tool(self.root / "native tools" / tool / tool) for tool in tools}
        public_commands = {tool: self.make_tool(public / tool) for tool in (*tools, "docker", "unrelated")}
        # A selected installation contains other commands, including another
        # selected tool. Neither sibling may replace its independent selection.
        for sibling in ("jj", "docker", "unrelated"):
            self.make_tool(selected["rg"].parent / sibling)
        fake = self.make_tool(self.root / "child fakes/jj")
        values = {f"DOTFILES_TEST_{tool.upper()}_REAL": str(path) for tool, path in selected.items()}
        values["PATH"] = str(public) + os.pathsep + self.inherited["PATH"]
        expected = {**selected, "docker": public_commands["docker"], "unrelated": public_commands["unrelated"]}
        for nested in (False, True):
            for child_fake in (False, True):
                with self.subTest(nested=nested, child_fake=child_fake):
                    overrides = values | ({"FIXTURE_COMMAND_PATH": str(fake.parent)} if child_fake else {})
                    arguments = ("nested", str(WRAPPER), "commands") if nested else ("commands",)
                    result, report = self.run_probe(*arguments, *expected, values=overrides)
                    self.assertEqual(0, result.returncode, result.stderr)
                    self.assert_private_home(report)
                    if nested:
                        self.assertEqual(0, report["nested_status"], report["nested_stderr"])
                        report = report["nested"]
                        self.assert_private_home(report)
                    wanted = expected | ({"jj": fake} if child_fake else {})
                    self.assertEqual({name: str(path) for name, path in wanted.items()},
                                     {name: entry["executable"] for name, entry in report["commands"].items()})
                    for tool, path in selected.items():
                        self.assertEqual(str(path), report["environment"][f"DOTFILES_TEST_{tool.upper()}_REAL"])

    def test_native_tool_path_need_not_share_the_command_name(self) -> None:
        fallback = self.make_tool(self.root / "public/rg")
        selected = self.make_tool(self.root / "another installation/custom ripgrep")
        result, report = self.run_probe("commands", "rg", values={
            "PATH": str(fallback.parent) + os.pathsep + self.inherited["PATH"],
            "RG_REAL": str(selected),
        })
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(str(selected), report["commands"]["rg"]["executable"])
        self.assertEqual(str(selected), report["environment"]["DOTFILES_TEST_RG_REAL"])
        self.assert_private_home(report)

    def test_explicit_wrappers_can_find_native_tools_without_exporting_raw_overrides(self) -> None:
        selected = {tool: self.make_tool(self.root / "native tools" / tool / tool) for tool in ("bb", "java", "rg")}
        values = {f"DOTFILES_TEST_{tool.upper()}_REAL": str(path) for tool, path in selected.items()}
        wrappers = {
            "bb": ROOT / "tools/agent-split/bb",
            "java": ROOT / "libexec/agent-wrappers/java",
            "rg": ROOT / "libexec/agent-wrappers/rg",
        }
        result, report = self.run_probe("commands", *map(str, wrappers.values()), values=values)
        self.assertEqual(0, result.returncode, result.stderr)
        for tool, wrapper in wrappers.items():
            self.assertEqual(str(selected[tool]), report["commands"][str(wrapper)]["executable"])
            self.assertNotIn(f"{tool.upper()}_REAL", report["environment"])
        self.assert_private_home(report)

    def test_state_writes_are_private_and_cleanup_preserves_exit_status(self) -> None:
        for status in (0, 23):
            with self.subTest(status=status):
                before = self.snapshot(self.old_home)
                result, report = self.run_probe("write", str(status))
                self.assertEqual(status, result.returncode, result.stderr)
                self.assertEqual(before, self.snapshot(self.old_home))
                self.assert_private_home(report)

    def test_native_babashka_home_is_private_before_inherited_preloads(self) -> None:
        executable = os.environ.get("DOTFILES_TEST_BB_REAL") or shutil.which("bb")
        if not executable:
            self.skipTest("Babashka is required")
        inherited = (ROOT / "tests/fixtures/test_environment_inherited_preload.clj").read_text()
        fixture = ROOT / "tests/fixtures/test_environment_home_probe.clj"
        for nested in (False, True):
            with self.subTest(nested=nested):
                before = self.snapshot(self.old_home)
                result = subprocess.run(
                    [WRAPPER, *([WRAPPER] if nested else []), executable, fixture],
                    env=self.inherited | {"BABASHKA_PRELOADS": inherited},
                    capture_output=True, text=True, check=False, timeout=15,
                )
                self.assertEqual(0, result.returncode, result.stderr)
                report = json.loads(result.stdout)
                self.assertEqual(report["home"], report["property-home"])
                self.assertEqual(report["home"], report["preload-home"])
                self.assertNotEqual(str(self.old_home), report["home"])
                self.assertFalse(Path(report["home"]).exists())
                self.assertEqual(before, self.snapshot(self.old_home))

    def test_java_home_overrides_inherited_options_and_supports_spaces_and_nesting(self) -> None:
        executable = os.environ.get("DOTFILES_TEST_JAVA_REAL") or shutil.which("java")
        if not executable:
            self.skipTest("Java is required")
        fixture = ROOT / "tests/fixtures/TestEnvironmentHomeProbe.java"
        temporary = self.root / "tmp with spaces"
        temporary.mkdir()
        environment = self.inherited | {
            "TMPDIR": str(temporary),
            "JAVA_TOOL_OPTIONS": f'-Duser.home="{self.old_home}"',
            "JDK_JAVA_OPTIONS": f'-Duser.home="{self.old_home}"',
            "_JAVA_OPTIONS": f'-Duser.home="{self.old_home}" -Dtest.existing.option=kept',
        }
        for nested in (False, True):
            with self.subTest(nested=nested):
                before = self.snapshot(self.old_home)
                result = subprocess.run(
                    [WRAPPER, *([WRAPPER] if nested else []), executable, fixture], env=environment,
                    capture_output=True, text=True, check=False, timeout=30,
                )
                self.assertEqual(0, result.returncode, result.stderr)
                home = Path(result.stdout.strip())
                self.assertTrue(home.is_relative_to(temporary))
                self.assertFalse(home.exists())
                self.assertEqual(before, self.snapshot(self.old_home))

    def test_cargo_home_persists_without_reusing_user_config_or_credentials(self) -> None:
        before = self.snapshot(self.old_home)
        homes = []
        for status in (0, 23):
            result, report = self.run_probe("cargo-cache", str(status))
            self.assertEqual(status, result.returncode, result.stderr)
            homes.append(self.assert_private_home(report))
            self.assertEqual(str(self.cargo_home), report["environment"]["CARGO_HOME"])
            self.assertEqual(str(self.cargo_home), report["environment"]["DOTFILES_TEST_CARGO_HOME"])
            self.assertEqual(status == 23, report["cargo_cache_existed"])
            self.assertEqual([], report["cargo_config_files"])
        self.assertNotEqual(*homes)
        self.assertTrue((self.cargo_home / "registry/cache/probe").is_file())
        self.assertEqual(before, self.snapshot(self.old_home))

    def test_default_cargo_home_belongs_to_the_wrapper_checkout(self) -> None:
        wrapper = self.root / "checkout/dev/test-environment"
        wrapper.parent.mkdir(parents=True)
        for source in (WRAPPER, HOME_PRELOAD):
            destination = wrapper.parent / source.name
            subprocess.run(["cp", str(source), str(destination)], check=True)
            subprocess.run(["cmp", str(source), str(destination)], check=True)
        environment = dict(self.inherited)
        environment.pop("DOTFILES_TEST_CARGO_HOME")
        before = self.snapshot(self.old_home)
        result = subprocess.run([wrapper, sys.executable, PROBE, "write", "0"],
            env=environment, text=True, capture_output=True, check=False, timeout=15)
        self.assertEqual(0, result.returncode, result.stderr)
        report = json.loads(result.stdout)
        self.assert_private_home(report)
        expected = self.root / "checkout/target/test-environment/cargo"
        self.assertEqual(str(expected), report["environment"]["CARGO_HOME"])
        self.assertEqual(0o700, expected.stat().st_mode & 0o777)
        self.assertEqual(before, self.snapshot(self.old_home))

    def test_nested_use_keeps_the_same_cargo_home(self) -> None:
        result, outer = self.run_probe("nested", str(WRAPPER))
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(0, outer["nested_status"], outer["nested_stderr"])
        for report in (outer, outer["nested"]):
            self.assert_private_home(report)
            self.assertEqual(str(self.cargo_home), report["environment"]["CARGO_HOME"])

    def test_invalid_cargo_home_prevents_child_start_without_falling_back(self) -> None:
        self.cargo_home.write_text("not a directory")
        before = self.snapshot(self.old_home)
        result = subprocess.run([WRAPPER, sys.executable, PROBE, "write", "0"],
            env=self.inherited, text=True, capture_output=True, check=False, timeout=15)
        self.assertEqual(1, result.returncode, result.stderr)
        self.assertEqual("", result.stdout)
        self.assertIn("cannot prepare Cargo test home", result.stderr)
        self.assertIn(str(self.cargo_home), result.stderr)
        self.assertEqual("not a directory", self.cargo_home.read_text())
        self.assertEqual(before, self.snapshot(self.old_home))

    @unittest.skipIf(os.geteuid() == 0, "root bypasses directory permissions")
    def test_read_only_cargo_home_prevents_child_start(self) -> None:
        self.cargo_home.mkdir(mode=0o500)
        self.addCleanup(self.cargo_home.chmod, 0o700)
        before = self.snapshot(self.old_home)
        result = subprocess.run([WRAPPER, sys.executable, PROBE, "write", "0"],
            env=self.inherited, text=True, capture_output=True, check=False, timeout=15)
        self.assertEqual(1, result.returncode, result.stderr)
        self.assertEqual("", result.stdout)
        self.assertIn("directory requires write and search access", result.stderr)
        self.assertEqual(before, self.snapshot(self.old_home))

    @unittest.skipUnless(shutil.which("fish"), "Fish is required")
    def test_interactive_fish_loads_config_without_background_completion_generation(self) -> None:
        before = self.snapshot(self.old_home)
        self.inherited.pop("FISH_UNIT_TESTS_RUNNING", None)
        for inherited in ({}, {"FISH_UNIT_TESTS_RUNNING": "0"}):
            with self.subTest(inherited=inherited):
                result, report = self.run_probe("fish", shutil.which("fish"),
                    str(ROOT / "tests/fixtures/test_environment_fish.fish"), values=inherited)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(report["fish_status"], 0, report["fish_stderr"])
                self.assertIsNotNone(report["fish_test_mode"])
                self.assertTrue(report["fish_startup_ran"])
                self.assertFalse(report["fish_completions_generated"])
                self.assert_private_home(report)
                self.assertEqual(before, self.snapshot(self.old_home))

    def test_explicit_sdk_path_is_preserved_without_modification(self) -> None:
        self.make_sdk(self.installed_sdk_path())
        sdk = self.make_sdk(self.root / "explicit SDK")
        before_sdk = self.snapshot(sdk)
        before_home = self.snapshot(self.old_home)
        result, report = self.run_probe("write", "0", values={"PI_PACKAGE_DIR": str(sdk)})
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(str(sdk), report["environment"].get("PI_PACKAGE_DIR"))
        self.assertEqual(before_sdk, self.snapshot(sdk))
        self.assertEqual(before_home, self.snapshot(self.old_home))
        self.assert_private_home(report)

    def test_installed_sdk_is_discovered_before_home_changes(self) -> None:
        sdk = self.make_sdk(self.installed_sdk_path())
        before = self.snapshot(self.old_home)
        result, report = self.run_probe("write", "0")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(str(sdk), report["environment"].get("PI_PACKAGE_DIR"))
        self.assertEqual(before, self.snapshot(self.old_home))
        self.assert_private_home(report)

    def test_sdk_discovery_requires_package_json(self) -> None:
        self.installed_sdk_path().mkdir(parents=True)
        for values in ({}, {"PI_PACKAGE_DIR": ""}):
            with self.subTest(values=values):
                before = self.snapshot(self.old_home)
                result, report = self.run_probe("write", "0", values=values)
                self.assertEqual(0, result.returncode, result.stderr)
                # An empty override also defeats the Node worker's ?? fallback.
                self.assertNotIn("PI_PACKAGE_DIR", report["environment"])
                self.assertEqual(before, self.snapshot(self.old_home))
                self.assert_private_home(report)

    def test_sdk_symlinks_resolve_before_nested_home_isolation(self) -> None:
        sdk = self.make_sdk(self.root / "source/packages/coding-agent")
        installed = self.installed_sdk_path()
        installed.parent.mkdir(parents=True)
        installed.symlink_to(sdk, target_is_directory=True)
        alias = self.root / "explicit SDK link"
        alias.symlink_to(installed, target_is_directory=True)
        before_sdk = self.snapshot(sdk)
        before_home = self.snapshot(self.old_home)
        for values in ({}, {"PI_PACKAGE_DIR": str(alias)}):
            with self.subTest(values=values):
                result, outer = self.run_probe("nested", str(WRAPPER), values=values)
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertEqual(0, outer["nested_status"], outer["nested_stderr"])
                for report in (outer, outer["nested"]):
                    self.assertEqual(str(sdk), report["environment"]["PI_PACKAGE_DIR"])
                    self.assert_private_home(report)
        self.assertEqual(before_sdk, self.snapshot(sdk))
        self.assertEqual(before_home, self.snapshot(self.old_home))

    def make_nvim_plugins(self, data: Path) -> Path:
        plugins = data / "nvim/lazy"
        entrypoint = plugins / "lazy.nvim/lua/lazy/init.lua"
        entrypoint.parent.mkdir(parents=True)
        entrypoint.write_text("return {}\n")
        return plugins

    def test_nvim_plugins_are_discovered_before_data_isolation(self) -> None:
        for use_xdg in (False, True):
            with self.subTest(use_xdg=use_xdg):
                if use_xdg:
                    data = self.old_home / "xdg_data_home"
                    self.inherited["XDG_DATA_HOME"] = str(data)
                else:
                    self.inherited.pop("XDG_DATA_HOME")
                    data = self.old_home / ".local/share"
                plugins = self.make_nvim_plugins(data)
                before = self.snapshot(self.old_home)
                result, report = self.run_probe("write", "0")
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertEqual(str(plugins), report["environment"].get("DOTFILES_TEST_NVIM_PLUGINS"))
                self.assertEqual(before, self.snapshot(self.old_home))
                self.assert_private_home(report)

    def test_explicit_nvim_plugins_survive_nested_isolation(self) -> None:
        self.make_nvim_plugins(Path(self.inherited["XDG_DATA_HOME"]))
        plugins = self.make_nvim_plugins(self.root / "explicit data")
        before = self.snapshot(plugins)
        result, outer = self.run_probe(
            "nested", str(WRAPPER),
            values={"DOTFILES_TEST_NVIM_PLUGINS": str(plugins)},
        )
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(0, outer["nested_status"], outer["nested_stderr"])
        for report in (outer, outer["nested"]):
            self.assertEqual(str(plugins), report["environment"]["DOTFILES_TEST_NVIM_PLUGINS"])
            self.assert_private_home(report)
        self.assertEqual(before, self.snapshot(plugins))

    def test_nvim_discovery_requires_lazy_entrypoint(self) -> None:
        plugins = Path(self.inherited["XDG_DATA_HOME"]) / "nvim/lazy/lazy.nvim"
        plugins.mkdir(parents=True)
        for values in ({}, {"DOTFILES_TEST_NVIM_PLUGINS": ""}):
            with self.subTest(values=values):
                environment = self.run_environment(**values)
                self.assertNotIn("DOTFILES_TEST_NVIM_PLUGINS", environment)

    def test_nested_wrapper_has_independent_home_and_retains_sdk_and_tools(self) -> None:
        sdk = self.make_sdk(self.installed_sdk_path())
        before = self.snapshot(self.old_home)
        result, outer = self.run_probe("nested", str(WRAPPER), values={"BB_REAL": "/original/bb"})
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(0, outer["nested_status"], outer["nested_stderr"])
        inner = outer["nested"]
        self.assertNotEqual(outer["home"], inner["home"])
        self.assertTrue(outer["outer_home_exists_after"])
        self.assertFalse(outer["nested_home_exists_after"])
        for report in (outer, inner):
            self.assertEqual(str(sdk), report["environment"].get("PI_PACKAGE_DIR"))
            self.assertEqual("/original/bb", report["environment"]["DOTFILES_TEST_BB_REAL"])
            self.assert_private_home(report)
        self.assertEqual(before, self.snapshot(self.old_home))

    @unittest.skipUnless(shutil.which("jj"), "native jj is required")
    def test_private_home_jj_does_not_track_repository_local_state(self) -> None:
        jj = os.environ.get("DOTFILES_TEST_JJ_REAL") or shutil.which("jj")
        checkout = self.root / "checkout"
        subprocess.run(
            [jj, "git", "init", "--colocate", str(checkout)], cwd=self.root,
            env=self.inherited, text=True, capture_output=True, check=True,
        )
        subprocess.run(["cp", ROOT / ".gitignore", checkout / ".gitignore"], check=True)
        subprocess.run(["cmp", ROOT / ".gitignore", checkout / ".gitignore"], check=True)
        (checkout / "keep.py").write_text("tracked source\n")
        generated = (
            "node_modules/package/index.js", "notes/draft.md",
            ".pytest_cache/state", ".session.vim", "config/.session.vim",
        )
        for name in generated:
            path = checkout / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("local state\n")
        result = subprocess.run(
            [WRAPPER, jj, "status"], cwd=checkout, env=self.inherited,
            text=True, capture_output=True, check=False, timeout=15,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        files = subprocess.run(
            [jj, "--ignore-working-copy", "file", "list", "-r", "@"],
            cwd=checkout, env=self.inherited, text=True, capture_output=True,
            check=True,
        ).stdout.splitlines()
        self.assertEqual([".gitignore", "keep.py"], files)
        for name in generated:
            self.assertEqual("local state\n", (checkout / name).read_text())

    def test_stdin_reaches_child_unchanged(self) -> None:
        text = "ordinary stdin\nsecond line\twith spaces\n"
        result, report = self.run_probe("stdin", input=text)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(text, report["stdin"])
        self.assert_private_home(report)

    def test_native_child_signal_status_is_preserved_after_home_cleanup(self) -> None:
        for terminating_signal in (signal.SIGTERM, signal.SIGKILL):
            with self.subTest(signal=terminating_signal):
                before = self.snapshot(self.old_home)
                result, report = self.run_probe("native-signal", str(int(terminating_signal)))
                self.assertEqual(-terminating_signal, result.returncode, result.stderr)
                self.assertEqual(before, self.snapshot(self.old_home))
                self.assert_private_home(report)

    def test_term_is_forwarded_and_child_finishes_before_home_cleanup(self) -> None:
        self.check_forwarded_signal(signal.SIGTERM, 37)

    def test_int_is_forwarded_and_child_status_is_preserved(self) -> None:
        self.check_forwarded_signal(signal.SIGINT, 130)

    def check_forwarded_signal(self, forwarded_signal, expected_status) -> None:
        before = self.snapshot(self.old_home)
        child = subprocess.Popen(
            [WRAPPER, sys.executable, PROBE, "signal"], env=self.inherited,
            text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        try:
            with selectors.DefaultSelector() as selector:
                selector.register(child.stdout, selectors.EVENT_READ)
                self.assertTrue(selector.select(timeout=5), "child did not become ready")
            ready = json.loads(child.stdout.readline())
            child.send_signal(forwarded_signal)  # Original wrapper PID, not helper PID.
            output, errors = child.communicate(timeout=5)
            self.assertEqual(expected_status, child.returncode, errors)
            completed = json.loads(output)
            self.assertTrue(completed["cleanup_completed"])
            self.assertTrue(completed["home_exists_during_cleanup"])
            self.assertEqual(ready["home"], completed["home"])
            self.assertEqual(before, self.snapshot(self.old_home))
            self.assert_private_home(completed)
        finally:
            if child.poll() is None:
                child.kill()
                child.communicate(timeout=15)


if __name__ == "__main__":
    unittest.main()
