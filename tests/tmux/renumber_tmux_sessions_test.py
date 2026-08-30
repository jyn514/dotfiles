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

    def test_renumber_tmux_sessions_avoids_name_collisions(self) -> None:
        calls = self.directory / "tmux-calls"
        self.executable(
            "tmux",
            'if [ "$1" = list-sessions ]; then\n'
            "  printf '10\\n0\\n2\\n'\n"
            "else\n"
            '  printf "%s %s %s\\n" "$1" "$3" "$4" >> "$TMUX_CALLS"\n'
            "fi\n",
        )

        result = subprocess.run(
            [str(ROOT / "libexec/tmux/renumber-tmux-sessions.sh")],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=os.environ | {
                "PATH": f"{self.directory}:{os.environ['PATH']}",
                "TMUX_CALLS": str(calls),
            },
        )

        self.assertEqual(0, result.returncode, result.stderr)
        renames = [line.split() for line in calls.read_text().splitlines()]
        self.assertEqual(["0", "2", "10"], [line[1] for line in renames[:3]])
        self.assertEqual(["1", "2", "3"], [line[2] for line in renames[3:]])
        self.assertEqual(
            [line[2] for line in renames[:3]],
            [line[1] for line in renames[3:]],
        )
    def test_renumber_tmux_sessions_propagates_listing_failure(self) -> None:
        self.executable("tmux", "exit 19\n")

        result = subprocess.run(
            [str(ROOT / "libexec/tmux/renumber-tmux-sessions.sh")],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=os.environ | {"PATH": f"{self.directory}:{os.environ['PATH']}"},
        )

        self.assertEqual(19, result.returncode)
    def test_renumber_tmux_sessions_rolls_back_second_phase_failure(self) -> None:
        calls = self.directory / "tmux-calls"
        self.executable(
            "tmux",
            'if [ "$1" = list-sessions ]; then\n'
            "  printf '10\\n0\\n2\\n'\n"
            "else\n"
            '  printf "%s %s %s\\n" "$1" "$3" "$4" >> "$TMUX_CALLS"\n'
            '  case "$3:$4" in __renumber-tmux-*-2:2) exit 27;; esac\n'
            "fi\n",
        )

        result = subprocess.run(
            [str(ROOT / "libexec/tmux/renumber-tmux-sessions.sh")],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=os.environ
            | {
                "PATH": f"{self.directory}:{os.environ['PATH']}",
                "TMUX_CALLS": str(calls),
            },
        )

        self.assertEqual(27, result.returncode)
        renames = [line.split() for line in calls.read_text().splitlines()]
        recovery = renames[-3:]
        self.assertEqual(["0", "2", "10"], [line[2] for line in recovery])
        self.assertTrue(all("recovery" in line[1] for line in recovery))
    def test_renumber_tmux_sessions_restores_state_after_each_failure_or_signal(self) -> None:
        tmux = self.directory / "tmux"
        tmux.write_text(
            "#!/usr/bin/env python3\n"
            "import json, os, signal, sys\n"
            "state_path = os.environ['TMUX_STATE']\n"
            "count_path = os.environ['TMUX_COUNT']\n"
            "names = json.loads(open(state_path).read())\n"
            "if sys.argv[1] == 'list-sessions':\n"
            "    print('\\n'.join(names))\n"
            "    raise SystemExit(0)\n"
            "count = int(open(count_path).read()) + 1\n"
            "open(count_path, 'w').write(str(count))\n"
            "old, new = sys.argv[3:5]\n"
            "if old not in names or (new != old and new in names):\n"
            "    raise SystemExit(90)\n"
            "fail_at = {int(value) for value in os.environ.get('TMUX_FAIL_AT', '').split(',') if value}\n"
            "if count in fail_at:\n"
            "    raise SystemExit(27)\n"
            "names[names.index(old)] = new\n"
            "open(state_path, 'w').write(json.dumps(names))\n"
            "if count == int(os.environ.get('TMUX_SIGNAL_AT', '0')):\n"
            "    os.kill(os.getppid(), signal.SIGTERM)\n"
        )
        tmux.chmod(0o755)
        state = self.directory / "state"
        count = self.directory / "count"
        original = ["10", "named-session", "0", "2"]
        environment = os.environ | {
            "PATH": f"{self.directory}:{os.environ['PATH']}",
            "TMUX_STATE": str(state),
            "TMUX_COUNT": str(count),
        }

        for fail_at in range(1, 7):
            with self.subTest(fail_at=fail_at):
                state.write_text(json.dumps(original))
                count.write_text("0")
                result = subprocess.run(
                    [str(ROOT / "libexec/tmux/renumber-tmux-sessions.sh")],
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    env=environment | {"TMUX_FAIL_AT": str(fail_at)},
                )
                self.assertEqual(27, result.returncode, result.stderr)
                self.assertEqual(set(original), set(json.loads(state.read_text())))

        state.write_text(json.dumps(original))
        count.write_text("0")
        result = subprocess.run(
            [str(ROOT / "libexec/tmux/renumber-tmux-sessions.sh")],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=environment | {"TMUX_SIGNAL_AT": "2"},
        )
        self.assertEqual(128 + signal.SIGTERM, result.returncode, result.stderr)
        self.assertEqual(set(original), set(json.loads(state.read_text())))

        state.write_text(json.dumps(original))
        count.write_text("0")
        result = subprocess.run(
            [str(ROOT / "libexec/tmux/renumber-tmux-sessions.sh")],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=environment,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual({"1", "2", "3", "named-session"}, set(json.loads(state.read_text())))

        state.write_text(json.dumps(original))
        count.write_text("0")
        result = subprocess.run(
            [str(ROOT / "libexec/tmux/renumber-tmux-sessions.sh")],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=environment | {"TMUX_FAIL_AT": "4,5"},
        )
        self.assertEqual(27, result.returncode)
        self.assertIn("during rollback", result.stderr)


if __name__ == "__main__":
    unittest.main()
