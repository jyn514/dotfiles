#!/usr/bin/env python3

import importlib.machinery
import importlib.util
from pathlib import Path
import subprocess
import tempfile
import tomllib
import unittest
from unittest import mock


SCRIPT = Path(__file__).resolve().parents[1] / "move-generated-config"
loader = importlib.machinery.SourceFileLoader("move_generated_config", str(SCRIPT))
spec = importlib.util.spec_from_loader(loader.name, loader)
module = importlib.util.module_from_spec(spec)
loader.exec_module(module)


# These are TOML value spellings, not decoded strings. tomllib is the oracle
# for both input validity and preservation of the values after the CLI runs.
LOOKALIKES = (
    '[projects."/example"]\ntrust_level = "trusted"\n'
    '[tui.model_availability_nux]\n"test" = 1\n'
    '[hooks.state]\n[hooks.state."example"]\ntrusted_hash = "test"\n'
    '[ordinary]\n[[ordinary_array]]\n'
)
STRING_VALUES = (
    ("literal", "'''\n" + LOOKALIKES + "'''"),
    ("basic", '"""\n' + LOOKALIKES + '"""'),
    ("escaped-basic-terminator", '"""\n\\"""\n' + LOOKALIKES + '"""'),
    ("basic-line-continuation", '"""\\\n  ' + LOOKALIKES + '"""'),
    ("literal-other-quotes", "'''\n\"\"\"\n" + LOOKALIKES + "'''''"),
    ("basic-other-quotes", '"""\n\'\'\'\n' + LOOKALIKES + '"""""'),
    ("basic-escaped-backslash", '"""\n' + LOOKALIKES + '\\\\"""'),
    ("basic-four-quote-close", '"""\n' + LOOKALIKES + '""""'),
    ("literal-four-quote-close", "'''\n" + LOOKALIKES + "''''"),
    ("literal-ordinary-only", "'''\n[ordinary]\n[[ordinary_array]]\n'''"),
    ("basic-ordinary-only", '"""\n[ordinary]\n[[ordinary_array]]\n"""'),
)


