#!/usr/bin/env python3

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
FIXTURES = Path(__file__).resolve().parent / "fixtures"
PWSH = shutil.which("pwsh")


@unittest.skipUnless(PWSH and os.name == "posix", "PowerShell and POSIX executables are required")
class EmojiDownloadTests(unittest.TestCase):
    def download(self, records: list[str], *, stdin: bool = False) -> tuple[list, dict]:
        with tempfile.TemporaryDirectory(prefix="emoji-download-") as temporary:
            base = Path(temporary)
            output = base / "output"
            output.mkdir()
            commands = base / "commands"
            commands.mkdir()
            curl = commands / "curl"
            shutil.copyfile(FIXTURES / "curl", curl)
            curl.chmod(0o755)
            log = base / "curl.jsonl"
            records_path = base / "records.json"
            records_path.write_text(json.dumps(records))
            environment = dict(
                os.environ,
                PATH=str(commands) + os.pathsep + os.environ["PATH"],
                EMOJI_CURL_LOG=str(log),
                EMOJI_FIXTURE_ROOT=str(base),
            )
            if stdin:
                command = [str(ROOT / "bin/emojis")]
                data = "\n".join(records) + "\n"
            else:
                command = [
                    PWSH, "-NoProfile", "-NonInteractive", "-File",
                    str(FIXTURES / "pipeline.ps1"), str(ROOT / "bin/emojis"),
                    str(records_path),
                ]
                data = None
            result = subprocess.run(
                command, input=data, env=environment, cwd=output,
                text=True, capture_output=True, timeout=30,
            )
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual("", result.stdout)
            self.assertEqual("", result.stderr)
            calls = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
            files = {
                str(path.relative_to(base)): path.read_text()
                for path in base.rglob("*.png")
            }
            return calls, files

    def assert_downloads(self, records: list[str], expected: list[tuple[str, str]], **options) -> None:
        calls, files = self.download(records, **options)
        self.assertEqual(
            [[f"https://cdn.discordapp.com/emojis/{identifier}.png?size=128&quality=lossless",
              "-o", f"{name}.png"] for name, identifier in expected],
            calls,
        )
        self.assertEqual(
            {f"output/{name}.png": "offline emoji fixture\n" for name, _ in expected},
            files,
        )

    def test_native_static_and_animated_markup_can_be_adjacent(self) -> None:
        # Discord's Message Formatting examples; animated input still requests PNG.
        self.assert_downloads(
            ["<:mmLol:216154654256398347><a:b1nzy:392938283556143104>"],
            [("mmLol", "216154654256398347"), ("b1nzy", "392938283556143104")],
        )

    def test_both_bracketless_convenience_forms_remain_supported(self) -> None:
        self.assert_downloads(
            [":mmLol:216154654256398347 a:b1nzy:392938283556143104"],
            [("mmLol", "216154654256398347"), ("b1nzy", "392938283556143104")],
        )

    def test_pipeline_records_and_multiline_stdin_preserve_order(self) -> None:
        records = ["<:one:123> :two:456", "<a:three:789>"]
        expected = [("one", "123"), ("two", "456"), ("three", "789")]
        self.assert_downloads(records, expected)
        self.assert_downloads(records, expected, stdin=True)

    def test_whitespace_and_multiline_records_separate_complete_tokens(self) -> None:
        self.assert_downloads(
            ["  <:one:123>\t<a:two:456>\r\n:three:789  "],
            [("one", "123"), ("two", "456"), ("three", "789")],
        )

    def test_names_are_not_limited_to_ascii_and_ids_have_no_fixed_length(self) -> None:
        self.assert_downloads(
            ["<:éclair:1> :x:0002 a:dot.name:123456789012345678901234567890 :$literal:3 :-dash:4"],
            [("éclair", "1"), ("x", "0002"), ("dot.name", "123456789012345678901234567890"),
             ("$literal", "3"), ("-dash", "4")],
        )

    def test_path_bearing_names_do_not_reach_the_filename_writer(self) -> None:
        for name in ("../outside", "..\\outside", "/absolute", "\\absolute", "part/name", "part\\name", ".", "..", "nul\0name"):
            with self.subTest(name=name):
                self.assert_downloads([f"<:{name}:123>", f":{name}:456"], [])

    def test_incomplete_or_unrelated_tokens_do_not_reach_curl(self) -> None:
        # Empty NAME/ID is missing a field of the complete NAME:ID fragment.
        for token in (
            "hello", "<t:1618953630>", "<@123>", "<wrong:ok:123>", "wrong:ok:123",
            "<:ok:123/extra>", "<:ok:123?x>", "<:ok:-123>", "<:ok:１２３>",
            "<:ok:123:456>", "<:ok:123", ":ok:123>", "<:ok:>", "<::123>",
            "::123", "<a::123>", "a::123", "prefix<:ok:123>", "<:ok:123>suffix",
            "<<:ok:123>>", "<:ok:123><broken>", "", " ",
        ):
            with self.subTest(token=token):
                # Adjacent chunks are independent, not an atomic batch: the valid
                # token preceding <broken> should still run.
                expected = [("ok", "123")] if token == "<:ok:123><broken>" else []
                self.assert_downloads([token], expected)

    def test_invalid_tokens_do_not_block_later_valid_tokens(self) -> None:
        self.assert_downloads(
            ["hello <:../outside:123> <:ok:123/extra> <:good:456>", "a:fine:789"],
            [("good", "456"), ("fine", "789")],
        )

    def test_tokens_are_not_joined_across_pipeline_records(self) -> None:
        self.assert_downloads(["<:split:", "123>", "<:whole:456>"], [("whole", "456")])

    def test_repeated_names_and_ids_are_not_deduplicated(self) -> None:
        self.assert_downloads(
            ["<:same:123><:same:456> <:other:456>"],
            [("same", "123"), ("same", "456"), ("other", "456")],
        )


if __name__ == "__main__":
    unittest.main()
