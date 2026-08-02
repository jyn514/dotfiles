import importlib.machinery
import importlib.util
import io
from pathlib import Path
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


class SsidTests(unittest.TestCase):
    def test_selects_first_active_record_without_decoding_payload(self):
        records = b"no:Other\nyes:Justice:of\\Toren-\xff\nyes:Later\n"

        self.assertEqual(ssid.active_ssid(records), b"Justice:of\\Toren-\xff")

    def test_invokes_nmcli_with_machine_readable_protocol(self):
        runner = mock.Mock(return_value=ssid.Result(0, b"yes:Network Name\n"))
        output = io.BytesIO()

        self.assertEqual(ssid.show_ssid(runner, output), 0)
        runner.assert_called_once_with(
            [
                "nmcli",
                "--terse",
                "--escape",
                "no",
                "--fields",
                "active,ssid",
                "device",
                "wifi",
            ]
        )
        self.assertEqual(output.getvalue(), b"Network Name\n")

    def test_empty_active_ssid_is_printed_as_an_empty_line(self):
        output = io.BytesIO()

        self.assertEqual(
            ssid.show_ssid(lambda _arguments: ssid.Result(0, b"yes:\n"), output),
            0,
        )
        self.assertEqual(output.getvalue(), b"\n")

    def test_no_active_network_produces_no_output(self):
        output = io.BytesIO()

        self.assertEqual(
            ssid.show_ssid(lambda _arguments: ssid.Result(0, b"no:Network\n"), output),
            0,
        )
        self.assertEqual(output.getvalue(), b"")

    def test_nmcli_failure_discards_partial_output_and_preserves_status(self):
        output = io.BytesIO()

        self.assertEqual(
            ssid.show_ssid(lambda _arguments: ssid.Result(29, b"yes:Partial\n"), output),
            29,
        )
        self.assertEqual(output.getvalue(), b"")

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
