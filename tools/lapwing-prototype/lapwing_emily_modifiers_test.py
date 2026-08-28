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


class EmilyModifiersTest(unittest.TestCase):
    def test_pinned_dictionary_forms(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            library = Path(directory) / "modifiers.so"
            subprocess.run(
                ["cc", "-std=c11", "-Wall", "-Wextra", "-Werror", "-pedantic",
                 "-shared", "-fPIC", str(ROOT / "lapwing_modifiers.c"),
                 "-o", str(library)],
                check=True,
            )
            lookup = ctypes.CDLL(str(library)).lw_emily_modifier_lookup
            lookup.argtypes = [ctypes.c_char_p, ctypes.POINTER(Result)]
            lookup.restype = ctypes.c_bool

            def result(stroke: str):
                value = Result()
                if not lookup(stroke.encode(), ctypes.byref(value)):
                    return None
                return value.key, value.modifiers

            # Enum order: NONE, A..Z, 0..9, F0...
            self.assertEqual(result("AFLGTS"), (1, 0x02))
            self.assertEqual(result("AFRPBLGTS"), (1, 0x0f))
            self.assertEqual(result("WRAOBLGTS"), (30, 0x04))
            self.assertEqual(result("TKPWRAOPLGTS"), (44, 0x08))
            self.assertEqual(result("FRPBLGTS"), (0, 0x0f))

            exclamation = result("TK*FLGTS")
            self.assertIsNotNone(exclamation)
            self.assertEqual(exclamation[1], 0x02)
            up = result("KPWR*FRLGTS")
            self.assertIsNotNone(up)
            self.assertEqual(up[1], 0x03)
            less = result("TPHA*FRLGTS")
            self.assertIsNotNone(less)
            self.assertEqual(less[1], 0x03)

            for invalid in ("A", "ALTZ", "ALGTS", "KWR*AOFRLGTS", "NOPELGTS"):
                self.assertIsNone(result(invalid))


if __name__ == "__main__":
    unittest.main()
