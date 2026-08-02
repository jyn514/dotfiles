#!/usr/bin/env python3

import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools/prompt"))
from prompt_renderer import main as renderer  # noqa: E402


class PromptFactTests(unittest.TestCase):
    def test_uses_runtime_and_os_id_in_a_container(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            os_release = Path(directory) / "os-release"
            os_release.write_text('NAME="Alpine Linux"\nID=alpine\n')
            with mock.patch.dict(os.environ, {"container": "podman"}):
                label = renderer.host_label(os_release)

        self.assertEqual("podman:alpine", label)

    def test_supports_quoted_os_id(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            os_release = Path(directory) / "os-release"
            os_release.write_text('ID="ubuntu"\n')
            with mock.patch.dict(os.environ, {"container": "docker"}):
                label = renderer.host_label(os_release)

        self.assertEqual("docker:ubuntu", label)

    def test_uses_runtime_when_os_release_is_unavailable(self) -> None:
        with mock.patch.dict(os.environ, {"container": "podman"}):
            label = renderer.host_label(Path("/missing/os-release"))

        self.assertEqual("podman", label)

    def test_uses_hostname_outside_a_container(self) -> None:
        with mock.patch.dict(os.environ, {"container": ""}):
            label = renderer.host_label()

        self.assertEqual(socket.gethostname(), label)

    def test_display_pwd_treats_home_as_literal_text_and_trims_components(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "home[1]&"
            cwd = home / "zero" / "one" / "two"
            cwd.mkdir(parents=True)

            displayed = renderer.display_path(cwd, home)

        self.assertEqual("~/.../one/two", displayed)


class PromptRenderingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.facts = renderer.Facts(
            label="shell",
            host="host",
            path="~/src",
            repository=renderer.Repository("red", "main"),
            ssh=True,
            root=False,
        )

    def test_exact_bash_target_bytes(self) -> None:
        output = renderer.render_left(self.facts, "bash", 0, 80)

        self.assertEqual(
            "\\[\x1b[2;37m\\](shell@host"
            "\\[\x1b[0;31m\\][ssh]"
            "\\[\x1b[2;37m\\]) "
            "\\[\x1b[2;37m\\]~/src "
            "\\[\x1b[0;31m\\]main\n"
            "\\[\x1b[0;32m\\]; "
            "\\[\x1b[0;0m\\]",
            output,
        )
        self.assertFalse(output.endswith("\n"))

    def test_exact_zsh_and_fish_markers(self) -> None:
        zsh = renderer.render_left(self.facts, "zsh", 1, 80)
        fish = renderer.render_left(self.facts, "fish-left", 1, 80)

        self.assertEqual(
            "%{\x1b[2;37m%}(shell@host"
            "%{\x1b[0;31m%}[ssh]"
            "%{\x1b[2;37m%}) "
            "%{\x1b[2;37m%}~/src "
            "%{\x1b[0;31m%}main\n"
            "%{\x1b[0;31m%}; "
            "%{\x1b[0;0m%}",
            zsh,
        )
        self.assertEqual(
            "\x1b[2;37m(shell@host"
            "\x1b[0;31m[ssh]"
            "\x1b[2;37m) "
            "\x1b[2;37m~/src "
            "\x1b[0;31mmain\n"
            "\x1b[0;31m; "
            "\x1b[0;0m",
            fish,
        )

    def test_narrow_terminal_breaks_identity_from_location(self) -> None:
        output = renderer.render_left(self.facts, "fish-left", 0, 10)

        self.assertIn("host\x1b[0;31m[ssh]\x1b[2;37m)\n\x1b[2;37m~/src", output)

    def test_vscode_target_omits_native_status_prompt(self) -> None:
        output = renderer.render_left(self.facts, "fish-left", 23, 80, vscode=True)

        self.assertTrue(output.endswith("\n\x1b[0;0m"))
        self.assertNotIn("; ", output)

    def test_visible_width_ignores_markers_controls_and_combining_marks(self) -> None:
        value = "\\[\x1b[0;31m\\]e\N{COMBINING ACUTE ACCENT}界\\[\x1b[0;0m\\]"

        self.assertEqual(3, renderer.visible_width(value))

    def test_data_controls_are_visible_and_cannot_inject_ansi(self) -> None:
        undecodable = os.fsdecode(b"\xff")
        escaped = renderer.terminal_text(f"tea\x1b\n界{undecodable}")

        self.assertEqual("tea\\u001b\\n界\\xff", escaped)
        self.assertNotIn("\x1b", escaped)

    def test_fish_right_target_formats_timestamp_and_duration(self) -> None:
        self.assertEqual("\x1b[2;37m12:34", renderer.render_right(50, "12:34"))
        self.assertEqual("\x1b[2;37m+12.35s", renderer.render_right(12_345, ""))
        self.assertEqual("", renderer.render_right(99, ""))

    def test_claude_target_is_plain_and_complete(self) -> None:
        facts = renderer.Facts("Opus", "host", "~/work", None, False, False)
        with tempfile.TemporaryDirectory() as directory:
            data = {
                "workspace": {"current_dir": directory},
                "model": {"display_name": "Opus"},
                "context_window": {"used_percentage": 42},
            }
            with mock.patch.object(renderer, "collect", return_value=facts):
                output = renderer.render_claude(data)

        self.assertEqual(" ctx:42% (Opus@host) ~/work", output)
        self.assertNotIn("\x1b", output)

    def test_invalid_cli_writes_no_partial_prompt(self) -> None:
        result = subprocess.run(
            [str(ROOT / "bin/prompt-command"), "fish-left", "bad", "0"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

        self.assertNotEqual(0, result.returncode)
        self.assertEqual(b"", result.stdout)
        self.assertIn(b"status must be an integer", result.stderr)


class PromptJujutsuTests(unittest.TestCase):
    def test_jj_info_resets_description_color(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            binaries = Path(directory)
            jj = binaries / "jj"
            jj.write_text("#!/bin/sh\nprintf 'false::parent\ntrue:bookmark:description\n'\n")
            jj.chmod(0o755)
            result = subprocess.run(
                [str(ROOT / "bin/jj-info")],
                env=os.environ | {"PATH": f"{binaries}:{os.environ['PATH']}"},
                text=True,
                capture_output=True,
                check=False,
            )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("\x01\x1b[0;0m\x02bookmark", result.stdout)

    def test_failed_jj_query_falls_back_to_git_refs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            binaries = root / "bin"
            binaries.mkdir()
            (root / ".jj").mkdir()
            git = binaries / "git"
            git.write_text(
                "#!/bin/sh\n"
                'case "$1:$2" in\n'
                "  rev-parse:--git-dir) printf '.git\\n';;\n"
                "  diff-index:*) exit 0;;\n"
                "  symbolic-ref:*) exit 1;;\n"
                "  tag:*) exit 0;;\n"
                "  for-each-ref:*) printf 'origin/main\\n';;\n"
                "  *) exit 99;;\n"
                "esac\n"
            )
            git.chmod(0o755)
            jj = binaries / "jj"
            jj.write_text("#!/bin/sh\nexit 23\n")
            jj.chmod(0o755)

            result = subprocess.run(
                [str(ROOT / "bin/prompt-command"), "fish-left", "0", "0", "fish"],
                cwd=root,
                env=os.environ | {"PATH": f"{binaries}:{os.environ['PATH']}"},
                text=True,
                capture_output=True,
                check=False,
            )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("origin/main", result.stdout)
        self.assertNotIn("(jj:", result.stdout)

    def test_unborn_repository_detection_does_not_depend_on_find(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            binaries = root / "bin"
            binaries.mkdir()
            marker = root / "find-called"
            git = binaries / "git"
            git.write_text(
                "#!/bin/sh\n"
                'case "$1:$2" in\n'
                "  rev-parse:--git-dir) printf '.git\\n';;\n"
                "  diff-index:*) exit 1;;\n"
                "  rev-parse:--verify) exit 1;;\n"
                "  symbolic-ref:--short) printf 'main\\n';;\n"
                "  *) exit 99;;\n"
                "esac\n"
            )
            git.chmod(0o755)
            find = binaries / "find"
            find.write_text(f"#!/bin/sh\ntouch {marker}\nexit 99\n")
            find.chmod(0o755)
            result = subprocess.run(
                [str(ROOT / "bin/prompt-command"), "fish-left", "0", "0", "fish"],
                cwd=root,
                env=os.environ | {"PATH": f"{binaries}:{os.environ['PATH']}"},
                text=True,
                capture_output=True,
                check=False,
            )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("\x1b[2;32m", result.stdout)
        self.assertFalse(marker.exists())

    def test_hanging_jj_cannot_block_prompt_rendering(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            nested = root / "nested"
            binaries = root / "bin"
            (root / ".jj").mkdir()
            nested.mkdir()
            binaries.mkdir()
            git = binaries / "git"
            git.write_text(
                "#!/bin/sh\n"
                'case "$1" in\n'
                "  rev-parse) printf '.git\\n';;\n"
                "  diff-index) exit 0;;\n"
                "  symbolic-ref) exit 1;;\n"
                "esac\n"
            )
            git.chmod(0o755)
            jj = binaries / "jj"
            jj.write_text("#!/bin/sh\nsleep 10\n")
            jj.chmod(0o755)
            started = time.monotonic()
            result = subprocess.run(
                [str(ROOT / "bin/prompt-command"), "fish-left", "0", "0", "fish"],
                cwd=nested,
                env=os.environ | {"PATH": f"{binaries}:{os.environ['PATH']}"},
                text=True,
                capture_output=True,
                check=False,
                timeout=3,
            )
            elapsed = time.monotonic() - started

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertLess(elapsed, 2)

    def test_hanging_git_cannot_block_prompt_rendering(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            git = root / "git"
            git.write_text("#!/bin/sh\nsleep 10\n")
            git.chmod(0o755)
            started = time.monotonic()
            result = subprocess.run(
                [str(ROOT / "bin/prompt-command"), "fish-left", "0", "0", "fish"],
                cwd=root,
                env=os.environ | {"PATH": f"{root}:{os.environ['PATH']}"},
                text=True,
                capture_output=True,
                check=False,
                timeout=3,
            )
            elapsed = time.monotonic() - started

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertLess(elapsed, 2)


if __name__ == "__main__":
    unittest.main()
