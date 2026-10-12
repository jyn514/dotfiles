import fcntl
import os
from pathlib import Path
import pty
import select
import shlex
import shutil
import subprocess
import sys
import tempfile
import termios
import time
import unittest


ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / "libexec/tmux/default-colors.py"
NATIVE = shutil.which("tmux", path=os.pathsep.join(
    entry for entry in os.get_exec_path() if Path(entry).resolve() != ROOT / "bin"))


@unittest.skipUnless(NATIVE, "tmux is required")
class DefaultColorsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.command = [NATIVE, "-S", str(self.directory / "socket")]
        self.input_file = self.directory / "typed"
        # A real pane consumes replayed typeahead without executing it.
        reader = self.directory / "reader.py"
        reader.write_text(
            "import sys, time\n"
            "line = sys.stdin.readline()\n"
            f"open({str(self.input_file)!r}, 'w').write(line)\n"
            "time.sleep(30)\n"
        )
        self.run_tmux("-f", "/dev/null", "new-session", "-d", "-s", "colors",
                      shlex.join([sys.executable, str(reader)]))
        self.addCleanup(self.stop_server)
        self.pane = self.run_tmux("display-message", "-p", "#{pane_id}").strip()
        self.environment = os.environ | {
            "TMUX": self.run_tmux("display-message", "-p", "#{socket_path},#{pid},0").strip(),
            "TMUX_PANE": self.pane,
        }

    def stop_server(self) -> None:
        subprocess.run([*self.command, "kill-server"], capture_output=True, check=False)

    def run_tmux(self, *arguments: str) -> str:
        return subprocess.run([*self.command, *arguments], capture_output=True,
                              text=True, check=True, timeout=3).stdout

    def run_helper(self, replies: list[bytes], environment: dict[str, str] | None = None,
                   terminate: bool = False, helper: Path = HELPER,
                   arguments: list[str] | None = None) -> bytes:
        master, slave = pty.openpty()
        previous = termios.tcgetattr(slave)
        def terminal_owner() -> None:
            os.setsid()
            fcntl.ioctl(0, termios.TIOCSCTTY, 0)
        stderr_log = tempfile.TemporaryFile()
        process = subprocess.Popen(
            arguments or [sys.executable, str(helper)], stdin=slave, stdout=slave,
            stderr=stderr_log, env=environment or self.environment,
            preexec_fn=terminal_owner,
        )
        output = bytearray()
        sent = False
        try:
            deadline = time.monotonic() + (10 if arguments else 3)
            while process.poll() is None and time.monotonic() < deadline:
                if select.select([master], [], [], 0.02)[0]:
                    output.extend(os.read(master, 4096))
                if not sent and b"\x1b]11;?\x07" in output:
                    if terminate:
                        process.terminate()
                    for fragment in replies:
                        os.write(master, fragment)
                        time.sleep(0.005)
                    sent = True
            if process.poll() is None:
                process.kill()
                process.wait()
                stderr_log.seek(0)
                self.fail("startup color probe did not finish: " + stderr_log.read().decode())
            process.wait(timeout=1)
            stderr_log.seek(0)
            stderr = stderr_log.read()
            self.assertEqual(143 if terminate else 0, process.returncode, stderr.decode())
            if arguments is not None:
                self.assertTrue(sent, stderr.decode())
            self.assertEqual(previous, termios.tcgetattr(slave), "terminal settings changed")
            return bytes(output)
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
            os.close(master)
            os.close(slave)
            stderr_log.close()

    def style(self, option: str) -> str:
        return self.run_tmux("show-options", "-pqv", "-t", self.pane, option).strip()

    def test_detected_colors_leave_styles_unchanged(self) -> None:
        self.run_tmux("set-option", "-p", "-t", self.pane, "window-style", "bold")
        self.run_tmux("set-option", "-p", "-t", self.pane, "window-active-style", "underscore")
        self.run_helper([b"\x1b]10;rgb:1234/5678/abcd\x07\x1b]11;rgb:2222/3333/4444\x1b\\"])
        self.assertEqual("bold", self.style("window-style"))
        self.assertEqual("underscore", self.style("window-active-style"))

    def test_missing_colors_are_reported_by_real_tmux(self) -> None:
        # Verify the actual consumer response, rather than just option strings.
        probe = self.directory / "probe.py"
        result = self.directory / "reply"
        probe.write_text(
            "import subprocess, sys\n"
            f"subprocess.run([sys.executable, {str(HELPER)!r}], check=True)\n"
            "import os, select, termios, tty\n"
            "tty.setraw(0)\n"
            "os.write(1, b'\\x1b]10;?\\x07\\x1b]11;?\\x07')\n"
            "data = b''\n"
            "while select.select([0], [], [], 0.3)[0]:\n"
            "    data += os.read(0, 256)\n"
            f"open({str(result)!r}, 'wb').write(data)\n"
        )
        self.run_tmux("respawn-pane", "-k", "-t", self.pane,
                      shlex.join([sys.executable, str(probe)]))
        deadline = time.monotonic() + 3
        while not result.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        self.assertTrue(result.exists(), "consumer probe did not complete")
        self.assertEqual(b"\x1b]10;rgb:cccc/cccc/cccc\x07\x1b]11;rgb:0202/0202/0202\x07",
                         result.read_bytes())

    def test_only_the_missing_color_is_supplied(self) -> None:
        for slot, missing_attribute in ((10, "bg"), (11, "fg")):
            with self.subTest(slot=slot):
                for option in ("window-style", "window-active-style"):
                    self.run_tmux("set-option", "-pu", "-t", self.pane, option)
                self.run_helper([f"\x1b]{slot};rgb:1234/5678/abcd\x07".encode()])
                for option in ("window-style", "window-active-style"):
                    self.assertIn(missing_attribute + "=", self.style(option))
                    self.assertNotIn(("fg" if missing_attribute == "bg" else "bg") + "=",
                                     self.style(option))

    def test_fragmented_replies_preserve_typeahead_and_attributes(self) -> None:
        self.run_tmux("set-option", "-p", "-t", self.pane, "window-style", "bold")
        self.run_helper([b"hello\x1b]10;rgb:cccc/", b"cccc/cccc\x07 world\n"])
        deadline = time.monotonic() + 2
        while not self.input_file.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        self.assertEqual("hello world\n", self.input_file.read_text())
        self.assertIn("bold", self.style("window-style"))
        self.assertIn("bg=#020202", self.style("window-style"))
        self.assertNotIn("fg=", self.style("window-style"))

    def test_outside_tmux_does_not_query_or_set_colors(self) -> None:
        environment = self.environment.copy()
        environment.pop("TMUX")
        self.assertEqual(b"", self.run_helper([], environment))
        self.assertEqual("", self.style("window-style"))

    def test_redirected_stdin_does_not_query_or_set_colors(self) -> None:
        result = subprocess.run([sys.executable, str(HELPER)], input=b"",
                                capture_output=True, env=self.environment, timeout=2)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(b"", result.stdout)
        self.assertEqual("", self.style("window-style"))

    def test_interruption_restores_terminal_without_setting_colors(self) -> None:
        self.run_helper([], terminate=True)
        self.assertEqual("", self.style("window-style"))

    def test_fallback_reads_maintained_theme_values(self) -> None:
        checkout = self.directory / "checkout"
        for relative in ("libexec/tmux/default-colors.py", "libexec/tmux/attachment.py",
                         "config/kitty/campbell.conf"):
            target = checkout / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(["cp", str(ROOT / relative), str(target)], check=True)
            subprocess.run(["cmp", str(ROOT / relative), str(target)], check=True)
        # Change only owned disposable theme data.
        (checkout / "config/kitty/campbell.conf").write_text(
            "foreground #aabbcc\nbackground #112233\n"
        )
        self.run_helper([], helper=checkout / "libexec/tmux/default-colors.py")
        self.assertIn("fg=#aabbcc", self.style("window-style"))
        self.assertIn("bg=#112233", self.style("window-style"))

    def test_interactive_shell_configs_load_the_fallback(self) -> None:
        home = self.directory / "home"
        home.mkdir()
        (home / ".local/share/mise/shims").mkdir(parents=True)
        (home / ".profile").symlink_to(ROOT / "config/profile")
        environment = self.environment | {
            "HOME": str(home), "DOTFILES": str(ROOT), "MY_GITHUB": "configured",
            "FISH_UNIT_TESTS_RUNNING": "1",
            "PATH": str(ROOT / "bin") + os.pathsep + os.environ["PATH"],
        }
        environment.pop("KITTY_INSTALLATION_DIR", None)
        for shell, config, flags in (
            ("bash", "config/bashrc", ["--noprofile", "--norc"]),
            ("zsh", "config/zsh/.zshrc", ["-f"]),
            ("fish", "config/config.fish", ["--no-config"]),
        ):
            with self.subTest(shell=shell):
                executable = shutil.which(shell)
                self.assertIsNotNone(executable, f"{shell} is required")
                for option in ("window-style", "window-active-style"):
                    self.run_tmux("set-option", "-pu", "-t", self.pane, option)
                # Run the real startup file through the probe, then stop before
                # optional plugin setup or toolchain discovery can run.
                python = shlex.quote(sys.executable)
                if shell == "fish":
                    stop_after_probe = (
                        f"function python3; command {python} $argv; "
                        "set -l probe_status $status; "
                        "exec /bin/sh -c 'exit \"$1\"' probe $probe_status; end; "
                    )
                else:
                    stop_after_probe = (
                        f"python3() {{ command {python} \"$@\"; "
                        "probe_status=$?; exec /bin/sh -c 'exit \"$1\"' probe \"$probe_status\"; }; "
                    )
                output = self.run_helper([], environment, arguments=[
                    executable, *flags, "-i", "-c",
                    stop_after_probe + f"source {shlex.quote(str(ROOT / config))}; exit 0",
                ])
                self.assertIn(b"\x1b]10;?\x07\x1b]11;?\x07", output)
                self.assertIn("fg=#cccccc", self.style("window-style"))
                self.assertIn("bg=#020202", self.style("window-active-style"))


if __name__ == "__main__":
    unittest.main()
