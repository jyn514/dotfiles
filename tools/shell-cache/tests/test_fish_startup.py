"""Real Git discovery and Fish consumption with private user/repository state."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[3]
GIT = shutil.which("git")
FISH = shutil.which("fish")


@unittest.skipUnless(GIT and FISH, "Git and Fish are required")
class FishStartupTest(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.home = self.directory / "home with spaces"
        (self.home / ".config/git").mkdir(parents=True)
        (self.home / ".local/bin").mkdir(parents=True)
        (self.home / ".profile").symlink_to(ROOT / "config/profile")
        self.included = self.home / ".local/gitconfig"
        self.included.write_text("[alias]\n  user-included = log --oneline\n")
        self.global_config = self.home / ".config/git/config"
        self.global_config.write_text(
            "[alias]\n  user-global = status --short\n"
            "  user-shell = !printf 'hello world'\n"
            "[include]\n  path = ~/.local/gitconfig\n"
        )
        self.calls = self.directory / "hook-calls"
        self.environment = {
            "HOME": str(self.home),
            # --no-config omits Fish's fish_user_paths event handler. Supply
            # the paths that real startup would install, without host tooling.
            "PATH": f"{ROOT / 'bin'}:{self.home / '.local/bin'}:/usr/bin:/bin",
            "XDG_CONFIG_HOME": str(self.home / ".config"),
            "TERM": "xterm-256color",
            "SSH_AUTH_SOCK": "fixture-agent-not-contacted",
            "HOOK_CALLS": str(self.calls),
            "PROFILE_FISH": str(ROOT / "config/config.fish"),
            "LC_ALL": "C.UTF-8",
        }
        self.a, self.b = self.directory / "a", self.directory / "b"
        for repository in (self.a, self.b):
            self.git("init", "--quiet", str(repository))
            self.git("-C", str(repository), "config", "alias.repo-only", repository.name)
        cargo = self.home / ".local/bin/cargo"
        cargo.write_text("#!/bin/sh\nprintf 'Installed Commands:\\n'\n")
        cargo.chmod(0o755)
        self.tool("bat", "print('bat 0.25.0')")
        self.tool("atuin", "print('function _atuin_search; end\\nset -g TEST_ATUIN loaded')")
        self.tool("zoxide", "print('function __zoxide_z; end\\nfunction z; end\\nset -g TEST_ZOXIDE loaded')")
        self.tool("direnv", "print('set -g TEST_DIRENV loaded')")

    def git(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [GIT, *arguments], env=self.environment, text=True,
            capture_output=True, check=True, timeout=10,
        )

    def tool(self, name: str, body: str) -> None:
        path = self.home / ".local/bin" / name
        path.write_text(
            f"#!{sys.executable}\n"
            "import json, os, sys\n"
            f"name = {name!r}\n"
            "with open(os.environ['HOOK_CALLS'], 'a') as output:\n"
            "    output.write(json.dumps([name, *sys.argv[1:]]) + '\\n')\n"
            f"{body}\n"
            "raise SystemExit(int(os.environ.get('FAIL_' + name.upper(), '0')))\n"
        )
        path.chmod(0o755)

    def startup(self, cwd: Path, command: str = "abbr --show", **environment: str):
        return subprocess.run(
            [FISH, "--no-config", "--interactive",
             str(ROOT / "tests/setup/fixtures/profile_command.fish"), command],
            cwd=cwd, env=self.environment | environment,
            stdin=subprocess.DEVNULL, text=True, capture_output=True, timeout=15,
        )

    def cache(self) -> Path:
        caches = list((self.home / ".local/config").glob("fish-startup-hooks-*.fish"))
        self.assertEqual(1, len(caches))
        return caches[0]

    def hook_calls(self):
        return [json.loads(line) for line in self.calls.read_text().splitlines()]

    def test_real_fish_keeps_user_aliases_but_never_replays_repository_aliases(self) -> None:
        for repository in (self.a, self.b):
            with self.subTest(repository=repository.name):
                result = self.startup(repository)
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertIn("user-global", result.stdout)
                self.assertIn("user-included", result.stdout)
                self.assertIn("guser-shell", result.stdout)
                self.assertIn("printf", result.stdout)
                self.assertNotIn("repo-only", result.stdout)
                self.assertNotIn("repo-stale", result.stdout)
                native = self.git("-C", str(repository), "config", "--get", "alias.repo-only")
                self.assertEqual(repository.name + "\n", native.stdout)
        self.assertEqual(4, len(self.hook_calls()))
        self.assertNotIn("user-global", self.cache().read_text())
        self.assertNotIn("user-included", self.cache().read_text())

    def test_combined_cache_left_by_previous_startup_is_not_sourced(self) -> None:
        old_cache = self.home / ".local/config/fish-startup-11111.fish"
        old_cache.parent.mkdir(parents=True)
        old_cache.write_text("abbr --add --global repo-stale -- unsafe-old-snapshot\n")
        result = self.startup(self.a)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("user-global", result.stdout)
        self.assertNotIn("repo-stale", result.stdout)
        self.assertEqual(4, len(self.hook_calls()))
        self.assertTrue(old_cache.exists())

    def test_included_config_changes_are_fresh_without_rewriting_or_rerunning_hooks(self) -> None:
        first = self.startup(self.a)
        self.assertEqual(0, first.returncode, first.stderr)
        cache = self.cache()
        before = (cache.read_bytes(), cache.stat().st_mtime_ns, self.hook_calls())
        old_time = self.included.stat().st_mtime_ns
        self.included.write_text("[alias]\n  user-included = diff --stat\n")
        # Invalidation does not depend on filesystem mtimes or this checkout.
        os.utime(self.included, ns=(old_time, old_time))
        second = self.startup(
            self.b,
            "abbr --show; printf 'HOOKS:%s:%s:%s\\n' $TEST_ATUIN $TEST_ZOXIDE $TEST_DIRENV",
        )
        self.assertEqual(0, second.returncode, second.stderr)
        self.assertIn("diff --stat", second.stdout)
        self.assertNotIn("log --oneline", second.stdout)
        self.assertIn("HOOKS:loaded:loaded:loaded", second.stdout)
        self.assertEqual(before, (cache.read_bytes(), cache.stat().st_mtime_ns, self.hook_calls()))

    def test_nested_and_newly_created_includes_use_native_git_resolution(self) -> None:
        nested = self.home / ".local/nested config"
        self.included.write_text('[include]\n  path = "nested config"\n')
        first = self.startup(self.a)
        self.assertEqual(0, first.returncode, first.stderr)
        self.assertNotIn("new-include", first.stdout)
        nested.write_text("[alias]\n  new-include = show --stat\n")
        second = self.startup(self.b)
        self.assertEqual(0, second.returncode, second.stderr)
        self.assertIn("new-include", second.stdout)
        self.assertIn("show --stat", second.stdout)
        self.assertEqual(4, len(self.hook_calls()))

    def test_global_scope_alone_is_insufficient_and_neutral_context_blocks_repo_conditions(self) -> None:
        conditional = self.home / "conditional"
        conditional.write_text("[alias]\n  repo-condition = reset\n")
        self.git("-C", str(self.a), "config", "remote.origin.url", "https://repo.invalid/project")
        with self.global_config.open("a") as config:
            config.write(
                f'[includeIf "gitdir:{self.a}/.git"]\n  path = {conditional}\n'
                f'[includeIf "onbranch:*"]\n  path = {conditional}\n'
                '[includeIf "hasconfig:remote.*.url:https://repo.invalid/**"]\n'
                f'  path = {conditional}\n'
            )
        native = self.git("-C", str(self.a), "config", "--global", "--includes", "--get-regexp", r"^alias\.")
        self.assertIn("repo-condition", native.stdout)
        inherited = {
            "GIT_DIR": str(self.a / ".git"),
            "GIT_WORK_TREE": str(self.a),
            "GIT_COMMON_DIR": str(self.a / ".git"),
        }
        for repository in (self.a, self.b):
            result = self.startup(repository, **inherited)
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertNotIn("repo-condition", result.stdout)
            self.assertNotIn("repo-only", result.stdout)
            self.assertIn("user-included", result.stdout)

    def test_explicit_global_file_and_repository_independent_hasconfig_include_are_preserved(self) -> None:
        selected = self.home / "explicit global"
        selected.write_text(
            '[remote "user-config"]\n  url = https://example.invalid/project\n'
            '[includeIf "hasconfig:remote.*.url:https://example.invalid/**"]\n'
            '  path = ~/.local/gitconfig\n'
        )
        result = self.startup(self.a, GIT_CONFIG_GLOBAL=str(selected))
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("user-included", result.stdout)
        self.assertNotIn("user-global", result.stdout)

    def test_native_xdg_and_home_global_sources_keep_git_precedence(self) -> None:
        cross_global = self.home / "cross-global-include"
        cross_global.write_text("[alias]\n  user-cross-global = show --stat\n")
        with self.global_config.open("a") as config:
            config.write(
                '[includeIf "hasconfig:remote.*.url:https://homeglobal.invalid/**"]\n'
                f'  path = {cross_global}\n'
            )
        (self.home / ".gitconfig").write_text(
            "[alias]\n  user-home = branch\n  user-global = diff --stat\n"
            '[remote "user-global"]\n  url = https://homeglobal.invalid/project\n'
        )
        result = self.startup(
            self.a,
            'abbr --show | while read --tokenize --local --array fields; '
            'if test "$fields[-2]" = user-global; printf %s "$fields[-1]"; end; end',
        )
        self.assertEqual(0, result.returncode, result.stderr)
        native = self.git("config", "--get", "alias.user-global")
        self.assertEqual(native.stdout.removesuffix("\n"), result.stdout)
        all_aliases = self.startup(self.b)
        self.assertEqual(0, all_aliases.returncode, all_aliases.stderr)
        self.assertIn("user-home", all_aliases.stdout)
        self.assertIn("user-included", all_aliases.stdout)
        self.assertIn("user-cross-global", all_aliases.stdout)

    def test_effective_alias_name_is_resolved_before_switching_shell_abbreviation_form(self) -> None:
        transitions = (
            ("status --short", "!printf effective-shell"),
            ("!printf obsolete-shell", "log --oneline"),
        )
        for source in ("global-files", "include-chain"):
            for lower, higher in transitions:
                with self.subTest(source=source, lower=lower, higher=higher):
                    self.global_config.write_text(f"[alias]\n  precedence-probe = {lower}\n")
                    home_config = self.home / ".gitconfig"
                    if source == "global-files":
                        home_config.write_text(f"[alias]\n  precedence-probe = {higher}\n")
                    else:
                        home_config.unlink(missing_ok=True)
                        with self.global_config.open("a") as config:
                            config.write("[include]\n  path = ~/.local/gitconfig\n")
                        self.included.write_text(f"[alias]\n  precedence-probe = {higher}\n")
                    native = self.git(
                        "-C", str(self.b), "config", "--get", "alias.precedence-probe"
                    ).stdout.removesuffix("\n")
                    self.assertEqual(higher, native)
                    result = self.startup(
                        self.a,
                        'abbr --show | while read --tokenize --local --array fields; '
                        'if contains -- "$fields[-2]" precedence-probe gprecedence-probe; '
                        'printf "%s\\0%s\\0" "$fields[-2]" "$fields[-1]"; end; end',
                    )
                    self.assertEqual(0, result.returncode, result.stderr)
                    expected_name = "gprecedence-probe" if native.startswith("!") else "precedence-probe"
                    expected_value = native[1:] if native.startswith("!") else native
                    # Exactly one native-effective value: no obsolete ordinary
                    # or g-prefixed form may survive from a losing definition.
                    self.assertEqual(expected_name + "\0" + expected_value + "\0", result.stdout)

    def test_system_and_injected_command_config_cannot_supply_aliases_or_include_conditions(self) -> None:
        system = self.directory / "system-config"
        system.write_text(
            '[alias]\n  non-user-direct = reset\n'
            '[remote "system"]\n  url = https://nonuser.invalid/system\n'
        )
        conditional = self.home / "non-user-conditional"
        conditional.write_text("[alias]\n  non-user-condition = reset\n")
        with self.global_config.open("a") as config:
            config.write(
                '[includeIf "hasconfig:remote.*.url:https://nonuser.invalid/**"]\n'
                f'  path = {conditional}\n'
            )
        cases = {
            "system": {"GIT_CONFIG_SYSTEM": str(system)},
            "command-count": {
                "GIT_CONFIG_COUNT": "2",
                "GIT_CONFIG_KEY_0": "alias.non-user-direct",
                "GIT_CONFIG_VALUE_0": "reset",
                "GIT_CONFIG_KEY_1": "remote.injected.url",
                "GIT_CONFIG_VALUE_1": "https://nonuser.invalid/command",
            },
            "command-parameters": {
                "GIT_CONFIG_PARAMETERS":
                    "'alias.non-user-direct=reset' "
                    "'remote.injected.url=https://nonuser.invalid/parameters'",
            },
            "legacy-file-selector": {"GIT_CONFIG": str(system)},
        }
        neutral = self.directory / "native-neutral"
        neutral.mkdir()
        for name, environment in cases.items():
            with self.subTest(source=name):
                native = subprocess.run(
                    [GIT, "-C", str(neutral), "config", "--includes", "--get-regexp", r"^alias\."],
                    env=self.environment | environment,
                    text=True, capture_output=True, check=True, timeout=10,
                )
                self.assertIn("non-user-direct", native.stdout)
                if name != "legacy-file-selector":
                    self.assertIn("non-user-condition", native.stdout)
                result = self.startup(self.a, **environment)
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertIn("user-global", result.stdout)
                self.assertIn("user-included", result.stdout)
                self.assertNotIn("non-user-direct", result.stdout)
                self.assertNotIn("non-user-condition", result.stdout)

    def test_relative_explicit_global_file_stays_anchored_before_neutral_chdir(self) -> None:
        selected = self.a / "chosen-global"
        selected.write_text("[include]\n  path = ~/.local/gitconfig\n")
        result = self.startup(self.a, GIT_CONFIG_GLOBAL="chosen-global")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("user-included", result.stdout)
        self.assertNotIn("user-global", result.stdout)

    def test_multiline_shell_alias_is_literal_data_not_generated_code(self) -> None:
        sentinel = self.directory / "must-not-exist"
        value = f"!printf '%s\\n' \"$(touch '{sentinel}')\";\n# café\tquoted ' \\\\\n\n"
        self.git("config", "--file", str(self.global_config), "alias.user-literal", value)
        result = self.startup(
            self.a,
            'abbr --show | while read --tokenize --local --array fields; '
            'if test "$fields[-2]" = guser-literal; printf %s "$fields[-1]"; end; end',
        )
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(value[1:], result.stdout)
        self.assertFalse(sentinel.exists())

    def test_absent_aliases_are_successful_and_hooks_still_load(self) -> None:
        self.global_config.write_text("[user]\n  name = Fixture\n")
        result = self.startup(self.a, "printf '%s:%s:%s\\n' $TEST_ATUIN $TEST_ZOXIDE $TEST_DIRENV")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("loaded:loaded:loaded\n", result.stdout)
        self.assertEqual(4, len(self.hook_calls()))

    def test_alias_failure_never_consumes_partial_output_or_touches_hook_cache(self) -> None:
        first = self.startup(self.a)
        self.assertEqual(0, first.returncode, first.stderr)
        cache = self.cache()
        before = (cache.read_bytes(), cache.stat().st_mtime_ns, self.hook_calls())
        self.tool("git", "print('global\\0alias.partial\\nstatus', end='\\0'); raise SystemExit(23)")
        result = self.startup(self.b)
        self.assertEqual(23, result.returncode, result.stderr)
        self.assertNotIn("partial", result.stdout)
        # The fake Git itself logs once; no hook producers run after failure.
        self.assertEqual(before[:2], (cache.read_bytes(), cache.stat().st_mtime_ns))
        self.assertEqual(before[2], self.hook_calls()[:-1])
        self.assertEqual("git", self.hook_calls()[-1][0])

    def appear_earlier_atuin(self) -> tuple[Path, tuple[bytes, int]]:
        earlier = self.home / ".local/bin/atuin"
        # Metacharacters and newlines must remain literal path data, not shell
        # syntax or extra command-vector elements in the identity header.
        later = self.directory / "later ' \\ $() ; #\n bin"
        later.mkdir()
        shadowing = self.directory / "earlier \\ ' $() ; #\r\n bin"
        shadowing.mkdir()
        earlier.rename(later / "atuin")
        self.environment["PATH"] += ":" + str(shadowing) + ":" + str(later)
        first = self.startup(self.a, "printf '%s\\n' $TEST_ATUIN")
        self.assertEqual(0, first.returncode, first.stderr)
        self.assertEqual("loaded\n", first.stdout)
        cache = self.cache()
        before = (cache.read_bytes(), cache.stat().st_mtime_ns)
        self.tool("atuin", "print('function _atuin_search; end\\nset -g TEST_ATUIN shadowed')")
        earlier.rename(shadowing / "atuin")
        earlier = shadowing / "atuin"
        os.utime(earlier, ns=(1_000_000_000, 1_000_000_000))
        self.assertLess(earlier.stat().st_mtime_ns, before[1])
        return earlier, before

    def test_earlier_path_candidate_with_older_mtime_changes_consumed_hook(self) -> None:
        earlier, before = self.appear_earlier_atuin()
        result = self.startup(
            self.b,
            "printf 'SELECTED:'; command --search atuin; "
            "printf 'CONSUMED:%s\\n' $TEST_ATUIN",
        )
        self.assertEqual(0, result.returncode, result.stderr)
        # subprocess text mode normalizes CRLF in the printed path.
        expected = f"SELECTED:{earlier}\nCONSUMED:shadowed\n".replace("\r\n", "\n")
        self.assertEqual(expected, result.stdout)
        self.assertNotEqual(before[0], self.cache().read_bytes())
        self.assertEqual(8, len(self.hook_calls()))
        warm_before = (self.cache().read_bytes(), self.cache().stat().st_mtime_ns, self.hook_calls())
        warm = self.startup(self.a, "printf '%s\\n' $TEST_ATUIN")
        self.assertEqual(0, warm.returncode, warm.stderr)
        self.assertEqual("shadowed\n", warm.stdout)
        self.assertEqual(
            warm_before,
            (self.cache().read_bytes(), self.cache().stat().st_mtime_ns, self.hook_calls()),
        )

    def test_failed_identity_change_preserves_old_bytes_and_mtime_then_retries(self) -> None:
        _, before = self.appear_earlier_atuin()
        failed = self.startup(self.b, "printf '%s\\n' $TEST_ATUIN", FAIL_ZOXIDE="24")
        self.assertEqual(0, failed.returncode, failed.stderr)
        self.assertIn("using previous cache", failed.stderr)
        self.assertEqual("loaded\n", failed.stdout)
        self.assertEqual(before, (self.cache().read_bytes(), self.cache().stat().st_mtime_ns))
        self.assertEqual(7, len(self.hook_calls()))
        retry = self.startup(self.a, "printf '%s\\n' $TEST_ATUIN")
        self.assertEqual(0, retry.returncode, retry.stderr)
        self.assertEqual("shadowed\n", retry.stdout)
        self.assertEqual(11, len(self.hook_calls()))

    def test_hook_producer_failure_preserves_and_consumes_previous_hook_cache(self) -> None:
        first = self.startup(self.a)
        self.assertEqual(0, first.returncode, first.stderr)
        cache = self.cache()
        before = cache.read_bytes()
        # Make one dependency newer without touching authoritative sources.
        atuin = self.home / ".local/bin/atuin"
        newer = cache.stat().st_mtime_ns + 2_000_000_000
        os.utime(atuin, ns=(newer, newer))
        result = self.startup(
            self.b, "printf '%s:%s:%s\\n' $TEST_ATUIN $TEST_ZOXIDE $TEST_DIRENV",
            FAIL_ZOXIDE="24",
        )
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("using previous cache", result.stderr)
        self.assertEqual("loaded:loaded:loaded\n", result.stdout)
        self.assertEqual(before, cache.read_bytes())


if __name__ == "__main__":
    unittest.main()
