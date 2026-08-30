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

    def test_set_tmux_env_preserves_whitespace_and_equals(self) -> None:
        calls = self.directory / "tmux-calls"
        (self.directory / ".profile").write_text(
            "unset CARGO_HOME RUSTUP_HOME\n"
            "EDITOR='editor\n--wait'\n"
            "VISUAL=''\n"
            "PATH='/one path:/two=parts'\n"
            "export EDITOR VISUAL PATH\n"
        )
        self.executable(
            "tmux",
            'printf "%s\\0%s\\0%s\\0%s\\0%s\\0%s\\0" '
            f'"$1" "$2" "$3" "${{4-}}" "$TMUX" "$TMUX_TMPDIR" >> "{calls}"\n',
        )

        result = subprocess.run(
            [str(ROOT / "libexec/tmux/set-tmux-env.sh")],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=os.environ | {
                "PATH": f"{self.directory}:{os.environ['PATH']}",
                "HOME": str(self.directory),
                "TMUX": "socket value",
                "TMUX_TMPDIR": "/socket directory",
            },
        )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(
            b"set-environment\0-g\0EDITOR\0editor\n--wait\0"
            b"socket value\0/socket directory\0"
            b"set-environment\0-g\0VISUAL\0\0"
            b"socket value\0/socket directory\0"
            b"set-environment\0-g\0PATH\0/one path:/two=parts\0"
            b"socket value\0/socket directory\0"
            b"set-environment\0-gu\0CARGO_HOME\0\0"
            b"socket value\0/socket directory\0"
            b"set-environment\0-gu\0RUSTUP_HOME\0\0"
            b"socket value\0/socket directory\0",
            calls.read_bytes(),
        )
    def test_set_tmux_env_finds_tmux_added_by_profile(self) -> None:
        calls = self.directory / "tmux-calls"
        bootstrap_bin = self.directory / "bootstrap-bin"
        profile_bin = self.directory / "profile-bin"
        bootstrap_bin.mkdir()
        profile_bin.mkdir()
        for command in ("bash", "env"):
            executable = shutil.which(command)
            if executable is None:
                self.skipTest(f"{command} is unavailable")
            (bootstrap_bin / command).symlink_to(executable)
        tmux = profile_bin / "tmux"
        tmux.write_text(
            "#!/bin/sh\n"
            f'printf "%s\\n" "$*" >> "{calls}"\n'
        )
        tmux.chmod(0o755)
        (self.directory / ".profile").write_text(
            f'PATH="{profile_bin}"\n'
            "export PATH\n"
            "unset EDITOR VISUAL CARGO_HOME RUSTUP_HOME\n"
        )

        result = subprocess.run(
            [str(ROOT / "libexec/tmux/set-tmux-env.sh")],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=os.environ
            | {
                "HOME": str(self.directory),
                "PATH": str(bootstrap_bin),
            },
        )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(
            [
                "set-environment -gu EDITOR",
                "set-environment -gu VISUAL",
                f"set-environment -g PATH {profile_bin}",
                "set-environment -gu CARGO_HOME",
                "set-environment -gu RUSTUP_HOME",
            ],
            calls.read_text().splitlines(),
        )
    def test_set_tmux_env_preserves_unset_and_empty_tmux_context(self) -> None:
        calls = self.directory / "tmux-context"
        (self.directory / ".profile").write_text(
            "unset EDITOR VISUAL CARGO_HOME RUSTUP_HOME\n"
        )
        self.executable(
            "tmux",
            'if [ "${TMUX+x}" ]; then tmux="set:$TMUX"; else tmux=unset; fi\n'
            'if [ "${TMUX_TMPDIR+x}" ]; then tmp="set:$TMUX_TMPDIR"; else tmp=unset; fi\n'
            f'printf "%s %s\\n" "$tmux" "$tmp" >> "{calls}"\n',
        )
        environment = os.environ | {
            "HOME": str(self.directory),
            "PATH": f"{self.directory}:{os.environ['PATH']}",
            "TMUX_CALLS": str(calls),
        }
        environment.pop("TMUX", None)
        environment.pop("TMUX_TMPDIR", None)

        unset = subprocess.run(
            [str(ROOT / "libexec/tmux/set-tmux-env.sh")],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=environment,
        )
        empty = subprocess.run(
            [str(ROOT / "libexec/tmux/set-tmux-env.sh")],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=environment | {"TMUX": "", "TMUX_TMPDIR": ""},
        )

        self.assertEqual(0, unset.returncode, unset.stderr)
        self.assertEqual(0, empty.returncode, empty.stderr)
        self.assertEqual(
            ["unset unset"] * 5 + ["set: set:"] * 5,
            calls.read_text().splitlines(),
        )
    def test_set_tmux_env_stops_after_tmux_failure(self) -> None:
        calls = self.directory / "tmux-calls"
        (self.directory / ".profile").write_text(
            "EDITOR=editor VISUAL=visual PATH=/profile/path\n"
            "export EDITOR VISUAL PATH\n"
            "unset CARGO_HOME RUSTUP_HOME\n"
        )
        self.executable(
            "tmux",
            f'printf "%s\\n" "$*" >> "{calls}"\n'
            '[ "$3" = VISUAL ] && exit 29\n'
            'exit 0\n',
        )

        result = subprocess.run(
            [str(ROOT / "libexec/tmux/set-tmux-env.sh")],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=os.environ | {
                "HOME": str(self.directory),
                "PATH": f"{self.directory}:{os.environ['PATH']}",
                "TMUX_CALLS": str(calls),
            },
        )

        self.assertEqual(29, result.returncode)
        self.assertEqual(
            ["set-environment -g EDITOR editor", "set-environment -g VISUAL visual"],
            calls.read_text().splitlines(),
        )
    def test_set_tmux_env_propagates_profile_failure(self) -> None:
        calls = self.directory / "tmux-calls"
        (self.directory / ".profile").write_text("return 17\n")
        self.executable("tmux", 'printf "%s\\n" "$*" > "$TMUX_CALLS"\n')

        result = subprocess.run(
            [str(ROOT / "libexec/tmux/set-tmux-env.sh")],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=os.environ | {
                "PATH": f"{self.directory}:{os.environ['PATH']}",
                "HOME": str(self.directory),
                "TMUX_CALLS": str(calls),
            },
        )

        self.assertEqual(17, result.returncode)
        self.assertFalse(calls.exists())


if __name__ == "__main__":
    unittest.main()
