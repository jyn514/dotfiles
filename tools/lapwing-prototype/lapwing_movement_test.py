#!/usr/bin/env python3

import ctypes
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).parent


class Result(ctypes.Structure):
    _fields_ = [
        ("key", ctypes.c_int),
        ("modifiers", ctypes.c_uint8),
        ("repeat", ctypes.c_uint8),
    ]


class MovementTest(unittest.TestCase):
    def test_all_modal_forms_and_repetition(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            library = Path(directory) / "movement.so"
            subprocess.run(
                ["cc", "-std=c11", "-Wall", "-Wextra", "-Werror", "-pedantic",
                 "-shared", "-fPIC", str(ROOT / "lapwing_movement.c"),
                 "-o", str(library)],
                check=True,
            )
            lookup = ctypes.CDLL(str(library)).lw_movement_lookup
            lookup.argtypes = [ctypes.c_char_p, ctypes.c_bool, ctypes.POINTER(Result)]
            lookup.restype = ctypes.c_bool

            suffixes = (
                "*FR", "*FBL", "*R", "*RPG", "*RB", "*P", "*B", "*BG",
                "*LG", "*G", "-FR", "-FPL", "-FBL", "-R", "-RPG", "-RB",
                "-RBG", "-RBT", "-RBTS", "-RBS", "-RT", "-RTS", "-RS",
                "-P", "-PT", "-PTS", "-PS", "-B", "-BG", "-BGT", "-BGTS",
                "-BGS", "-BT", "-BTS", "-BS", "-LG", "-G", "-GT", "-GTS",
                "-GS",
            )

            def result(stroke: str, continuation: bool):
                value = Result()
                if not lookup(stroke.encode(), continuation, ctypes.byref(value)):
                    return None
                return value.key, value.modifiers, value.repeat

            for suffix in suffixes:
                continuation = result(suffix, True)
                self.assertIsNotNone(continuation, suffix)
                self.assertEqual(result("STPH" + suffix, False), continuation)
                self.assertEqual(result("#TPH" + suffix, False), continuation)

            left = result("-RBT", True)
            self.assertEqual(left[1:], (0x02, 3))
            selected_word = result("*RB", True)
            self.assertEqual(selected_word[1:], (0x03, 1))
            self.assertEqual(result("-GTS", True)[2], 4)
            for invalid in ("", "KAT", "STPH", "#TPH-RD"):
                self.assertIsNone(result(invalid, False))


if __name__ == "__main__":
    unittest.main()