class MoveGeneratedConfigTests(unittest.TestCase):
    def run_cli(self, profile: Path, config: Path) -> None:
        result = subprocess.run(
            [str(SCRIPT), str(profile), str(config)],
            text=True, capture_output=True,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("", result.stdout)
        self.assertEqual("", result.stderr)

    def test_cli_unicode_separators_do_not_end_comments(self) -> None:
        for separator in ("\u2028", "\u0085"):
            for newline in ("\n", "\r\n"):
                for has_generated_table in (False, True):
                    with self.subTest(separator=repr(separator), newline=repr(newline),
                                      generated=has_generated_table), \
                            tempfile.TemporaryDirectory() as temporary:
                        root = Path(temporary)
                        profile, config = root / "profile.toml", root / "config.toml"
                        comment = '# comment' + separator + '[projects."/example"]' + newline
                        generated = (
                            '[projects."/real"]' + newline + 'trust_level = "trusted"' + newline
                        )
                        text = comment + (generated if has_generated_table else "")
                        expected = tomllib.loads(generated) if has_generated_table else {}
                        self.assertEqual(expected, tomllib.loads(text))
                        profile.write_bytes(text.encode())

                        self.run_cli(profile, config)

                        if has_generated_table:
                            # Migration already reads with universal-newline
                            # translation; do not change its existing CRLF policy.
                            self.assertEqual(comment.replace("\r\n", "\n"), profile.read_text())
                            self.assertEqual(expected, tomllib.loads(config.read_text()))
                        else:
                            self.assertEqual(text.encode(), profile.read_bytes())
                            self.assertFalse(config.exists())

    def test_cli_header_lookalikes_in_strings_are_an_unchanged_noop(self) -> None:
        for name, value in STRING_VALUES:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                profile, config = root / "profile.toml", root / "config.toml"
                text = 'developer_instructions = ' + value + '\n'
                self.assertIn("[ordinary]", tomllib.loads(text)["developer_instructions"])
                profile.write_text(text)
                before = profile.stat()

                self.run_cli(profile, config)

                self.assertEqual(text.encode(), profile.read_bytes())
                self.assertEqual(before.st_ino, profile.stat().st_ino)
                self.assertEqual(before.st_mtime_ns, profile.stat().st_mtime_ns)
                self.assertFalse(config.exists())

    def test_cli_moves_only_real_tables_with_strings_in_both_files(self) -> None:
        for name, value in STRING_VALUES:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                profile, config = root / "profile.toml", root / "config.toml"
                kept = 'developer_instructions = ' + value + '\n\n'
                # Ordinary and array-table lookalikes inside this generated table
                # must not end its source range early.
                generated = (
                    '[projects."/real"]\ntrust_level = "trusted"\n'
                    'note = ' + value + '\n\n'
                    '[hooks.state]\n\n[hooks.state."real"]\n'
                    'trusted_hash = "new"\n\n'
                    '[tui.model_availability_nux]\n"test" = 2\n'
                )
                remaining = '[notice]\nhide = true\n'
                destination = (
                    'developer_instructions = ' + value + '\n\n'
                    '[tui.model_availability_nux]\n"test" = 1\n'
                    'note = ' + value + '\n\n'
                    '[history]\npersistence = "save-all"\n'
                )
                profile.write_text(kept + generated + remaining)
                config.write_text(destination)
                expected = tomllib.loads(kept + generated + remaining)
                old_destination = tomllib.loads(destination)

                self.run_cli(profile, config)

                self.assertEqual(kept + remaining, profile.read_text())
                migrated = tomllib.loads(config.read_text())
                self.assertEqual(expected["projects"], migrated["projects"])
                self.assertEqual(expected["hooks"], migrated["hooks"])
                self.assertEqual(expected["tui"], migrated["tui"])
                self.assertEqual(old_destination["history"], migrated["history"])
                self.assertEqual(expected["developer_instructions"], migrated["developer_instructions"])
                self.assertIn(kept, config.read_text())
                self.assertIn('[projects."/real"]\ntrust_level = "trusted"\nnote = ' + value,
                              config.read_text())
                before = config.read_bytes()
                self.run_cli(profile, config)
                self.assertEqual(before, config.read_bytes())

    def test_publish_failure_preserves_state_and_retry_recovers(self) -> None:
        for failed_file in ("profile.toml", "config.toml"):
            with self.subTest(failed_file=failed_file), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                profile, config = root / "profile.toml", root / "config.toml"
                kept = 'developer_instructions = ' + STRING_VALUES[2][1] + '\n\n'
                generated = '[projects."/real"]\ntrust_level = "trusted"\n'
                profile.write_text(kept + generated)
                original_replace = module.os.replace

                def fail_selected(source, target):
                    if Path(target).name == failed_file:
                        raise OSError("injected publication failure")
                    return original_replace(source, target)

                with mock.patch.object(module.os, "replace", side_effect=fail_selected):
                    with self.assertRaisesRegex(OSError, "injected publication failure"):
                        module.migrate(profile, config)

                self.assertEqual(kept + generated, profile.read_text())
                if failed_file == "profile.toml":
                    self.assertEqual(generated, config.read_text())
                else:
                    self.assertFalse(config.exists())
                self.assertFalse(list(root.glob(".*.toml.*")))
                self.run_cli(profile, config)
                self.assertEqual(kept.rstrip("\n") + "\n", profile.read_text())
                self.assertEqual(generated, config.read_text())

    def test_moves_generated_tables_and_preserves_tracked_model(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            tracked = root / "tracked.toml"
            profile = root / "dotfiles.config.toml"
            profile.symlink_to(tracked)
            config = root / "config.toml"
            tracked.write_text(
                'model = "gpt-test"\n\n'
                '[tui.model_availability_nux]\n'
                '"gpt-5.5" = 4\n\n'
                '[projects."/new project"]\n'
                'trust_level = "trusted"\n\n'
                '[notice]\n'
                'hide = true\n',
                encoding="utf-8",
            )
            config.write_text(
                '[projects."/existing"]\n'
                'trust_level = "trusted"\n\n'
                '[history]\n'
                'persistence = "save-all"\n',
                encoding="utf-8",
            )

            changed = module.migrate(profile, config)

            self.assertTrue(changed)
            self.assertTrue(profile.is_symlink())
            self.assertEqual(
                'model = "gpt-test"\n\n[notice]\nhide = true\n',
                tracked.read_text(encoding="utf-8"),
            )
            migrated = config.read_text(encoding="utf-8")
            self.assertIn('[projects."/existing"]', migrated)
            self.assertIn('[projects."/new project"]', migrated)
            self.assertIn('[tui.model_availability_nux]', migrated)
            self.assertIn('"gpt-5.5" = 4', migrated)
            self.assertIn('[history]', migrated)

    def test_matching_destination_entry_is_removed_from_profile(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            profile = root / "dotfiles.config.toml"
            config = root / "config.toml"
            project = '[projects."/work"]\ntrust_level = "trusted"\n'
            profile.write_text(f'model = "gpt-test"\n\n{project}', encoding="utf-8")
            config.write_text(project, encoding="utf-8")

            module.migrate(profile, config)

            self.assertEqual('model = "gpt-test"\n', profile.read_text(encoding="utf-8"))
            self.assertEqual(project, config.read_text(encoding="utf-8"))

    def test_new_model_availability_replaces_stale_destination(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            profile = root / "dotfiles.config.toml"
            config = root / "config.toml"
            profile_text = '[tui.model_availability_nux]\n"gpt-5.5" = 4\n'
            config_text = '[tui.model_availability_nux]\n"gpt-5.5" = 3\n'
            profile.write_text(profile_text, encoding="utf-8")
            config.write_text(config_text, encoding="utf-8")

            module.migrate(profile, config)

            self.assertEqual("", profile.read_text(encoding="utf-8"))
            self.assertEqual(profile_text, config.read_text(encoding="utf-8"))

    def test_project_conflict_preserves_both_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            profile = root / "dotfiles.config.toml"
            config = root / "config.toml"
            profile_text = '[projects."/work"]\ntrust_level = "trusted"\n'
            config_text = '[projects."/work"]\ntrust_level = "untrusted"\n'
            profile.write_text(profile_text, encoding="utf-8")
            config.write_text(config_text, encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "conflicting"):
                module.migrate(profile, config)

            self.assertEqual(profile_text, profile.read_text(encoding="utf-8"))
            self.assertEqual(config_text, config.read_text(encoding="utf-8"))

    def test_moves_hook_state_without_moving_hook_configuration(self) -> None:
        # Codex emits an empty parent table; TOML also permits implicit parents.
        for parent in ("", "[hooks.state]\n\n"):
            for destination in ("", "unrelated", "matching"):
                with self.subTest(parent=bool(parent), destination=destination):
                    with tempfile.TemporaryDirectory() as temporary:
                        root = Path(temporary)
                        profile = root / "profile.toml"
                        config = root / "config.toml"
                        hook = (
                            '[hooks.state."/work/project/.codex/hooks.json:post_tool_use:0:0"]\n'
                            'trusted_hash = "sha256:new"\n'
                        )
                        other = (
                            "[hooks.state.'another.hook']\n"
                            'trusted_hash = "sha256:other"\n'
                        )
                        settings = '[hooks]\nenabled = true\n\n[hooks.settings]\nkeep = true\n'
                        profile.write_text(settings + "\n" + parent + hook)
                        config.write_text(
                            "" if destination == "" else other if destination == "unrelated" else hook
                        )

                        self.assertTrue(module.migrate(profile, config))

                        self.assertEqual(settings, profile.read_text())
                        migrated = tomllib.loads(config.read_text())
                        expected = tomllib.loads(hook)["hooks"]["state"]
                        if destination == "unrelated":
                            expected.update(tomllib.loads(other)["hooks"]["state"])
                        self.assertEqual({"hooks": {"state": expected}}, migrated)
                        before = config.read_text()
                        self.assertFalse(module.migrate(profile, config))
                        self.assertEqual(before, config.read_text())

    def test_hook_state_conflict_preserves_both_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            profile = root / "profile.toml"
            config = root / "config.toml"
            hook = '[hooks.state."/work/hook.json:post_tool_use:0:0"]\n'
            profile_text = (
                '[projects."/new project"]\ntrust_level = "trusted"\n\n'
                '[hooks.state]\n\n' + hook + 'trusted_hash = "sha256:new"\n'
            )
            config_text = hook + 'trusted_hash = "sha256:old"\n'
            profile.write_text(profile_text)
            config.write_text(config_text)

            with self.assertRaisesRegex(ValueError, "conflicting"):
                module.migrate(profile, config)

            self.assertEqual(profile_text, profile.read_text())
            self.assertEqual(config_text, config.read_text())

    def test_missing_profile_is_a_noop(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.assertFalse(module.migrate(root / "missing", root / "config.toml"))
            self.assertFalse((root / "config.toml").exists())


if __name__ == "__main__":
    unittest.main()
