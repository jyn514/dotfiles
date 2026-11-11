"""Native setup functions with recorded privileged effects and a real tty."""
import fcntl
import json
import os
from pathlib import Path
import pty
import select
import subprocess
import sys
import tempfile
import termios
import unittest


ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests/setup/fixtures"
SCRIPT = ROOT / "libexec/setup/setup_sudo.sh"


class SetupSudoTests(unittest.TestCase):
    def setUp(self):
        self.directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.log = self.directory / "commands.jsonl"
        self.home = self.directory / "home [ab]* with spaces"
        self.user = "fixture user [ab]*"
        self.device = "/dev/fixture device"
        self.environment = os.environ | {
            "FIXTURE_PYTHON": sys.executable,
            "FIXTURE_RECORDER": str(FIXTURES / "setup_sudo_recorder.py"),
            "SETUP_SUDO_FIXTURE": str(FIXTURES / "setup_sudo_harness.sh"),
            "FIXTURE_LOG": str(self.log),
            "FIXTURE_HOME": str(self.home),
            "FIXTURE_USER": self.user,
            "FIXTURE_DEVICE": self.device,
        }

    def command(self, mode):
        return ["sh", "-c", '. "$SETUP_SUDO_FIXTURE"', str(SCRIPT), mode]

    def run_prompt(self, name, destination, reply, source=None):
        environment = self.environment | {
            "FIXTURE_NAME": name,
            "FIXTURE_DEST": str(destination),
        }
        if source is not None:
            environment["FIXTURE_SOURCE"] = str(source)
        return subprocess.run(
            self.command("prompt"), cwd=ROOT, env=environment,
            input=reply, text=True, capture_output=True, timeout=10,
        )

    def run_encryption(self, reply, *, mode="encrypt", simple_paths=False):
        if simple_paths:
            self.home = self.directory / "home"
            self.user = "fixture-user"
            self.environment.update(FIXTURE_HOME=str(self.home), FIXTURE_USER=self.user)
        master, slave = pty.openpty()
        self.addCleanup(os.close, master)
        self.addCleanup(os.close, slave)

        def terminal_owner():
            os.setsid()
            fcntl.ioctl(slave, termios.TIOCSCTTY, 0)

        process = subprocess.Popen(
            self.command(mode), cwd=ROOT, env=self.environment,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            preexec_fn=terminal_owner,
        )
        try:
            stdout, stderr = process.communicate(reply, timeout=10)
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate()
        self.assertEqual(0, process.returncode, stderr.decode())
        self.assertEqual(b"", stdout)
        self.assertTrue(select.select([master], [], [], 1)[0], "no /dev/tty prompt")
        self.assertEqual(
            b"setup encrypted home drive; delete backup? [y/N]\r\n",
            os.read(master, 4096),
        )
        return stderr.decode()

    def run_pcscd(self, mode):
        return subprocess.run(
            self.command(mode), cwd=ROOT, env=self.environment,
            text=True, capture_output=True, timeout=10,
        )

    def run_reload(self, mode):
        return subprocess.run(
            self.command(mode), cwd=ROOT, env=self.environment,
            text=True, capture_output=True, timeout=10,
        )

    def commands(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()]

    def expected_commands(self, delete=False):
        home = str(self.home)
        backup = home + ".bak"
        commands = [
            ["fscrypt", "status", home],
            ["df", home, "--output=source"],
            ["dumpe2fs", "-h", self.device],
            ["tune2fs", "-O", "encrypt", self.device],
            ["fscrypt", "setup", "--all-users"],
            ["setup_fscrypt_profile"],
            ["mv", home, backup],
            ["mkdir", home],
            ["chown", f"{self.user}:{self.user}", home],
            ["fscrypt", "encrypt", "--source=pam_passphrase", f"--user={self.user}", home],
            ["rsync", "-azAHX", "--info=progress2", backup + "/", home],
        ]
        if delete:
            commands.append(["rm", "-rf", backup])
        return commands

    def test_percent_and_backslash_names_are_literal_in_install_prompt(self):
        name = r"config %s\name"
        destination = self.directory / r"destination %s\name"
        for reply, status in (("y\n", 0), ("n\n", 1)):
            with self.subTest(reply=reply):
                result = self.run_prompt(name, destination, reply)
                self.assertEqual(status, result.returncode, result.stderr)
                expected = f"confirm: install ./global/{name} to {destination}? [y/N] "
                if status:
                    expected += "ok, skipping\n"
                self.assertEqual(expected, result.stdout)
                self.assertFalse(destination.exists())

    def test_matching_unmanaged_global_is_already_installed(self):
        source = self.directory / "source.conf"
        source.write_text("tracked configuration\n")
        destination = self.directory / "destination.conf"
        destination.write_text("tracked configuration\n")

        result = self.run_prompt("source.conf", destination, "n\n", source)

        self.assertEqual(1, result.returncode, result.stderr)
        self.assertEqual(
            f"ok, already installed: {destination}\n",
            result.stdout,
        )

    def test_matching_generated_global_is_already_installed(self):
        source = self.directory / "source.conf"
        source.write_text("tracked configuration\n")
        destination = self.directory / "destination.conf"
        destination.write_text(
            "# Generated by /repo/libexec/setup/setup_sudo.sh vfixture from ./global/source.conf at 2026-11-11 12:00:00\n"
            "tracked configuration\n"
        )

        result = self.run_prompt("source.conf", destination, "n\n", source)

        self.assertEqual(1, result.returncode, result.stderr)
        self.assertEqual(
            f"ok, already installed: {destination}\n",
            result.stdout,
        )

    def test_changed_generated_global_still_reaches_install_prompt(self):
        source = self.directory / "source.conf"
        source.write_text("new configuration\n")
        destination = self.directory / "destination.conf"
        destination.write_text(
            "# Generated by /repo/libexec/setup/setup_sudo.sh vfixture from ./global/source.conf at 2026-11-11 12:00:00\n"
            "old configuration\n"
        )

        result = self.run_prompt("source.conf", destination, "n\n", source)

        self.assertEqual(1, result.returncode, result.stderr)
        self.assertEqual(
            f"confirm: install ./global/source.conf to {destination}? [y/N] ok, skipping\n",
            result.stdout,
        )

    def test_matching_generated_script_is_already_installed(self):
        source = self.directory / "source.sh"
        source.write_text("#!/bin/sh\nprintf 'tracked\\n'\n")
        destination = self.directory / "destination.sh"
        destination.write_text(
            "#!/bin/sh\n"
            "# Generated by /repo/libexec/setup/setup_sudo.sh vfixture from ./global/source.sh at 2026-11-11 12:00:00\n"
            "printf 'tracked\\n'\n"
        )

        result = self.run_prompt("source.sh", destination, "n\n", source)

        self.assertEqual(1, result.returncode, result.stderr)
        self.assertEqual(
            f"ok, already installed: {destination}\n",
            result.stdout,
        )

    def test_different_unmanaged_global_is_still_refused(self):
        source = self.directory / "source.conf"
        source.write_text("tracked configuration\n")
        destination = self.directory / "destination.conf"
        destination.write_text("local configuration\n")

        result = self.run_prompt("source.conf", destination, "", source)

        self.assertEqual(1, result.returncode, result.stderr)
        self.assertEqual(
            f"error: {destination} already exists, refusing to overwrite\n",
            result.stdout,
        )

    def test_pcscd_setup_prefers_socket_activation(self):
        result = self.run_pcscd("pcscd-socket")

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn(
            ["systemctl", "enable", "--now", "pcscd.socket"],
            self.commands(),
        )
        self.assertNotIn(
            ["systemctl", "enable", "--now", "pcscd.service"],
            self.commands(),
        )

    def test_pcscd_setup_falls_back_to_the_service(self):
        result = self.run_pcscd("pcscd-service")

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn(
            ["systemctl", "enable", "--now", "pcscd.service"],
            self.commands(),
        )
        self.assertNotIn(
            ["systemctl", "enable", "--now", "pcscd.socket"],
            self.commands(),
        )

    def test_global_copy_reloads_systemd_when_available(self):
        result = self.run_reload("reload-systemd")

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual([["systemctl", "daemon-reload"]], self.commands())

    def test_global_copy_skips_systemd_reload_when_unavailable(self):
        result = self.run_reload("reload-no-systemd")

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertFalse(self.log.exists())

    def test_affirmative_reply_preserves_migration_argv_and_deletes_only_backup(self):
        stderr = self.run_encryption(b"y\n")
        self.assertEqual(self.expected_commands(delete=True), self.commands())
        self.assertEqual("deleting\n", stderr)

    def test_negative_reply_preserves_migration_argv_and_retains_backup(self):
        stderr = self.run_encryption(b"n\n")
        self.assertEqual(self.expected_commands(), self.commands())
        self.assertEqual(f"retaining backup in {self.home}.bak\n", stderr)

    def test_backslash_reply_is_not_an_affirmative(self):
        stderr = self.run_encryption(b"\\y\n", simple_paths=True)
        self.assertEqual(self.expected_commands(), self.commands())
        self.assertEqual(f"retaining backup in {self.home}.bak\n", stderr)

    def test_failed_read_cannot_reuse_an_old_affirmative(self):
        stderr = self.run_encryption(b"", mode="failed-read", simple_paths=True)
        self.assertEqual(self.expected_commands(), self.commands())
        self.assertEqual(f"retaining backup in {self.home}.bak\n", stderr)


if __name__ == "__main__":
    unittest.main()
