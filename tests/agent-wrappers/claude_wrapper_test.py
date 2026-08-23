#!/usr/bin/env python3

import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
WRAPPER = ROOT / "bin/claude"


class ClaudeWrapperTests(unittest.TestCase):
    def run_wrapper(
        self, legacy: str, *, install_settings: bool = True
    ) -> tuple[list[str], Path, dict[str, object], int]:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        home = Path(temporary.name)
        binary_directory = home / "bin"
        binary_directory.mkdir()
        real_claude = binary_directory / "claude"
        real_claude.write_text(
            "#!/usr/bin/env python3\n"
            "import json, sys\n"
            "json.dump(sys.argv[1:], sys.stdout)\n"
        )
        real_claude.chmod(0o755)

        settings = home / ".config/claude/settings.json"
        if install_settings:
            settings.parent.mkdir(parents=True)
            settings.symlink_to(ROOT / "config/claude.json")
        legacy_settings = home / ".claude/settings.json"
        legacy_settings.parent.mkdir(parents=True)
        if legacy == "managed-link":
            legacy_settings.symlink_to(ROOT / "config/claude.json")
        else:
            legacy_settings.write_text(legacy)

        result = subprocess.run(
            [WRAPPER, "prompt"],
            cwd=ROOT,
            env=os.environ
            | {
                "HOME": str(home),
                "PATH": f"{binary_directory}:{os.environ['PATH']}",
            },
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(0, result.returncode, result.stderr)
        arguments = json.loads(result.stdout)
        generated_settings = Path(arguments[1])
        return (
            arguments,
            legacy_settings,
            json.loads(generated_settings.read_text()),
            generated_settings.stat().st_mode & 0o777,
        )

    def test_loads_tracked_settings_with_project_and_local_sources(self) -> None:
        arguments, legacy_settings, settings, mode = self.run_wrapper("managed-link")

        self.assertEqual("--settings", arguments[0])
        self.assertTrue(arguments[1].endswith("/.cache/claude/generated-settings.json"))
        self.assertEqual(["--setting-sources", "project,local"], arguments[2:4])
        self.assertEqual("--system-prompt", arguments[4])
        self.assertEqual("prompt", arguments[-1])
        self.assertIn("Skill(claude-api)", settings["permissions"]["allow"])
        self.assertIn("Bash(jj commit *)", settings["permissions"]["allow"])
        self.assertEqual(0o600, mode)
        self.assertFalse(legacy_settings.exists())

    def test_uses_repository_settings_before_dotfile_setup(self) -> None:
        arguments, legacy_settings, settings, _ = self.run_wrapper(
            "managed-link", install_settings=False
        )

        self.assertTrue(arguments[1].endswith("/.cache/claude/generated-settings.json"))
        self.assertEqual("opus", settings["model"])
        self.assertFalse(legacy_settings.exists())

    def test_preserves_claude_owned_user_settings(self) -> None:
        arguments, legacy_settings, _, _ = self.run_wrapper('{"theme":"dark"}\n')

        self.assertEqual("prompt", arguments[-1])
        self.assertEqual('{"theme":"dark"}\n', legacy_settings.read_text())

    def test_failed_generation_preserves_published_settings(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            binary_directory = home / "bin"
            binary_directory.mkdir()
            marker = home / "claude-ran"
            real_claude = binary_directory / "claude"
            real_claude.write_text(f"#!/bin/sh\ntouch {marker}\n")
            real_claude.chmod(0o755)
            bb = binary_directory / "bb"
            bb.write_text("#!/bin/sh\nprintf partial\nexit 7\n")
            bb.chmod(0o755)
            cache = home / ".cache/claude"
            cache.mkdir(parents=True)
            published = cache / "generated-settings.json"
            published.write_text('{"previous":true}\n')

            result = subprocess.run(
                [WRAPPER],
                cwd=ROOT,
                env=os.environ
                | {
                    "HOME": str(home),
                    "PATH": f"{binary_directory}:{os.environ['PATH']}",
                },
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertNotEqual(0, result.returncode)
            self.assertIn("cannot generate settings", result.stderr)
            self.assertEqual('{"previous":true}\n', published.read_text())
            self.assertFalse(marker.exists())
            self.assertEqual([published], list(cache.iterdir()))


if __name__ == "__main__":
    unittest.main()
