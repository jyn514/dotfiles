"""Exact Pi resumes through the configured hook and tmux-resurrect consumer."""

import base64
import json
import os
from pathlib import Path
import runpy
import shlex
import shutil
import subprocess
import tempfile
import time
import unittest


ROOT = Path(__file__).resolve().parents[2]
HOOK = ROOT / "config/tmux/resurrect-pi.py"
rewrite = runpy.run_path(str(HOOK))["rewrite"]


def registration(pid, session, cwd):
    return base64.urlsafe_b64encode(json.dumps({"version": 1, "pid": pid,
        "session": str(session) if session else None, "cwd": str(cwd)}).encode()).decode()


def pane(index, command):
    return f"pane\twork\t0\t1\t:*\t{index}\tPi\t:/original\t1\tpython3\t:{command}\n"


class SaveTests(unittest.TestCase):
    def test_only_live_saved_attachments_replace_commands(self):
        with tempfile.TemporaryDirectory() as directory:
            cwd = Path(directory)
            session = cwd / "selected.jsonl"
            session.write_text('{"type":"session"}\n')
            original = pane(0, "sandbox-host-pi --session-id launch-id") + "state\twork\t\n"
            for label, pid, selected, parents, expected in (
                ("pane root", 10, session, {10: 1}, True),
                ("child UI", 11, session, {11: 10, 10: 1}, True),
                ("stale other pane", 11, session, {11: 20, 10: 1, 20: 1}, False),
                ("exited UI", 11, session, {10: 1}, False),
                ("ephemeral", 11, None, {11: 10, 10: 1}, False),
                ("not yet persisted", 11, cwd / "missing.jsonl", {11: 10, 10: 1}, False),
            ):
                with self.subTest(label=label):
                    panes = "work\t0\t0\t10\t" + registration(pid, selected, cwd) + "\n"
                    result = rewrite(original, panes, parents)
                    if expected:
                        self.assertEqual(shlex.split(result.splitlines()[0].split("\t")[10][1:]),
                            ["pi", "--session", str(session), "--session-dir", str(cwd)])
                        self.assertTrue(result.endswith("state\twork\t\n"))
                    else:
                        self.assertEqual(result, original)

    def test_invalid_metadata_does_not_break_other_panes_or_change_unrelated_rows(self):
        with tempfile.TemporaryDirectory() as directory:
            cwd = Path(directory)
            session = cwd / "selected.jsonl"
            session.touch()
            original = pane(0, "old Pi") + pane(1, "another Pi") + pane(2, "hx notes.txt")
            panes = ("work\t0\t0\t10\tinvalid!\nwork\t0\t1\t20\t"
                + registration(20, session, cwd) + "\nwork\t0\t2\t30\t\n")
            result = rewrite(original, panes, {10: 1, 20: 1, 30: 1})
            self.assertEqual(result.splitlines()[0], original.splitlines()[0])
            self.assertIn(":pi --session", result.splitlines()[1])
            self.assertEqual(result.splitlines()[2], original.splitlines()[2])


PLUGIN = os.environ.get("TMUX_RESURRECT_PLUGIN")


@unittest.skipUnless(PLUGIN and shutil.which("tmux"),
    "set TMUX_RESURRECT_PLUGIN to an installed tmux-resurrect checkout for native restore testing")
