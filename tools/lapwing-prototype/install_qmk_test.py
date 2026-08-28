#!/usr/bin/env python3

import tempfile
import unittest
from pathlib import Path

import generate_model
import install_qmk


class InstallQmkTest(unittest.TestCase):
    def test_install_is_repeatable_and_preserves_existing_hooks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            keymap = Path(directory) / "KW9E9"
            keymap.mkdir()
            (keymap / "rules.mk").write_text("STENO_ENABLE = yes\n")
            (keymap / "keymap.c").write_text(
                "#include QMK_KEYBOARD_H\n"
                "void keyboard_post_init_user(void) {\n    existing();\n}\n"
                "void matrix_scan_user(void) {\n    scan_existing();\n}\n"
            )
            model = Path(directory) / "model.bin"
            model.write_bytes(generate_model.pack_model(["cat"], []))
            install_qmk.install(keymap, model)
            first = (keymap / "keymap.c").read_text()
            install_qmk.install(keymap, model)
            self.assertEqual((keymap / "keymap.c").read_text(), first)
            self.assertIn("lapwing_qmk_init();\n    existing();", first)
            self.assertEqual(first.count("lapwing_qmk_task();"), 1)
            self.assertIn("lapwing_qmk_task();\n    scan_existing();", first)
            rules = (keymap / "rules.mk").read_text()
            self.assertEqual(rules.count("lapwing_decoder.c"), 1)
            self.assertIn("lapwing_modifiers.c", rules)
            self.assertIn("lapwing_movement.c", rules)
            self.assertTrue((keymap / "lapwing_features.h").is_file())
            self.assertTrue((keymap / "lapwing_modifiers.c").is_file())
            self.assertTrue((keymap / "lapwing_movement.c").is_file())
            self.assertEqual((keymap / "lapwing_model.bin").read_bytes(), model.read_bytes())


if __name__ == "__main__":
    unittest.main()
