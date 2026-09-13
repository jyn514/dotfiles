#!/usr/bin/env python3

import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
HOURS = ROOT / "bin/hours"


class HoursTests(unittest.TestCase):
    def run_hours(self, input_text: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(HOURS)],
            input=input_text,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

    def assert_hours(self, interval: str, expected: str) -> None:
        result = self.run_hours(interval + "\n")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(expected + "\n", result.stdout)

    def test_meridiem_is_part_of_duration_arithmetic(self) -> None:
        cases = {
            "9AM-9PM": "12.00",
            "12AM-12PM": "12.00",
            "12AM-1AM": "1.00",
            "12PM-1PM": "1.00",
            "9AM-5AM": "20.00",
            "1PM-3AM": "14.00",
            "9PM-9AM": "12.00",
        }
        for interval, expected in cases.items():
            with self.subTest(interval=interval):
                self.assert_hours(interval, expected)

    def test_24_hour_clocks_and_documented_endpoint_policy(self) -> None:
        cases = {
            "00:00-12:00": "12.00",
            "12:00-00:00": "12.00",
            "23:00-01:00": "2.00",
            "09:00-09:00": "0.00",
            "9AM-9AM": "0.00",
        }
        for interval, expected in cases.items():
            with self.subTest(interval=interval):
                self.assert_hours(interval, expected)

    def test_cells_allow_boundary_whitespace_and_round_exact_minutes(self) -> None:
        self.assert_hours(" 9:00AM - 9:01AM , 10AM-10:02AM ", "0.05")
        self.assert_hours("9AM-9:59AM", "0.98")

    def test_invalid_clock_grammar_and_ranges_are_rejected(self) -> None:
        invalid = (
            "0AM-1AM",
            "13PM-1PM",
            "24:00-01:00",
            "09:60-10:00",
            "9-10",
            "9AM-17:00",
            "9am-10am",
            "9AMAM-10AM",
            "9 AM-10 AM",
            "+09:00-10:00",
            "9.5AM-10AM",
            "09:00-10:00 trailing",
            "09:00--10:00",
            "09:00-10:00-extra",
            "09:00-10:00,",
        )
        for cell in invalid:
            with self.subTest(cell=cell):
                result = self.run_hours(cell + "\n")
                self.assertEqual(2, result.returncode)
                self.assertEqual("", result.stdout)
                self.assertIn("line 1", result.stderr)

    def test_a_late_error_emits_no_partial_results(self) -> None:
        result = self.run_hours("9AM-5PM\n09:00-17:00,broken\n")

        self.assertEqual(2, result.returncode)
        self.assertEqual("", result.stdout)
        self.assertIn("line 2, interval 2", result.stderr)


if __name__ == "__main__":
    unittest.main()