class ResurrectTests(unittest.TestCase):
    def test_plugin_saves_and_restores_split_sessions_with_quoted_paths_idempotently(self):
        with tempfile.TemporaryDirectory(prefix="pi-resurrect-") as directory:
            root = Path(directory)
            cwd = root / "workspace with spaces 'and quotes'"
            cwd.mkdir()
            storage = root / "custom sessions"
            storage.mkdir()
            session = storage / "selected 'conversation'; $(touch injected).jsonl"
            session.write_text(json.dumps({"type": "session", "version": 3,
                "id": "selected-conversation", "cwd": str(cwd)}) + "\n")
            split_session = storage / "split-conversation.jsonl"
            split_session.write_text(json.dumps({"type": "session", "version": 3,
                "id": "split-conversation", "cwd": str(cwd)}) + "\n")
            bin_dir = root / "bin"
            bin_dir.mkdir()
            records = root / "restored.jsonl"
            fixture = bin_dir / "pi"
            fixture.write_text("#!/usr/bin/env python3\nimport json, os, sys, time\n"
                "with open(os.environ['RESTORED_RECORDS'], 'a') as out:\n"
                "    out.write(json.dumps({'argv':sys.argv[1:], 'cwd':os.getcwd()}) + '\\n')\n"
                "time.sleep(60)\n")
            fixture.chmod(0o700)
            config_dir = root / ".config/tmux"
            config_dir.mkdir(parents=True)
            (config_dir / "resurrect-pi.py").symlink_to(HOOK)
            save_dir = root / "resurrect"
            socket = str(root / "tmux.sock")
            environment = {**os.environ, "HOME": str(root), "TERM": "xterm-256color",
                "PATH": str(bin_dir) + os.pathsep + os.environ["PATH"], "RESTORED_RECORDS": str(records)}
            environment.pop("TMUX", None)
            environment.pop("TMUX_PANE", None)

            def tmux(*args, check=True):
                result = subprocess.run(["tmux", "-S", socket, *args], env=environment,
                    capture_output=True, text=True, timeout=10)
                if check:
                    self.assertEqual(result.returncode, 0, f"{args!r}: {result.stderr}")
                return result

            def configure():
                # Exercise the production config lines through tmux's parser.
                lines = [line for line in (ROOT / "config/tmux/tmux.conf").read_text().splitlines()
                    if line.startswith(("set -g @resurrect-processes ", "set -g @resurrect-hook-post-save-layout "))]
                config = root / "restore.conf"
                config.write_text("\n".join(lines) + "\n")
                tmux("source-file", str(config))
                self.assertEqual(tmux("show-option", "-gv", "@resurrect-hook-post-save-layout").stdout.strip(),
                    'python3 "$HOME/.config/tmux/resurrect-pi.py"')
                tmux("set-option", "-g", "@resurrect-dir", str(save_dir))
                tmux("set-option", "-g", "@resurrect-save-command-strategy", "ps")
                shell = shutil.which("fish") or "/bin/bash"
                tmux("set-option", "-g", "default-shell", shell)
                if Path(shell).name == "fish":
                    # System Fish startup generates completions in the background.
                    # Exercise Fish quoting without launching those unrelated jobs.
                    tmux("set-option", "-g", "default-command", shlex.join(["exec", shell, "--no-config"]))

            def plugin_script(name):
                tmux_env = tmux("display-message", "-p", "#{socket_path},#{pid},0").stdout.strip()
                result = subprocess.run(["bash", str(Path(PLUGIN) / "scripts" / name)],
                    env={**environment, "TMUX": tmux_env}, capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, 0, result.stderr + result.stdout)

            try:
                first = tmux("-f", "/dev/null", "new-session", "-d", "-s", "work",
                    "-c", str(cwd), "-P", "-F", "#{pane_id}", "sleep 300").stdout.strip()
                second = tmux("split-window", "-d", "-t", first, "-c", str(cwd),
                    "-P", "-F", "#{pane_id}", "sleep 300").stdout.strip()
                configure()
                for target, selected in ((first, session), (second, split_session)):
                    pid = int(tmux("display-message", "-p", "-t", target, "#{pane_pid}").stdout)
                    tmux("set-option", "-p", "-t", target, "@resurrect_pi_session", registration(pid, selected, cwd))
                plugin_script("save.sh")
                saved = (save_dir / "last").read_text()
                self.assertEqual(saved.count(":pi --session "), 2)
                self.assertNotIn("--session-id", saved)
                tmux("kill-server")
                # Restoration must work on a new server, independently of the
                # original server's socket and asynchronous shutdown.
                socket = str(root / "restored.sock")
                tmux("-f", "/dev/null", "new-session", "-d", "-s", "seed", "sleep 300")
                configure()
                plugin_script("restore.sh")
                deadline = time.monotonic() + 10
                while time.monotonic() < deadline:
                    restored = [json.loads(line) for line in records.read_text().splitlines()] if records.exists() else []
                    if len(restored) >= 2:
                        break
                    time.sleep(.1)
                self.assertCountEqual(restored, [{"argv": ["--session", str(selected), "--session-dir", str(storage)],
                    "cwd": str(cwd)} for selected in (session, split_session)])
                self.assertFalse((cwd / "injected").exists())
                plugin_script("restore.sh")
                self.assertEqual(len(records.read_text().splitlines()), 2)
                self.assertEqual(json.loads(session.read_text())["id"], "selected-conversation")
            finally:
                tmux("kill-server", check=False)


if __name__ == "__main__":
    unittest.main()
