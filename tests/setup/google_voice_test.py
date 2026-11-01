import importlib.util
import json
import os
from pathlib import Path
import random
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from urllib.parse import quote, unquote, urlsplit


ROOT = Path(__file__).resolve().parents[2]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


voice = load("open_google_voice", "libexec/setup/open_google_voice.py")
setup = load("setup_mimetypes", "libexec/setup/setup_mimetypes.py")


class GoogleVoiceTest(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "Node is required")
    def test_glide_prefills_only_the_confirmed_number_and_an_empty_body(self):
        subprocess.run([
            "node", str(ROOT / "tests/setup/fixtures/glide-sms-prefill.mjs"),
            str(ROOT / "config/glide.ts"),
        ], check=True)

    def test_body_reaches_clipboard_before_browser_with_exact_text(self):
        body = 'hello + café\n$(touch /tmp/unwanted) `no` & # ? %'
        uri = "sms:%2B15551234567?body=hello%20+%20caf%C3%A9%0A%24%28touch%20%2Ftmp%2Funwanted%29%20%60no%60%20%26%20%23%20%3F%20%25"
        events = []

        def copy(command, *, input, check):
            self.assertEqual(command, [str(ROOT / "bin/copy")])
            self.assertEqual(input.decode("utf-8"), body)
            self.assertTrue(check)
            events.append("copy")

        def launch(executable, arguments):
            self.assertEqual(events, ["copy"])
            self.assertEqual(executable, "glide-bin")
            self.assertEqual(arguments[:2], ["glide-bin", "--new-tab"])
            url = urlsplit(arguments[2])
            self.assertEqual((url.scheme, url.netloc, url.path),
                             ("https", "voice.google.com", "/u/0/messages"))
            marker, payload = url.fragment.split("=", 1)
            self.assertEqual(marker, "dotfiles-sms")
            self.assertEqual(json.loads(unquote(payload)),
                             {"number": "+15551234567", "body": body, "copied": True,
                              "recipients": [{"address": "+15551234567", "number": "+15551234567"}]})
            events.append("open")

        with mock.patch.object(sys, "argv", ["open-google-voice", uri]), \
                mock.patch.object(voice.subprocess, "run", side_effect=copy), \
                mock.patch.object(voice.os, "execvp", side_effect=launch):
            voice.main()
        self.assertEqual(events, ["copy", "open"])

    def test_clipboard_failure_still_opens_draft_and_reports_no_fallback(self):
        with mock.patch.object(sys, "argv", ["open-google-voice", "sms:+15551234567?body=test"]), \
                mock.patch.object(voice.subprocess, "run",
                                  side_effect=subprocess.CalledProcessError(1, "copy")), \
                mock.patch.object(voice.os, "execvp") as launch:
            voice.main()
            payload = urlsplit(launch.call_args.args[1][2]).fragment.split("=", 1)[1]
            self.assertEqual(json.loads(unquote(payload)),
                             {"number": "+15551234567", "body": "test", "copied": False,
                              "recipients": [{"address": "+15551234567", "number": "+15551234567"}]})

    def test_absent_and_empty_body_are_distinct(self):
        self.assertEqual(voice.sms_draft("sms:+15551234567")["body"], None)
        self.assertEqual(voice.sms_draft("smsto:+1(555)123-4567?body=")["body"], "")

    def test_rejects_unsupported_or_malformed_links_before_effects(self):
        for uri in ("https://example.com", "sms://15551234567", "sms:+123,,+456",
                    "sms:123;phone-context=", "smsto:123:body",
                    "sms:123?body=a&Body=b", "sms:123#other",
                    "sms:123?body=%FF", "sms:123?body=%ZZ", "sms:123?body"):
            with self.subTest(uri=uri), self.assertRaises(ValueError):
                voice.sms_draft(uri)

    def test_article_and_rfc_examples(self):
        cases = [
            ("sms:", [], None),
            ("sms:+15551234567", ["+15551234567"], None),
            ("sms:+15551234567?body=", ["+15551234567"], ""),
            ("sms:+15551234567?body=Hello%20world!", ["+15551234567"], "Hello world!"),
            ("sms:+15551230001,+15551230002?body=Hello%20world!",
             ["+15551230001", "+15551230002"], "Hello world!"),
            ("sms://open?addresses=+15551230001,+15551230002&body=Hello%20world!",
             ["+15551230001", "+15551230002"], "Hello world!"),
            ("SMS:+1-(510)-555.0101?ignored=%FF&BoDy=hello%20there", ["+15105550101"], "hello there"),
            ("sms:+1?body=%2B+%26%3D%3F%23", ["+1"], "++&=?#"),
            ("sms:+12345678901234567890;unknown=%3B", ["+12345678901234567890"], None),
        ]
        for uri, numbers, body in cases:
            with self.subTest(uri=uri):
                draft = voice.sms_draft(uri)
                self.assertEqual([recipient["number"] for recipient in draft["recipients"]], numbers)
                self.assertEqual(draft["body"], body)

    def test_valid_subscribers_that_need_manual_resolution_are_preserved(self):
        for address in ("7042;phone-context=example.com", "911;phone-context=+1",
                        "12AB*#;phone-context=example.com", "+15551234567;ext=123",
                        "+15551234567;isub=%3B%FF", "+15551234567;m-routing=example"):
            with self.subTest(address=address):
                draft = voice.sms_draft("sms:" + address + "?body=hello")
                self.assertEqual(draft["recipients"], [{"address": address, "number": None}])
                self.assertEqual(draft["body"], "hello")

    def test_generated_recipient_lists_and_utf8_bodies_keep_their_meaning(self):
        rng = random.Random(5724)
        alphabet = "abc XYZ+&=?#%;\n\t\r'\\\"éλ🦀"
        seen = set()
        for case in range(250):
            count = case % 5
            numbers = ["+" + "".join(rng.choices("0123456789", k=rng.randrange(1, 23)))
                       for _ in range(count)]
            body = "".join(rng.choices(alphabet, k=case % 49))
            rendered = [number[:2] + "-(" + number[2:] + ")" for number in numbers]
            query = "body=" + quote(body, safe="")
            for uri in ("sms:" + ",".join(rendered) + "?" + query,
                        "sms://open?addresses=" + quote(",".join(rendered), safe="") + "&" + query):
                with self.subTest(case=case, uri=uri):
                    draft = voice.sms_draft(uri)
                    self.assertEqual([entry["number"] for entry in draft["recipients"]], numbers)
                    self.assertEqual(draft["body"], body)
                    seen.add((count, bool(body)))
        self.assertEqual(seen, {(count, empty) for count in range(5) for empty in (False, True)})

    def test_installer_preserves_an_unmanaged_launcher(self):
        with tempfile.TemporaryDirectory() as temporary, \
                mock.patch.dict(os.environ, {"XDG_DATA_HOME": temporary}):
            launcher = Path(temporary) / "dotfiles/open-google-voice"
            launcher.parent.mkdir()
            launcher.write_text("owned by someone else")
            with self.assertRaises(RuntimeError):
                setup.glide_sms_desktop(False)
            self.assertEqual(launcher.read_text(), "owned by someone else")

    @unittest.skipUnless(shutil.which("xdg-mime"), "xdg-mime is required")
    def test_installed_handler_registers_both_schemes_and_is_idempotent(self):
        with tempfile.TemporaryDirectory(prefix="voice space % ") as temporary, \
                mock.patch.dict(os.environ, {"XDG_DATA_HOME": temporary}):
            name = setup.glide_sms_desktop(False)
            self.assertEqual(setup.glide_sms_desktop(False), name)
            launcher = Path(temporary) / "dotfiles/open-google-voice"
            self.assertEqual(launcher.resolve(), ROOT / "libexec/setup/open_google_voice.py")
            desktop = Path(temporary) / "applications" / name
            if shutil.which("desktop-file-validate"):
                subprocess.run(["desktop-file-validate", str(desktop)], check=True)
            for scheme in ("sms", "smsto"):
                mime = f"x-scheme-handler/{scheme}"
                subprocess.run(["xdg-mime", "default", name, mime], check=True)
                result = subprocess.check_output(["xdg-mime", "query", "default", mime], text=True)
                self.assertEqual(result.strip(), name)

    @unittest.skipUnless(shutil.which("xdg-open"), "xdg-open is required")
    def test_terminal_open_reaches_clipboard_and_browser_through_desktop_entry(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            home = directory / "home"
            home.mkdir()
            (home / ".config").mkdir()
            (home / ".profile").write_text("")
            commands = directory / "bin"
            commands.mkdir()
            for name, source in {
                "xclip": 'import os, pathlib, sys\npathlib.Path(os.environ["VOICE_TEST_CLIPBOARD"]).write_bytes(sys.stdin.buffer.read())\n',
                "glide-bin": 'import json, os, pathlib, sys\npathlib.Path(os.environ["VOICE_TEST_BROWSER"]).write_text(json.dumps(sys.argv[1:]))\n',
            }.items():
                command = commands / name
                command.write_text(f"#!{sys.executable}\n" + source)
                command.chmod(0o755)
            clipboard = directory / "clipboard"
            browser = directory / "browser.json"
            environment = {
                **os.environ,
                "HOME": str(home), "XDG_CONFIG_HOME": str(home / ".config"),
                "XDG_DATA_HOME": str(home / ".local/share"),
                "XDG_CURRENT_DESKTOP": "X-Generic", "DESKTOP_SESSION": "generic",
                "DISPLAY": ":12345", "WAYLAND_DISPLAY": "",
                "PATH": str(commands) + ":/usr/bin:/bin",
                "VOICE_TEST_CLIPBOARD": str(clipboard),
                "VOICE_TEST_BROWSER": str(browser),
            }
            with mock.patch.dict(os.environ, environment, clear=True):
                name = setup.glide_sms_desktop(False)
                subprocess.run(["xdg-mime", "default", name, "x-scheme-handler/sms"], check=True)
            cases = [
                ("sms:+15551234567?body=hi%20kat", ["+15551234567"], "hi kat"),
                ("sms:+15551234567,+15551234568?body=hi%20kat", ["+15551234567", "+15551234568"], "hi kat"),
                ("sms://open?addresses=+15551234567,+15551234568&body=hi%20kat",
                 ["+15551234567", "+15551234568"], "hi kat"),
                ("sms:", [], None),
            ]
            for uri, numbers, body in cases:
                with self.subTest(uri=uri):
                    browser.unlink(missing_ok=True)
                    clipboard.write_bytes(b"preserve this clipboard")
                    result = subprocess.run(
                        [str(ROOT / "bin/open"), uri], env=environment,
                        capture_output=True, text=True, timeout=15,
                    )
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertTrue(browser.exists(), result.stderr)
                    self.assertEqual(clipboard.read_bytes(), body.encode() if body is not None else b"preserve this clipboard")
                    arguments = json.loads(browser.read_text())
                    self.assertEqual(arguments[0], "--new-tab")
                    payload = urlsplit(arguments[1]).fragment.split("=", 1)[1]
                    self.assertEqual(json.loads(unquote(payload)), {
                        "number": numbers[0] if len(numbers) == 1 else "", "body": body,
                        "copied": body is not None,
                        "recipients": [{"address": number, "number": number} for number in numbers],
                    })


if __name__ == "__main__":
    unittest.main()
