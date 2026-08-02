import importlib.util
import sys
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("patch_keymap.py")
SPEC = importlib.util.spec_from_file_location("patch_keymap", MODULE_PATH)
assert SPEC and SPEC.loader
patch_keymap = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = patch_keymap
SPEC.loader.exec_module(patch_keymap)


def unicode_sequence(codepoint, terminator="ENTER"):
    digits = " SS_DELAY(5) ".join(
        f"SS_TAP(X_{digit})" for digit in codepoint.upper()
    )
    return (
        "SS_LCTL(SS_LSFT(SS_TAP(X_U))) SS_DELAY(5) "
        f"{digits} SS_DELAY(5) SS_TAP(X_{terminator})"
    )


class PatchKeymapTests(unittest.TestCase):
    def test_converts_unicode_and_mode_sentinel(self):
        source = (
            "case EMOJI:\n"
            f"  SEND_STRING({unicode_sequence('1f449')});\n"
            "  break;\n"
            "const keycode = KC_F13;\n"
        )

        result = patch_keymap.patch_keymap(source)

        self.assertIn("register_unicode(0x1F449);", result)
        self.assertIn("const keycode = UC_NEXT;", result)
        self.assertNotIn("SS_LCTL", result)

    def test_converts_multiple_codepoints_in_one_send_string(self):
        source = (
            f"SEND_STRING({unicode_sequence('1f449')} "
            f"{unicode_sequence('1f448')}); KC_F13"
        )

        result = patch_keymap.patch_keymap(source)

        self.assertIn(
            "register_unicode(0x1F449); register_unicode(0x1F448);",
            result,
        )

    def test_accepts_space_terminator(self):
        source = f"SEND_STRING({unicode_sequence('3bb', 'SPACE')}); KC_F13"

        result = patch_keymap.patch_keymap(source)

        self.assertIn("register_unicode(0x3BB);", result)

    def test_leaves_ordinary_send_string_unchanged(self):
        ordinary = "SEND_STRING(SS_TAP(X_A));"
        source = ordinary + f" SEND_STRING({unicode_sequence('ae')}); KC_F13"

        result = patch_keymap.patch_keymap(source)

        self.assertIn(ordinary, result)

    def test_builds_fenced_code_block_macro(self):
        source = (
            "SEND_STRING(SS_TAP(X_GRAVE) SS_DELAY(100) SS_TAP(X_GRAVE) "
            "SS_DELAY(100) SS_TAP(X_GRAVE)); "
            f"SEND_STRING({unicode_sequence('ae')}); KC_F13"
        )

        result = patch_keymap.patch_keymap(source)

        self.assertIn(patch_keymap.BACKTICKS, result)
        self.assertIn("SS_TAP(X_UP)", result)
        self.assertNotIn("SS_DELAY(100)", result)

    def test_replaces_pointing_fingers_placeholder(self):
        source = (
            "SEND_STRING(SS_TAP(X_P) SS_DELAY(100) SS_TAP(X_L) "
            "SS_DELAY(100) SS_TAP(X_P) SS_DELAY(100) SS_TAP(X_R)); "
            f"SEND_STRING({unicode_sequence('ae')}); KC_F13"
        )

        result = patch_keymap.patch_keymap(source)

        self.assertIn(
            "register_unicode(0x1F449); register_unicode(0x1F448);",
            result,
        )
        self.assertNotIn("SS_TAP(X_P)", result)

    def test_rejects_missing_mode_sentinel(self):
        source = f"SEND_STRING({unicode_sequence('ae')});"

        with self.assertRaisesRegex(patch_keymap.PatchError, "found 0"):
            patch_keymap.patch_keymap(source)

    def test_rejects_duplicate_mode_sentinel(self):
        source = f"SEND_STRING({unicode_sequence('ae')}); KC_F13 KC_F13"

        with self.assertRaisesRegex(patch_keymap.PatchError, "found 2"):
            patch_keymap.patch_keymap(source)

    def test_rejects_malformed_unicode_macro(self):
        source = "SEND_STRING(SS_LCTL(SS_LSFT(SS_TAP(X_U))) SS_TAP(X_A)); KC_F13"

        with self.assertRaisesRegex(patch_keymap.PatchError, "no Enter or Space"):
            patch_keymap.patch_keymap(source)


if __name__ == "__main__":
    unittest.main()
