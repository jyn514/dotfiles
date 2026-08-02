#!/usr/bin/env python3

import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
FINGERPRINT = "3FEF9748469ADBE15DA7CA80AC2D62742012EA22"


class OnePasswordArchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name)
        self.bin = self.directory / "bin"
        self.bin.mkdir()
        self.log = self.directory / "commands"
        recorder = self.bin / "recorder"
        recorder.write_text(
            "#!/bin/sh\n"
            'printf "%s" "${0##*/}" >> "$COMMAND_LOG"\n'
            'for arg do printf " <%s>" "$arg" >> "$COMMAND_LOG"; done\n'
            'printf "\\n" >> "$COMMAND_LOG"\n'
        )
        recorder.chmod(0o755)
        for command in ("curl", "makepkg"):
            (self.bin / command).symlink_to(recorder)

        git = self.bin / "git"
        git.write_text(
            "#!/bin/sh\n"
            'printf "git" >> "$COMMAND_LOG"\n'
            'for arg do printf " <%s>" "$arg" >> "$COMMAND_LOG"; done\n'
            'printf "\\n" >> "$COMMAND_LOG"\n'
            'eval "destination=\\${$#}"\n'
            'mkdir -p "$destination"\n'
            f'printf "validpgpkeys=(\'{FINGERPRINT}\')\\n" > "$destination/PKGBUILD"\n'
        )
        git.chmod(0o755)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def run_installer(self, fingerprint: str) -> subprocess.CompletedProcess[str]:
        gpg = self.bin / "gpg"
        gpg.write_text(
            "#!/bin/sh\n"
            'printf "gpg" >> "$COMMAND_LOG"\n'
            'for arg do printf " <%s>" "$arg" >> "$COMMAND_LOG"; done\n'
            'printf "\\n" >> "$COMMAND_LOG"\n'
            'case "$*" in *--show-keys*) '
            f"printf 'fpr:::::::::{fingerprint}:\\n'"
            ";; esac\n"
        )
        gpg.chmod(0o755)
        env = os.environ.copy()
        env.update(
            COMMAND_LOG=str(self.log),
            PATH=f"{self.bin}:{env['PATH']}",
            TMPDIR=str(self.directory),
        )
        return subprocess.run(
            ["sh", "lib/install_1password_arch.sh"],
            cwd=ROOT,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )

    def commands(self) -> str:
        return self.log.read_text() if self.log.exists() else ""

    def test_verifies_key_and_pkgbuild_before_building(self) -> None:
        result = self.run_installer(FINGERPRINT)

        self.assertEqual(0, result.returncode, result.stderr)
        commands = self.commands()
        self.assertIn("gpg <--batch> <--show-keys> <--with-colons>", commands)
        self.assertIn("<--import>", commands)
        self.assertIn("git <clone> <--quiet> <--depth=1>", commands)
        self.assertIn("makepkg <--syncdeps> <--install> <--needed>", commands)
        self.assertLess(commands.index("<--import>"), commands.index("git <clone>"))

    def test_rejects_an_unexpected_key_before_import_or_clone(self) -> None:
        result = self.run_installer("0" * 40)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("fingerprint mismatch", result.stderr)
        self.assertNotIn("<--import>", self.commands())
        self.assertNotIn("git <clone>", self.commands())


if __name__ == "__main__":
    unittest.main()
