#!/usr/bin/env python3

import importlib.machinery
import importlib.util
from pathlib import Path
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "move-generated-config"
loader = importlib.machinery.SourceFileLoader("move_generated_config", str(SCRIPT))
spec = importlib.util.spec_from_loader(loader.name, loader)
module = importlib.util.module_from_spec(spec)
loader.exec_module(module)


class MoveGeneratedConfigTests(unittest.TestCase):
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

    def test_missing_profile_is_a_noop(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.assertFalse(module.migrate(root / "missing", root / "config.toml"))
            self.assertFalse((root / "config.toml").exists())


if __name__ == "__main__":
    unittest.main()
