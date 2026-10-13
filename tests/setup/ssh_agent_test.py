"""Fish selects a reachable local agent without replacing remote credentials."""

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]


@unittest.skipUnless(shutil.which("fish"), "fish is required")
class AgentTests(unittest.TestCase):
    def test_agent_selection(self):
        # Exit 2 alone means unreachable; exit 1 is a reachable empty agent.
        cases = [
            ("local", "old", 2, 0, "fallback"),
            ("local", "old", 2, 1, "fallback"),
            ("local", "old", 2, 2, "old"),
            ("local", "old", 0, 0, "old"),
            ("local", "old", 1, 0, "old"),
            ("local", "", 2, 0, "fallback"),
            ("remote", "old", 2, 0, "old"),
            ("remote", "", 2, 0, ""),
            ("tmux-local", "old", 2, 0, "fallback"),
            ("tmux-remote", "old", 2, 0, "old"),
            ("tmux-unknown", "old", 2, 0, "old"),
        ]
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            commands = home / "bin"
            commands.mkdir()
            for name, body in {
                "ssh-add": 'if [ "$SSH_AUTH_SOCK" = old ]; then exit "$OLD_STATUS"; fi\nexit "$LOCAL_STATUS"\n',
                "python3": 'exit "$SOURCE_STATUS"\n',
                "uname": 'printf "%s\\n" "$TEST_KERNEL"\n',
            }.items():
                path = commands / name
                path.write_text("#!/bin/sh\n" + body)
                path.chmod(0o755)
            probe = home / "probe.fish"
            probe.write_text(
                'source "$DOTFILES/lib/shell/ssh-agent.fish"\n'
                'printf "%s" "$SSH_AUTH_SOCK"\n'
            )
            for kernel in ("Linux", "Darwin"):
                fallback = str(home / (".1password/agent.sock" if kernel == "Linux" else
                    "Library/Group Containers/2BUA8C4S2C.com.1password/t/agent.sock"))
                for source, old, old_status, local_status, expected in cases:
                    with self.subTest(kernel=kernel, source=source, old=old,
                                      old_status=old_status, local_status=local_status):
                        env = dict(os.environ, HOME=directory, DOTFILES=str(ROOT),
                                   PATH=str(commands) + os.pathsep + os.environ["PATH"],
                                   SSH_AUTH_SOCK=old, TEST_KERNEL=kernel,
                                   OLD_STATUS=str(old_status), LOCAL_STATUS=str(local_status),
                                   SOURCE_STATUS="0" if source == "tmux-local" else "1")
                        for name in ("TMUX", "TMUX_PANE", "SSH_CONNECTION", "SSH_TTY", "SSH_CLIENT"):
                            env.pop(name, None)
                        if source != "local":
                            env["SSH_CONNECTION"] = "stale connection metadata"
                        if source.startswith("tmux-"):
                            env["TMUX"] = "/unused,1,0"
                            env["TMUX_PANE"] = "%1"
                        result = subprocess.run(["fish", "--no-config", str(probe)],
                                                env=env, capture_output=True, text=True, check=True)
                        self.assertEqual(result.stdout, fallback if expected == "fallback" else expected)
                        self.assertEqual(result.stderr, "")


if __name__ == "__main__":
    unittest.main()
