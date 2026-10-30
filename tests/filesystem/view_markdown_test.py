from html.parser import HTMLParser
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from urllib.parse import unquote, urljoin, urlsplit


ROOT = Path(__file__).resolve().parents[2]


class Page(HTMLParser):
    def __init__(self, html: str) -> None:
        super().__init__()
        self.elements: list[tuple[str, dict]] = []
        self.text: list[str] = []
        self.feed(html)

    def handle_starttag(self, tag: str, attrs: list) -> None:
        self.elements.append((tag, dict(attrs)))

    def handle_data(self, data: str) -> None:
        self.text.append(data)

    def attributes(self, tag: str) -> list[dict]:
        return [attrs for name, attrs in self.elements if name == tag]


class ViewMarkdownTest(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.bin = self.directory / "bin"
        self.bin.mkdir()
        self.document = self.directory / "notes & examples #1.md"
        self.document.write_text("# Heading\n")
        self.capture = self.directory / "captured.html"
        self.opened = self.directory / "opened"
        self.environment = os.environ | {
            "PATH": f"{self.bin}:{os.environ['PATH']}",
            "CAPTURE": str(self.capture),
            "OPENED": str(self.opened),
            "TMPDIR": str(self.directory),
        }
        self.executable("open", 'cp "$1" "$CAPTURE" || exit\nprintf "%s" "$1" > "$OPENED"\n')

    def executable(self, name: str, source: str) -> None:
        executable = self.bin / name
        executable.write_text("#!/bin/sh\n" + source)
        executable.chmod(0o755)

    def run_viewer(self, command: Path | None = None) -> subprocess.CompletedProcess:
        return subprocess.run(
            [str(command or ROOT / "bin/view_markdown"), self.document.name],
            cwd=self.directory, env=self.environment, capture_output=True, text=True,
        )

    def test_styled_page_preserves_relative_links_and_filename_characters(self) -> None:
        self.executable("marked", "printf '<p><a href=\"images/example.png\">example</a></p>\\n'\n")
        linked_command = self.bin / "view_markdown"
        linked_command.symlink_to(ROOT / "bin/view_markdown")

        result = self.run_viewer(linked_command)

        self.assertEqual(0, result.returncode, result.stderr)
        html = self.capture.read_text()
        page = Page(html)
        self.assertTrue(html.lower().startswith("<!doctype html>"))
        self.assertIn(self.document.name, "".join(page.text))
        base = page.attributes("base")[0]["href"]
        self.assertEqual(self.directory.as_uri() + "/", base)
        image = urljoin(base, page.attributes("a")[0]["href"])
        self.assertEqual((self.directory / "images/example.png").as_uri(), image)
        stylesheet = page.attributes("link")[0]
        self.assertEqual("stylesheet", stylesheet["rel"])
        style_path = Path(unquote(urlsplit(stylesheet["href"]).path))
        self.assertTrue(style_path.is_file())
        self.assertTrue(style_path.read_text().strip())
        self.assertEqual(self.document.with_suffix(".preview.html"), (self.directory / self.opened.read_text()))
        self.assertTrue((self.directory / self.opened.read_text()).is_file())

    def test_failed_generation_does_not_open_partial_html(self) -> None:
        # Either producer can fail; neither failure may reach the browser.
        for producer, status in (("marked", 23), ("node", 24)):
            with self.subTest(producer=producer):
                self.executable("marked", "printf '<p>complete</p>\\n'\n")
                self.executable(producer, f"printf partial\nexit {status}\n")
                result = self.run_viewer()
                self.assertEqual(status, result.returncode, result.stderr)
                self.assertFalse(self.opened.exists())
                self.assertFalse(self.capture.exists())
                self.assertEqual([], list(self.directory.glob("*.tmp.*")))

    @unittest.skipUnless(shutil.which("marked"), "native marked is required")
    def test_native_marked_renders_gfm_tables_and_fenced_code(self) -> None:
        self.document.write_text(
            "# Heading\n\n"
            "| Name | Value |\n| --- | --- |\n| one | two |\n\n"
            "```js\nconst value = '<tag>';\n```\n"
        )

        result = self.run_viewer()

        self.assertEqual(0, result.returncode, result.stderr)
        page = Page(self.capture.read_text())
        self.assertEqual(1, len(page.attributes("h1")))
        self.assertEqual(1, len(page.attributes("table")))
        self.assertEqual(2, len(page.attributes("td")))
        self.assertIn({"class": "language-js"}, page.attributes("code"))
        self.assertIn("const value = '<tag>';", "".join(page.text))
        self.assertFalse(page.attributes("tag"))

    @unittest.skipUnless(shutil.which("marked"), "native marked is required")
    def test_missing_source_does_not_open_a_page(self) -> None:
        self.document.unlink()
        result = self.run_viewer()
        self.assertNotEqual(0, result.returncode)
        self.assertFalse(self.opened.exists())
        self.assertEqual([], list(self.directory.glob("*.tmp.*")))


if __name__ == "__main__":
    unittest.main()
