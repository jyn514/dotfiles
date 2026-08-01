#!/usr/bin/env python3

import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class ProfileContractTests(unittest.TestCase):
    def test_interactive_shells_activate_mise(self) -> None:
        profile = (ROOT / "config/profile").read_text()

        self.assertIn('eval "$(mise activate bash)"', profile)
        self.assertIn('eval "$(mise activate zsh)"', profile)

    def test_mise_shims_are_added_after_linuxbrew(self) -> None:
        profile = (ROOT / "config/profile").read_text()

        self.assertLess(
            profile.index("linuxbrew/.linuxbrew/bin/brew shellenv"),
            profile.index('. "$DOTFILES/lib/paths.sh"'),
        )

    def test_noninteractive_profile_exposes_tool_and_dotfile_paths_once(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "home"
            home.mkdir()
            (home / ".profile").symlink_to(ROOT / "config/profile")
            cargo_bin = home / ".local/lib/cargo/bin"
            local_bin = home / ".local/bin"
            mise_shims = home / ".local/share/mise/shims"
            cargo_bin.mkdir(parents=True)
            local_bin.mkdir(parents=True)
            mise_shims.mkdir(parents=True)
            env = os.environ.copy()
            env.update(
                HOME=str(home),
                PATH=f"{local_bin}:/usr/bin:{local_bin}",
                SSH_AUTH_SOCK="",
            )

            result = subprocess.run(
                [
                    "/bin/sh",
                    "-c",
                    '. "$HOME/.profile"; printf "%s\\n" "$PATH"',
                ],
                cwd=ROOT,
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(0, result.returncode, result.stderr)
            paths = result.stdout.strip().split(":")
            expected_prefix = [
                str(mise_shims),
                str(ROOT / "bin"),
                str(local_bin),
                str(cargo_bin),
            ]
            self.assertEqual(expected_prefix, paths[: len(expected_prefix)])
            self.assertEqual(1, paths.count(str(local_bin)))
            self.assertEqual(1, paths.count(str(cargo_bin)))
            self.assertEqual(1, paths.count(str(mise_shims)))


if __name__ == "__main__":
    unittest.main()
