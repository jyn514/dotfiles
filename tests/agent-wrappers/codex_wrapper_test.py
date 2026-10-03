#!/usr/bin/env python3

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
WRAPPER = ROOT / "bin/codex"


class CodexWrapperTests(unittest.TestCase):
    def test_native_commands_bypass_interactive_setup(self) -> None:
        commands = [
            ["app-server", "--listen", "stdio://"],
            ["execpolicy", "check", "--rules", "generated rules", "jj", "status"],
        ]
        for arguments in commands:
            with self.subTest(command=arguments[0]), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                fake_bin = root / "bin"
                fake_bin.mkdir()
                (fake_bin / "codex").symlink_to(ROOT / "tests/fixtures/codex_native_command.sh")
                (fake_bin / "bb").symlink_to(
                    ROOT / "tests/fixtures/codex_unexpected_permission_generation.sh"
                )
                codex_home = root / "private-codex"
                environment = os.environ | {
                    "HOME": str(root),
                    "CODEX_HOME": str(codex_home),
                    "CODEX_DEVELOPER_INSTRUCTIONS_FILE": str(root / "missing-manifest"),
                    "CODEX_TEST_EXIT_STATUS": "23",
                    "CODEX_TEST_GENERATION_EXIT_STATUS": "89",
                    "PATH": f"{fake_bin}:{os.environ['PATH']}",
                }
                environment.pop("DOTFILES_SANDBOX", None)

                result = subprocess.run(
                    [str(WRAPPER), *arguments],
                    env=environment, text=True, capture_output=True,
                )

                self.assertEqual(23, result.returncode, result.stderr)
                self.assertEqual(arguments, result.stdout.splitlines())
                self.assertEqual("", result.stderr)
                self.assertFalse(codex_home.exists())

    def test_administrative_commands_do_not_receive_runtime_profile(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fake_bin = root / "bin"
            fake_bin.mkdir()
            (fake_bin / "codex").symlink_to(shutil.which("echo"))
            codex_home = root / ".codex"
            codex_home.mkdir()
            (codex_home / "developer-instructions.md").write_text("")
            environment = os.environ | {
                "DOTFILES_SANDBOX": "1",
                "CODEX_HOME": str(codex_home),
                "PATH": f"{fake_bin}:{os.environ['PATH']}",
            }
            for arguments in (
                ["app-server", "daemon", "stop"], ["features", "list"],
                ["login", "status"], ["doctor"], ["update"], ["plugin", "list"],
                ["completion", "fish"], ["logout"], ["remote-control", "--help"],
                ["apply", "--help"], ["cloud", "--help"], ["exec-server", "--help"],
                ["migrate-rollouts"], ["help"], ["debug", "models"],
            ):
                with self.subTest(arguments=arguments):
                    result = subprocess.run(
                        [str(WRAPPER), *arguments], env=environment,
                        text=True, capture_output=True,
                    )
                    self.assertEqual(0, result.returncode, result.stderr)
                    self.assertNotIn("--profile", result.stdout.split())
                    self.assertTrue(result.stdout.rstrip().endswith(" ".join(arguments)))
            for arguments in (
                ["resume", "--all"], ["exec", "prompt"], ["mcp", "list"],
                ["debug", "prompt-input"], ["prompt"],
            ):
                with self.subTest(arguments=arguments):
                    result = subprocess.run(
                        [str(WRAPPER), *arguments], env=environment,
                        text=True, capture_output=True,
                    )
                    self.assertEqual(0, result.returncode, result.stderr)
                    self.assertEqual(["--profile", "dotfiles"], result.stdout.split()[:2])

    def test_instruction_includes_resolve_from_symlink_location(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "tracked"
            source.mkdir()
            (source / "developer-instructions.md").write_text("@breq.md\n")
            installed = root / ".codex"
            installed.mkdir()
            (installed / "developer-instructions.md").symlink_to(
                source / "developer-instructions.md"
            )
            (installed / "breq.md").write_text("ancillary instructions\n")

            result = subprocess.run(
                [
                    str(ROOT / "libexec/expand-codex-instructions"),
                    str(installed / "developer-instructions.md"),
                ],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
            )

        self.assertEqual("ancillary instructions\n", result.stdout)

    def test_injects_shared_voice_as_developer_instructions(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fake_bin = root / "bin"
            fake_bin.mkdir()
            codex = fake_bin / "codex"
            codex.write_text(
                '#!/bin/sh\n'
                'printf "%s\\n" "$@"\n'
                'printf "PATH=%s\\n" "$PATH"\n'
                'printf "\\n[tui.model_availability_nux]\\n\\\"gpt-test\\\" = 1\\n" '
                '>> "$HOME/.codex/dotfiles.config.toml"\n'
            )
            codex.chmod(0o755)
            codex_home = root / ".codex"
            codex_home.mkdir()
            profile = codex_home / "dotfiles.config.toml"
            profile.write_text(
                'model = "gpt-test"\n\n'
                '[projects."/generated"]\n'
                'trust_level = "trusted"\n',
                encoding="utf-8",
            )
            config = codex_home / "config.toml"
            config.write_text('[history]\npersistence = "save-all"\n', encoding="utf-8")
            rules_directory = codex_home / "rules"
            rules_directory.mkdir()
            legacy_source = root / "tracked-codex.rules"
            legacy_source.write_text("legacy rules\n")
            os.link(legacy_source, rules_directory / "default.rules")
            first = codex_home / "first.md"
            second = codex_home / "second file.md"
            nested = codex_home / "nested.md"
            first.write_text("first instructions\n@nested.md\n", encoding="utf-8")
            second.write_text("second instructions", encoding="utf-8")
            nested.write_text("nested instructions\n", encoding="utf-8")
            manifest = codex_home / "developer-instructions.md"
            manifest.write_text("# Shared instruction files\n@first.md\n@second file.md\n", encoding="utf-8")
            environment = os.environ.copy()
            environment["HOME"] = str(root)
            environment.pop("CODEX_HOME", None)
            environment.pop("CODEX_DEVELOPER_INSTRUCTIONS_FILE", None)
            environment["PATH"] = f"{fake_bin}:{environment['PATH']}"

            output = subprocess.run(
                [str(WRAPPER), "prompt"],
                check=True,
                env=environment,
                text=True,
                stdout=subprocess.PIPE,
            ).stdout.splitlines()
            rules = codex_home / "rules/default.rules"
            rendered_rules = rules.read_text()
            rules_mode = rules.stat().st_mode & 0o777
            legacy_rules = legacy_source.read_text()
            replaced_legacy_link = not os.path.samefile(legacy_source, rules)
            migrated_profile = profile.read_text(encoding="utf-8")
            migrated_config = config.read_text(encoding="utf-8")

        self.assertEqual(["--profile", "dotfiles", "-c"], output[:3])
        key, encoded = output[3].split("=", 1)
        self.assertEqual("developer_instructions", key)
        self.assertEqual(
            "first instructions\nnested instructions\nsecond instructions\n",
            json.loads(encoded),
        )
        self.assertEqual("prompt", output[4])
        self.assertIn(str(ROOT / "libexec/agent-wrappers"), output[5])
        self.assertNotIn("sandbox-wrappers", output[5])
        self.assertIn('deny(["sed"]', rendered_rules)
        self.assertIn('allow(["jj", ["status", "diff"', rendered_rules)
        self.assertEqual(0o600, rules_mode)
        self.assertEqual("legacy rules\n", legacy_rules)
        self.assertTrue(replaced_legacy_link)
        self.assertEqual('model = "gpt-test"\n', migrated_profile)
        self.assertIn('[projects."/generated"]', migrated_config)
        self.assertIn('[tui.model_availability_nux]', migrated_config)
        self.assertIn('"gpt-test" = 1', migrated_config)
        self.assertIn('[history]', migrated_config)

    def test_instruction_include_cycle_does_not_launch_codex(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fake_bin = root / "bin"
            fake_bin.mkdir()
            marker = root / "codex-ran"
            codex = fake_bin / "codex"
            codex.write_text(f"#!/bin/sh\ntouch {marker}\n")
            codex.chmod(0o755)
            codex_home = root / ".codex"
            codex_home.mkdir()
            (codex_home / "developer-instructions.md").write_text("@first.md\n")
            (codex_home / "first.md").write_text("@second.md\n")
            (codex_home / "second.md").write_text("@first.md\n")
            environment = os.environ | {
                "DOTFILES_SANDBOX": "1",
                "HOME": str(root),
                "PATH": f"{fake_bin}:{os.environ['PATH']}",
            }
            environment.pop("CODEX_HOME", None)

            result = subprocess.run(
                [str(WRAPPER)], env=environment, text=True, capture_output=True,
            )

            self.assertNotEqual(0, result.returncode)
            self.assertIn("instruction include cycle", result.stderr)
            self.assertFalse(marker.exists())

    def test_failed_generation_preserves_rules_and_does_not_launch(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fake_bin = root / "bin"
            fake_bin.mkdir()
            marker = root / "codex-ran"
            codex = fake_bin / "codex"
            codex.write_text(f"#!/bin/sh\ntouch {marker}\n")
            codex.chmod(0o755)
            bb = fake_bin / "bb"
            bb.write_text("#!/bin/sh\nprintf partial\nexit 7\n")
            bb.chmod(0o755)
            codex_home = root / ".codex"
            rules_directory = codex_home / "rules"
            rules_directory.mkdir(parents=True)
            published = rules_directory / "default.rules"
            published.write_text("previous rules\n")
            environment = os.environ | {
                "HOME": str(root),
                "PATH": f"{fake_bin}:{os.environ['PATH']}",
            }
            environment.pop("CODEX_HOME", None)

            result = subprocess.run(
                [str(WRAPPER)],
                env=environment,
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertNotEqual(0, result.returncode)
            self.assertIn("cannot generate rules", result.stderr)
            self.assertEqual("previous rules\n", published.read_text())
            self.assertFalse(marker.exists())
            self.assertEqual([published], list(rules_directory.iterdir()))

    def test_sandbox_skips_permission_generation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fake_bin = root / "bin"
            fake_bin.mkdir()
            codex = fake_bin / "codex"
            codex.write_text('#!/bin/sh\nprintf "%s\\n" "$@"\n')
            codex.chmod(0o755)
            codex_home = root / ".codex"
            codex_home.mkdir()
            manifest = codex_home / "developer-instructions.md"
            manifest.write_text("", encoding="utf-8")
            environment = os.environ | {
                "DOTFILES_SANDBOX": "1",
                "HOME": str(root),
                "PATH": f"{fake_bin}:{os.environ['PATH']}",
            }
            environment.pop("CODEX_HOME", None)

            result = subprocess.run(
                [str(WRAPPER), "prompt"],
                env=environment,
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(0, result.returncode, result.stderr)
            self.assertIn("prompt", result.stdout.splitlines())
            self.assertFalse((codex_home / "rules").exists())

    def test_codex_uses_noninteractive_man_pager_without_changing_caller(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fake_bin = root / "bin"
            fake_bin.mkdir()
            codex = fake_bin / "codex"
            codex.write_text('#!/bin/sh\nprintf "%s\\n" "$MANPAGER"\n')
            codex.chmod(0o755)
            codex_home = root / ".codex"
            codex_home.mkdir()
            (codex_home / "developer-instructions.md").write_text("")
            environment = os.environ | {
                "DOTFILES_SANDBOX": "1",
                "HOME": str(root),
                "MANPAGER": "nvim +Man!",
                "PATH": f"{fake_bin}:{os.environ['PATH']}",
            }
            environment.pop("CODEX_HOME", None)

            result = subprocess.run(
                [str(WRAPPER)], env=environment, text=True, capture_output=True,
            )

            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual("col -b\n", result.stdout)
            self.assertEqual("nvim +Man!", environment["MANPAGER"])


if __name__ == "__main__":
    unittest.main()
