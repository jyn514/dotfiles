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
    ) -> tuple[list[str], Path]:
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
        return json.loads(result.stdout), legacy_settings

    def test_loads_tracked_settings_with_project_and_local_sources(self) -> None:
        arguments, legacy_settings = self.run_wrapper("managed-link")

        self.assertEqual("--settings", arguments[0])
        self.assertTrue(arguments[1].endswith("/.config/claude/settings.json"))
        self.assertEqual(["--setting-sources", "project,local"], arguments[2:4])
        self.assertEqual("--system-prompt", arguments[4])
        self.assertEqual("prompt", arguments[-1])
        self.assertFalse(legacy_settings.exists())

    def test_uses_repository_settings_before_dotfile_setup(self) -> None:
        arguments, legacy_settings = self.run_wrapper(
            "managed-link", install_settings=False
        )

        self.assertEqual(str(ROOT / "config/claude.json"), arguments[1])
        self.assertFalse(legacy_settings.exists())

    def test_preserves_claude_owned_user_settings(self) -> None:
        arguments, legacy_settings = self.run_wrapper('{"theme":"dark"}\n')

        self.assertEqual("prompt", arguments[-1])
        self.assertEqual('{"theme":"dark"}\n', legacy_settings.read_text())


if __name__ == "__main__":
    unittest.main()
