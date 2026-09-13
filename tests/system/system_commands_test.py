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

    def test_makeuser_stops_after_confirmation_is_refused(self) -> None:
        calls = self.directory / "adduser-calls"
        self.executable("adduser", 'printf "%s\\n" "$*" >> "$ADDUSER_CALLS"\n')

        result = subprocess.run(
            [str(ROOT / "bin/makeuser"), "citizen", "ssh-ed25519 key"],
            text=True,
            input="n\n",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=os.environ | {
                "ADDUSER_CALLS": str(calls),
                "PATH": f"{self.directory}:{os.environ['PATH']}",
            },
        )

        self.assertEqual(1, result.returncode)
        self.assertIn("error: aborting", result.stdout)
        self.assertFalse(calls.exists())
    def test_makeuser_validates_arguments_before_privileged_commands(self) -> None:
        calls = self.directory / "adduser-calls"
        self.executable("adduser", 'touch "$ADDUSER_CALLS"\n')

        result = subprocess.run(
            [str(ROOT / "bin/makeuser")],
            env=os.environ
            | {
                "ADDUSER_CALLS": str(calls),
                "PATH": f"{self.directory}:{os.environ['PATH']}",
            },
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

        self.assertEqual(2, result.returncode)
        self.assertIn("usage:", result.stderr)
        self.assertFalse(calls.exists())
    def test_ssh_wrapper_cleans_up_agents_and_propagates_startup_failure(self) -> None:
        calls = self.directory / "ssh-wrapper-calls"
        self.executable(
            "ssh-add",
            'printf "ssh-add %s\\n" "$*" >> "$SSH_WRAPPER_CALLS"\n'
            'if [ "$1" = -l ] && [ ! -e "$AGENT_READY" ]; then exit 1; fi\n'
            'touch "$AGENT_READY"\n',
        )
        self.executable(
            "ssh-agent",
            'printf "ssh-agent %s\\n" "$*" >> "$SSH_WRAPPER_CALLS"\n'
            'if [ "$1" = -k ]; then exit 0; fi\n'
            '[ -z "${AGENT_STATUS:-}" ] || exit "$AGENT_STATUS"\n'
            'printf "SSH_AUTH_SOCK=/tmp/mock-agent; export SSH_AUTH_SOCK; SSH_AGENT_PID=123; export SSH_AGENT_PID;\\n"\n',
        )
        self.executable("systemctl", "exit 0\n")
        self.executable("ssh", "exit 17\n")
        environment = os.environ | {
            "AGENT_READY": str(self.directory / "agent-ready"),
            "SSH_WRAPPER_CALLS": str(calls),
            "PATH": f"{self.directory}:{os.environ['PATH']}",
        }

        session = subprocess.run(
            [str(ROOT / "bin/ssh.sh"), "host"], env=environment, check=False
        )
        call_text = calls.read_text()
        calls.unlink()
        (self.directory / "agent-ready").unlink(missing_ok=True)
        startup_failure = subprocess.run(
            [str(ROOT / "bin/ssh.sh"), "host"],
            env=environment | {"AGENT_STATUS": "23"},
            check=False,
        )

        self.assertEqual(17, session.returncode)
        self.assertIn("ssh-agent -k", call_text)
        self.assertEqual(23, startup_failure.returncode)
    def test_firefox_preserves_spaces_in_windows_path(self) -> None:
        calls = self.directory / "firefox-calls"
        self.executable("wslpath", "printf 'C:\\\\Users\\\\One Esk\\\\page.html\\n'\n")
        self.executable(
            "firefox",
            'printf "%s\\n%s\\n" "$#" "$1" > "$FIREFOX_CALLS"\n',
        )

        result = subprocess.run(
            [str(ROOT / "bin/firefox.sh"), "/mnt/c/Users/One Esk/page.html"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=os.environ | {
                "FIREFOX": str(self.directory / "firefox"),
                "FIREFOX_CALLS": str(calls),
                "PATH": f"{self.directory}:{os.environ['PATH']}",
            },
        )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("1\nC:\\Users\\One Esk\\page.html\n", calls.read_text())
    def test_cargo_doc_dev_accepts_no_subcommand_argument(self) -> None:
        calls = self.directory / "cargo-calls"
        self.executable("cargo", 'printf "%s\\n" "$*" > "$CARGO_CALLS"\n')

        result = subprocess.run(
            [str(ROOT / "bin/cargo-doc-dev")],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=os.environ | {
                "CARGO": str(self.directory / "cargo"),
                "CARGO_CALLS": str(calls),
            },
        )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("doc --document-private-items --no-deps\n", calls.read_text())
    def test_audio_action_survives_notification_failure(self) -> None:
        calls = self.directory / "cmus-calls"
        self.executable("which", "exit 99\n")
        self.executable("notify-send", "exit 1\n")
        self.executable("cmus-remote", 'printf "%s\\n" "$*" > "$CMUS_CALLS"\n')

        result = subprocess.run(
            [str(ROOT / "bin/audio"), "toggle"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=os.environ | {
                "CMUS_CALLS": str(calls),
                "PATH": f"{self.directory}:{os.environ['PATH']}",
            },
        )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("--pause\n", calls.read_text())
    def test_audio_media_action_requires_the_command_it_invokes(self) -> None:
        self.executable("cmus", "exit 0\n")

        result = subprocess.run(
            [str(ROOT / "bin/audio"), "play", "--quiet"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=os.environ | {"PATH": str(self.directory)},
        )

        self.assertEqual(1, result.returncode)
        self.assertIn("no known media player", result.stderr)
    def test_audio_reports_missing_volume_backend_on_stderr(self) -> None:
        for verb in ("up", "down", "mute", "unmute"):
            with self.subTest(verb=verb):
                result = subprocess.run(
                    [str(ROOT / "bin/audio"), verb, "--quiet"],
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    env=os.environ | {"PATH": str(self.directory)},
                    check=False,
                )

                self.assertEqual(1, result.returncode)
                self.assertEqual("", result.stdout)
                self.assertEqual(
                    "ERROR: no known volume manager available\n", result.stderr
                )
    def test_audio_does_not_announce_a_failed_media_action(self) -> None:
        notifications = self.directory / "notifications"
        self.executable("cmus-remote", "exit 23\n")
        self.executable(
            "notify-send",
            'printf "%s\\n" "$*" > "$NOTIFICATIONS"\n',
        )

        result = subprocess.run(
            [str(ROOT / "bin/audio"), "next"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=os.environ | {
                "NOTIFICATIONS": str(notifications),
                "PATH": str(self.directory),
            },
        )

        self.assertEqual(23, result.returncode)
        self.assertFalse(notifications.exists())
    def test_audio_rejects_complete_invalid_grammar_before_effects(self) -> None:
        effects = self.directory / "effects"
        for command in ("amixer", "cmus-remote", "notify-send"):
            self.executable(command, 'printf "%s\\n" "$0 $*" >> "$EFFECTS"\n')
        environment = os.environ | {
            "EFFECTS": str(effects),
            "PATH": f"{self.directory}:{os.environ['PATH']}",
        }

        for arguments in (
            [],
            ["play", "quite"],
            ["next", "--quiet", "unexpected"],
            ["toggle", "--unknown"],
            ["play", "--quiet", "--quiet"],
            ["--quiet", "play"],
        ):
            with self.subTest(arguments=arguments):
                result = subprocess.run(
                    [str(ROOT / "bin/audio"), *arguments],
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    env=environment,
                    check=False,
                )
                self.assertEqual(2, result.returncode, result.stderr)
                self.assertIn("usage:", result.stderr)
                self.assertFalse(effects.exists())
    def test_audio_help_lists_the_complete_grammar_without_effects(self) -> None:
        result = subprocess.run(
            [str(ROOT / "bin/audio"), "--help"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=os.environ | {"PATH": str(self.directory)},
            check=False,
        )

        self.assertEqual(0, result.returncode)
        self.assertIn("unmute", result.stderr)
    def test_hours_parses_meridiem_and_zero_pads_fractional_hours(self) -> None:
        result = subprocess.run(
            [str(ROOT / "bin/hours")],
            input="9:00AM-5:03PM\n",
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("8.05\n", result.stdout)
    def test_groupme_transcript_reads_file_and_flushes_final_messages(self) -> None:
        transcript = self.directory / "groupme transcript"
        transcript.write_text("Avatar\nAlice\nFirst\n9:00 PM\nAvatar\nBob\nFinal\n")

        result = subprocess.run(
            [str(ROOT / "bin/groupme2transcript"), "--input", str(transcript)],
            input="Avatar\nWrong\nstdin\n",
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("[][Alice]: First\n", result.stdout)
        self.assertIn("[9:00 PM][Bob]: Final\n", result.stdout)
        self.assertNotIn("Wrong", result.stdout)
    def test_pretty_parser_does_not_execute_input(self) -> None:
        marker = self.directory / "executed"
        malicious = f'__import__("pathlib").Path({str(marker)!r}).touch()'
        rejected = subprocess.run(
            [str(ROOT / "bin/pretty.py")],
            input=malicious + "\n",
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        valid = subprocess.run(
            [str(ROOT / "bin/pretty.py")],
            input="[65, 66]\n",
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

        self.assertNotEqual(0, rejected.returncode)
        self.assertFalse(marker.exists())
        self.assertEqual(0, valid.returncode, valid.stderr)
        self.assertEqual("AB\n", valid.stdout)
    def test_toggle_dnd_does_not_mutate_state_after_query_failure(self) -> None:
        calls = self.directory / "gsettings-calls"
        self.executable(
            "gsettings",
            'printf "%s\\n" "$*" >> "$GSETTINGS_CALLS"\n'
            'case "$1" in get) exit 29;; esac\n',
        )

        result = subprocess.run(
            [str(ROOT / "bin/toggle-dnd")],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=os.environ
            | {
                "GSETTINGS_CALLS": str(calls),
                "PATH": f"{self.directory}:{os.environ['PATH']}",
            },
        )

        self.assertEqual(29, result.returncode)
        self.assertEqual(
            "get org.gnome.desktop.notifications show-banners\n",
            calls.read_text(),
        )
    def test_toggle_dnd_rejects_arguments_before_querying(self) -> None:
        calls = self.directory / "gsettings-calls"
        self.executable("gsettings", 'touch "$GSETTINGS_CALLS"\n')

        for arguments in (["--unknown"], ["true"], ["false", "extra"]):
            with self.subTest(arguments=arguments):
                result = subprocess.run(
                    [str(ROOT / "bin/toggle-dnd"), *arguments],
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    env=os.environ | {
                        "GSETTINGS_CALLS": str(calls),
                        "PATH": f"{self.directory}:{os.environ['PATH']}",
                    },
                    check=False,
                )
                self.assertEqual(2, result.returncode)
                self.assertIn("usage:", result.stderr)
                self.assertFalse(calls.exists())
    def test_toggle_dnd_requires_boolean_output_and_verifies_the_write(self) -> None:
        calls = self.directory / "gsettings-calls"
        state = self.directory / "state"
        self.executable(
            "gsettings",
            'printf "<%s>\\n" "$*" >> "$GSETTINGS_CALLS"\n'
            'case "$1" in get) cat "$GSETTINGS_STATE";; set) printf "%s\\n" "$4" > "$GSETTINGS_STATE";; esac\n',
        )
        environment = os.environ | {
            "GSETTINGS_CALLS": str(calls),
            "GSETTINGS_STATE": str(state),
            "PATH": f"{self.directory}:{os.environ['PATH']}",
        }

        for malformed in ("", "unexpected-state\n", "'true'\n", "true\nfalse\n"):
            state.write_text(malformed)
            calls.unlink(missing_ok=True)
            result = subprocess.run(
                [str(ROOT / "bin/toggle-dnd")], env=environment, check=False
            )
            self.assertEqual(1, result.returncode)
            self.assertEqual(
                "<get org.gnome.desktop.notifications show-banners>\n",
                calls.read_text(),
            )

        state.write_text("true\n")
        calls.unlink()
        result = subprocess.run(
            [str(ROOT / "bin/toggle-dnd")], env=environment, check=False
        )
        self.assertEqual(0, result.returncode)
        self.assertEqual("false\n", state.read_text())
        self.assertEqual(
            "<get org.gnome.desktop.notifications show-banners>\n"
            "<set org.gnome.desktop.notifications show-banners false>\n"
            "<get org.gnome.desktop.notifications show-banners>\n",
            calls.read_text(),
        )
    def test_toggle_dnd_reports_readback_mismatch(self) -> None:
        calls = self.directory / "gsettings-calls"
        self.executable(
            "gsettings",
            'printf "%s\\n" "$*" >> "$GSETTINGS_CALLS"\n'
            'case "$1" in get) printf "true\\n";; esac\n',
        )
        result = subprocess.run(
            [str(ROOT / "bin/toggle-dnd")],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=os.environ | {
                "GSETTINGS_CALLS": str(calls),
                "PATH": f"{self.directory}:{os.environ['PATH']}",
            },
            check=False,
        )

        self.assertEqual(3, result.returncode)
        self.assertIn("readback", result.stderr)
        self.assertEqual(3, len(calls.read_text().splitlines()))
    def test_youtube_search_passes_only_search_terms(self) -> None:
        calls = self.directory / "ddg-calls"
        self.executable("ddg", 'printf "<%s>\\n" "$@" > "$DDG_CALLS"\n')

        result = subprocess.run(
            [str(ROOT / "bin/youtube_search"), "tea", "ceremony"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=os.environ | {
                "DDG": str(self.directory / "ddg"),
                "DDG_CALLS": str(calls),
            },
        )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(
            "<site:youtube.com/playlist>\n<tea>\n<ceremony>\n",
            calls.read_text(),
        )


if __name__ == "__main__":
    unittest.main()
