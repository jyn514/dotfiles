"""Fish selects a local agent without querying agents or replacing supplied credentials."""

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
        cases = [
            ("local", "old", "old"),
            ("local", "", "fallback"),
            ("remote", "old", "old"),
            ("remote", "", ""),
            ("tmux-local", "old", "old"),
            ("tmux-local", "", "fallback"),
            ("tmux-remote", "old", "old"),
            ("tmux-remote", "", ""),
            ("tmux-unknown", "old", "old"),
            ("tmux-unknown", "", ""),
        ]
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            commands = home / "bin"
            commands.mkdir()
            for name, body in {
                "ssh-add": 'touch "$HOME/agent-queried"\nexit 2\n',
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
                for source, old, expected in cases:
                    with self.subTest(kernel=kernel, source=source, old=old):
                        env = dict(os.environ, HOME=directory, DOTFILES=str(ROOT),
                                   PATH=str(commands) + os.pathsep + os.environ["PATH"],
                                   SSH_AUTH_SOCK=old, TEST_KERNEL=kernel,
                                   SOURCE_STATUS="0" if source == "tmux-local" else "1")
                        for name in ("TMUX", "TMUX_PANE", "SSH_CONNECTION", "SSH_TTY", "SSH_CLIENT"):
                            env.pop(name, None)
                        if source != "local":
                            env["SSH_CONNECTION"] = "stale connection metadata"
                        if source.startswith("tmux-"):
                            env["TMUX"] = "/unused,1,0"
                            env["TMUX_PANE"] = "%1"
                        result = subprocess.run(["fish", "--no-config", str(probe)],
                                                env=env, capture_output=True, text=True, check=True,
                                                timeout=5)
                        self.assertEqual(result.stdout, fallback if expected == "fallback" else expected)
                        self.assertEqual(result.stderr, "")
                        self.assertFalse((home / "agent-queried").exists(),
                                         "shell startup must not query an agent")


if __name__ == "__main__":
    unittest.main()
