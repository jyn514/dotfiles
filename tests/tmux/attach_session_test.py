import json
import os
from pathlib import Path
import signal
import shutil
import subprocess
import sys
import tempfile
import tomllib
import unittest


ROOT = Path(__file__).resolve().parents[2]


class CommandIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)

    def executable(self, name: str, contents: str) -> None:
        path = self.directory / name
        path.write_text("#!/bin/sh\n" + contents)
        path.chmod(0o755)

    def test_attach_session_propagates_tmux_query_failures(self) -> None:
        self.executable(
            "tmux",
            'case "$1" in\n'
            "  show-option) exit 1;;\n"
            "  display-message) exit 23;;\n"
            "esac\n",
        )

        result = subprocess.run(
            [str(ROOT / "libexec/tmux/attach-session.sh")],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=os.environ | {"PATH": f"{self.directory}:{os.environ['PATH']}"},
        )

        self.assertEqual(23, result.returncode)
    def test_attach_session_propagates_session_listing_failure(self) -> None:
        self.executable(
            "tmux",
            'case "$1" in\n'
            "  show-option) exit 1;;\n"
            "  display-message)\n"
            '    case "$*" in\n'
            "      *client_last_session*) printf '\\n';;\n"
            "      *session_attached*) printf '1\\n';;\n"
            "    esac;;\n"
            "  list-sessions) exit 24;;\n"
            "esac\n",
        )

        result = subprocess.run(
            [str(ROOT / "libexec/tmux/attach-session.sh")],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=os.environ | {"PATH": f"{self.directory}:{os.environ['PATH']}"},
        )

        self.assertEqual(24, result.returncode)
    def test_attach_session_modes_do_not_run_session_queries(self) -> None:
        calls = self.directory / "tmux-calls"
        self.executable("tmux", 'printf "%s\\n" "$*" >> "$TMUX_CALLS"\n')
        environment = os.environ | {
            "PATH": f"{self.directory}:{os.environ['PATH']}",
            "TMUX_CALLS": str(calls),
        }

        for mode in ("disable", "enable"):
            result = subprocess.run(
                [str(ROOT / "libexec/tmux/attach-session.sh"), mode],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=environment,
            )
            self.assertEqual(0, result.returncode, result.stderr)

        self.assertEqual(
            [
                "set-option -s @attach-session-disable 1",
                "set-option -su @attach-session-disable",
            ],
            calls.read_text().splitlines(),
        )
    def test_attach_session_does_not_switch_after_set_option_failure(self) -> None:
        calls = self.directory / "tmux-calls"
        self.executable(
            "tmux",
            'printf "%s\\n" "$*" >> "$TMUX_CALLS"\n'
            'case "$1 $2" in\n'
            "  \"show-option -sv\") exit 1;;\n"
            "  \"display-message -p\")\n"
            '    case "$*" in *client_last_session*) printf \'\\n\';; *) printf \'1\\n\';; esac;;\n'
            "  \"list-sessions -f\") printf '@2\\n';;\n"
            "  \"set-option destroy-unattached\") exit 25;;\n"
            "esac\n",
        )

        result = subprocess.run(
            [str(ROOT / "libexec/tmux/attach-session.sh")],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=os.environ | {
                "PATH": f"{self.directory}:{os.environ['PATH']}",
                "TMUX_CALLS": str(calls),
            },
        )

        self.assertEqual(25, result.returncode)
        self.assertNotIn("switch-client", calls.read_text())
    def test_attach_session_selects_first_detached_session_with_exact_arguments(self) -> None:
        calls = self.directory / "tmux-calls"
        self.executable(
            "tmux",
            'printf "<%s>" "$1" >> "$TMUX_CALLS"\n'
            'shift\n'
            'printf " <%s>" "$@" >> "$TMUX_CALLS"\n'
            'printf "\\n" >> "$TMUX_CALLS"\n'
            'case "$(tail -n 1 "$TMUX_CALLS")" in\n'
            '  "<show-option> <-sv> <@attach-session-disable>") exit 1;;\n'
            '  "<list-sessions> <-f> <#{?session_attached,0,1}> <-F> <#{session_id}>")\n'
            "    printf '@9\\n@12\\n';;\n"
            '  *client_last_session*) printf \'\\n\';;\n'
            '  *session_attached*) printf \'1\\n\';;\n'
            'esac\n',
        )

        result = subprocess.run(
            [str(ROOT / "libexec/tmux/attach-session.sh")],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=os.environ | {
                "PATH": f"{self.directory}:{os.environ['PATH']}",
                "TMUX_CALLS": str(calls),
            },
        )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(
            [
                "<show-option> <-sv> <@attach-session-disable>",
                "<display-message> <-p> <#{client_last_session}>",
                "<display-message> <-p> <#{session_attached}>",
                "<list-sessions> <-f> <#{?session_attached,0,1}> <-F> <#{session_id}>",
                "<set-option> <destroy-unattached>",
                "<switch-client> <-t> <@9>",
            ],
            calls.read_text().splitlines(),
        )


if __name__ == "__main__":
    unittest.main()
