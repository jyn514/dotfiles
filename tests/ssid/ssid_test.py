import importlib.machinery
import importlib.util
import io
import itertools
from pathlib import Path
import random
import sys
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "bin/ssid"
LOADER = importlib.machinery.SourceFileLoader("ssid_command", str(MODULE_PATH))
SPEC = importlib.util.spec_from_loader(LOADER.name, LOADER)
assert SPEC
ssid = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = ssid
LOADER.exec_module(ssid)


def nmcli_rows(rows: list[tuple[bool, bytes]]) -> bytes:
    """Model native tabular IN-USE,SSID output with --escape yes."""
    return b"".join(
        (b"*" if active else b" ") + b":"
        + payload.replace(b"\\", b"\\\\").replace(b":", b"\\:") + b"\n"
        for active, payload in rows
    )


class SsidTests(unittest.TestCase):
    def test_selects_first_active_record_without_text_decoding(self):
        records = b" :Other\n*:Justice\\:of\\\\Toren-\xff\n*:Later\n"

        self.assertEqual(ssid.active_ssid(records), b"Justice:of\\Toren-\xff")

    def test_invokes_nmcli_with_machine_readable_protocol(self):
        runner = mock.Mock(return_value=ssid.Result(0, b"*:Network Name\n"))
        output = io.BytesIO()

        self.assertEqual(ssid.show_ssid(runner, output), 0)
        runner.assert_called_once_with(
            [
                "nmcli",
                "--terse",
                "--escape",
                "yes",
                "--fields",
                "in-use,ssid",
                "device",
                "wifi",
            ]
        )
        self.assertEqual(output.getvalue(), b"Network Name\n")

    def test_empty_active_ssid_is_printed_as_an_empty_line(self):
        output = io.BytesIO()

        self.assertEqual(
            ssid.show_ssid(lambda _arguments: ssid.Result(0, b"*:\n"), output),
            0,
        )
        self.assertEqual(output.getvalue(), b"\n")

    def test_no_active_network_produces_no_output(self):
        output = io.BytesIO()

        self.assertEqual(
            ssid.show_ssid(lambda _arguments: ssid.Result(0, b" :Network\n"), output),
            0,
        )
        self.assertEqual(output.getvalue(), b"")

    def test_nmcli_failure_discards_partial_output_and_preserves_status(self):
        output = io.BytesIO()

        self.assertEqual(
            ssid.show_ssid(lambda _arguments: ssid.Result(29, b"*:Partial\n"), output),
            29,
        )
        self.assertEqual(output.getvalue(), b"")

    def test_active_payload_preserves_all_newline_positions(self):
        for payload in (
            b"\n", b"\n\n", b"\nLeading", b"Trailing\n", b"Trailing\n\n",
            b"Multiple\n\nLines", b"\n*:\n :\n", b"Colon:slash\\\n\xff",
        ):
            with self.subTest(payload=payload):
                self.assertEqual(ssid.active_ssid(nmcli_rows([(True, payload)])), payload)

    def test_payload_cannot_forge_active_or_inactive_records(self):
        inactive = b"Other\n*:Forged\n :Also forged\n"
        active = b"Actual\n :Not a new row\n*:Still this SSID\n"
        records = nmcli_rows([(False, inactive), (True, active), (True, b"Later")])

        self.assertEqual(ssid.active_ssid(records), active)
        self.assertIsNone(ssid.active_ssid(nmcli_rows([(False, inactive)])))

    def test_absent_rows_produce_no_active_ssid(self):
        self.assertIsNone(ssid.active_ssid(b""))

    def test_malformed_output_is_rejected_even_after_an_active_record(self):
        for records in (
            b"*:Missing terminator", b"junk\n*:Forged\n", b"? :Unknown marker\n",
            b"*:Unescaped:colon\n", b"*:Unknown\\escape\n", b"*:Dangling\\\n",
            b"*:\x00\n", b"*:Valid\n :Unescaped:colon\n",
            b"*:Valid\n :Unknown\\escape\n", b"*:Valid\n :Unterminated",
        ):
            with self.subTest(records=records):
                self.assertIsNone(ssid.active_ssid(records))

    def test_escaped_display_rows_round_trip(self):
        # Native --escape yes quotes only colon/backslash; newline is payload.
        # This model encoder is checked against the extracted native formatter
        # in target/ssid-native-locale. No decoder logic is shared with ssid.
        alphabet = (b"A", b"*", b" ", b":", b"\\", b"\n", b"\xff")
        payloads = (b"".join(parts) for size in range(4)
                    for parts in itertools.product(alphabet, repeat=size))
        for payload in payloads:
            for rows in (
                [(False, payload)],
                [(True, payload), (True, b"Later")],
                [(False, b"Other\n*:Forged"), (True, payload), (False, payload)],
            ):
                with self.subTest(rows=rows):
                    expected = next((value for active, value in rows if active), None)
                    self.assertEqual(ssid.active_ssid(nmcli_rows(rows)), expected)

        # Native fields are C strings, so NUL cannot occur in display output.
        # Keep all other byte values opaque, including non-UTF-8 test payloads.
        seed = 0x53534944
        generator = random.Random(seed)
        for case in range(500):
            rows = [
                (bool(generator.getrandbits(1)), bytes(
                    generator.randrange(1, 256) for _ in range(generator.randrange(97))
                ))
                for _ in range(generator.randrange(7))
            ]
            with self.subTest(seed=seed, case=case, rows=rows):
                expected = next((value for active, value in rows if active), None)
                self.assertEqual(ssid.active_ssid(nmcli_rows(rows)), expected)

    def test_unknown_escapes_never_select_an_active_record(self):
        for byte in range(256):
            if byte in b":\\":
                continue
            records = b"*:Valid\n :Bad\\" + bytes([byte]) + b"\n"
            with self.subTest(byte=byte):
                self.assertIsNone(ssid.active_ssid(records))

    def test_missing_nmcli_returns_shell_compatible_status(self):
        with mock.patch.object(
            ssid.subprocess,
            "run",
            side_effect=FileNotFoundError("missing"),
        ), mock.patch("sys.stderr", new_callable=io.StringIO) as stderr:
            result = ssid.run(["nmcli"])

        self.assertEqual(result.status, 127)
        self.assertIn("could not execute 'nmcli'", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
