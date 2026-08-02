from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from urllib.error import URLError


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools/man-page"))

from man_page import main


class ManPageTest(unittest.TestCase):
    def test_supported_sections_and_request_shape(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "manpath.config"
            config.write_text("MANPATH /usr/share/man\nSECTION 1 2 3p n\n")
            sections = main.supported_sections(config)

        self.assertEqual({"1", "2", "3p", "n"}, sections)
        self.assertEqual((None, "printf"), main.parse_request(["printf"], sections))
        self.assertEqual(("3p", "printf"), main.parse_request(["3p", "printf"], sections))
        self.assertIsNone(main.parse_request(["printf", "sh"], sections))

    @mock.patch.object(main, "launch", return_value=0)
    @mock.patch.object(main, "probe", return_value=True)
    @mock.patch.object(main, "supported_sections", return_value={"3"})
    def test_openbsd_url_quotes_opaque_page_and_section(self, _sections, probe, launch) -> None:
        self.assertEqual(0, main.resolve(["3", "name/with spaces?#"]))
        url = "https://man.openbsd.org/name%2Fwith%20spaces%3F%23.3"
        probe.assert_called_once_with(url)
        launch.assert_called_once_with(url)

    @mock.patch.object(main, "launch", return_value=0)
    @mock.patch.object(main, "probe", side_effect=[False, True])
    @mock.patch.object(main, "distribution_codename", return_value="noble next")
    @mock.patch.object(main, "infer_section", return_value="3p")
    @mock.patch.object(main, "supported_sections", return_value=set())
    def test_ubuntu_fallback_uses_unique_index_section(
        self, _sections, infer, codename, probe, launch
    ) -> None:
        self.assertEqual(0, main.resolve(["printf+"]))
        infer.assert_called_once_with("printf+")
        codename.assert_called_once_with()
        self.assertEqual(
            "https://manpages.ubuntu.com/manpages/noble%20next/man3p/printf%2B.3p.html",
            probe.call_args_list[1].args[0],
        )
        launch.assert_called_once_with(probe.call_args_list[1].args[0])

    @mock.patch.object(main, "distribution_codename", return_value="noble")
    @mock.patch.object(main, "infer_section", return_value=None)
    @mock.patch.object(main, "probe", return_value=False)
    @mock.patch.object(main, "supported_sections", return_value=set())
    def test_ambiguous_index_requests_native_fallback(self, _sections, _probe, _infer, _codename) -> None:
        self.assertEqual(main.FALLBACK, main.resolve(["printf"]))

    def test_infer_section_requires_one_unique_exact_match(self) -> None:
        completed = subprocess.CompletedProcess(
            [], 0, "printf, printf-tool (1) - format\nprintf (3) - library\n", ""
        )
        with mock.patch.object(main.subprocess, "run", return_value=completed):
            self.assertIsNone(main.infer_section("printf"))
        completed.stdout = "other (1) - no\nprintf-tool (7) - no\nprintf (3p) - yes\n"
        with mock.patch.object(main.subprocess, "run", return_value=completed) as run:
            self.assertEqual("3p", main.infer_section("printf"))
        run.assert_called_once_with(
            ["man", "-k", "--", "printf"],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            errors="replace",
        )

    @mock.patch.object(main, "distribution_codename", return_value=None)
    @mock.patch.object(main, "infer_section", return_value="1")
    @mock.patch.object(main, "probe", return_value=False)
    @mock.patch.object(main, "supported_sections", return_value=set())
    def test_missing_distribution_tools_request_native_fallback(
        self, _sections, _probe, _infer, _codename
    ) -> None:
        self.assertEqual(main.FALLBACK, main.resolve(["printf"]))

    def test_network_errors_are_provider_misses(self) -> None:
        for error in (URLError("offline"), TimeoutError(), OSError("unreachable")):
            with self.subTest(error=error):
                with mock.patch.object(main, "urlopen", side_effect=error):
                    self.assertFalse(main.probe("https://example.invalid"))

    @mock.patch.object(main.shutil, "which", return_value="/usr/bin/xdg-open")
    def test_launcher_failure_never_uses_fallback_status(self, _which) -> None:
        with mock.patch.object(
            main.subprocess, "run", return_value=subprocess.CompletedProcess([], main.FALLBACK)
        ):
            self.assertEqual(main.LAUNCH_FAILURE, main.launch("https://example.invalid"))

    @mock.patch.object(main, "supported_sections", return_value=set())
    def test_option_heavy_and_multiple_page_requests_fall_back(self, _sections) -> None:
        self.assertEqual(main.FALLBACK, main.resolve(["-a", "printf"]))
        self.assertEqual(main.FALLBACK, main.resolve(["printf", "sh"]))


if __name__ == "__main__":
    unittest.main()
