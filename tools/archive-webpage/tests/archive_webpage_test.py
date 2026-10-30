import json
import os
from pathlib import Path
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[3]


class ArchiveWebpageTests(unittest.TestCase):
    def run_archive(
        self, *arguments: str, failed_format: str = "", wget_status: int = 0,
    ) -> tuple[int, dict[str, list], str]:
        result = subprocess.run(
            [
                "node", str(Path(__file__).parent / "fixtures/archive-harness.cjs"),
                str(ROOT / "bin/archive-webpage"),
            ],
            env=os.environ | {
                "ARCHIVE_ARGUMENTS": json.dumps(arguments),
                "FAILED_FORMAT": failed_format,
                "WGET_STATUS": str(wget_status),
            },
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        output = next(
            line.removeprefix("__RESULT__")
            for line in result.stdout.splitlines()
            if line.startswith("__RESULT__")
        )
        archived = json.loads(output)
        return archived["status"], archived["state"], result.stdout

    def test_archive_webpage_rejects_path_titles_and_serializes_metadata(self) -> None:
        for title in (".", "..", "nested/name", r"nested\\name"):
            status, state, _ = self.run_archive("output", "https://example.test", title)
            self.assertEqual(1, status, title)
            self.assertEqual([], state["trees"], title)
            self.assertEqual([], state["writes"], title)

        status, state, _ = self.run_archive("output", "https://example.test", "page")
        self.assertEqual(0, status)
        self.assertEqual("output/page_meta.yaml", state["writes"][0][0])
        self.assertEqual("w", state["writes"][0][2])
        metadata = json.loads(state["writes"][0][1])
        self.assertEqual('quoted " title\nnext', metadata["title"])
        self.assertEqual("https://example.test", metadata["url"])
        self.assertEqual([], metadata["tags"])

    def test_success_renders_both_formats_and_reports_completion(self) -> None:
        status, state, output = self.run_archive("output", "https://example.test", "page")
        self.assertEqual(0, status)
        self.assertEqual(["png", "pdf"], [options["format"] for _, options in state["renders"]])
        self.assertEqual(1, len(state["writes"]))
        self.assertEqual("wget", state["spawns"][0][0])
        self.assertIn("INFO: all operations complete.", output)

    def assert_render_failure(self, failed_format: str, rendered_formats: list[str]) -> None:
        status, state, output = self.run_archive(
            "output", "https://example.test", "page", failed_format=failed_format,
        )
        self.assertNotEqual(0, status)
        self.assertIn("FATAL: could not render output/page." + failed_format, output)
        self.assertNotIn("all operations complete", output)
        self.assertEqual(rendered_formats, [options["format"] for _, options in state["renders"]])
        self.assertEqual([], state["writes"])
        self.assertEqual([], state["spawns"])

    def test_png_failure_stops_before_pdf_metadata_and_wget(self) -> None:
        self.assert_render_failure("png", ["png"])

    def test_pdf_failure_stops_before_metadata_and_wget(self) -> None:
        self.assert_render_failure("pdf", ["png", "pdf"])

    def test_wget_failure_remains_failure_without_completion_message(self) -> None:
        status, state, output = self.run_archive(
            "output", "https://example.test", "page", wget_status=8,
        )
        self.assertEqual(8, status)
        self.assertEqual(2, len(state["renders"]))
        self.assertEqual(1, len(state["writes"]))
        self.assertNotIn("all operations complete", output)


if __name__ == "__main__":
    unittest.main()
