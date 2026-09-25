from __future__ import annotations

from pathlib import Path
import importlib.util
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "install_pi", ROOT / "libexec/setup/install_pi.py"
)
assert SPEC is not None and SPEC.loader is not None
install_pi = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(install_pi)


class PiInstallTest(unittest.TestCase):
    def test_matching_marker_does_not_hide_a_missing_cli(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory)
            install = state / "node"
            package = install / "node_modules/@earendil-works/pi-coding-agent"
            package.mkdir(parents=True)
            (install / ".source-revision").write_text(
                install_pi.PI_REVISION + "\n", encoding="utf-8"
            )

            with mock.patch.object(install_pi, "PI_INSTALL", install), \
                    mock.patch.object(install_pi, "PI_CLI", install / "node_modules/.bin/pi"):
                self.assertFalse(install_pi.install_is_current(install_pi.PI_REVISION))

    def test_install_records_revision_only_after_npm_install(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory)
            source = state / "source"
            install = state / "node"
            package = source / "packages/coding-agent"
            package.mkdir(parents=True)

            commands: list[tuple[list[str], Path | None]] = []

            def fake_run(command: list[str], *, cwd: Path | None = None) -> None:
                commands.append((command, cwd))
                if command[:2] == ["git", "clone"]:
                    (source / ".git").mkdir()
                if command[:2] == ["npm", "install"] and "--prefix" in command:
                    cli = install / "node_modules/.bin/pi"
                    cli.parent.mkdir(parents=True, exist_ok=True)
                    cli.touch()

            with mock.patch.object(install_pi, "PI_STATE", state), \
                    mock.patch.object(install_pi, "PI_SOURCE", source), \
                    mock.patch.object(install_pi, "PI_INSTALL", install), \
                    mock.patch.object(install_pi, "PI_PACKAGE", package), \
                    mock.patch.object(install_pi, "PI_CLI", install / "node_modules/.bin/pi"), \
                    mock.patch.object(install_pi, "run", side_effect=fake_run), \
                    mock.patch.object(install_pi.subprocess, "run") as subprocess_run:
                subprocess_run.return_value.stdout = "test-revision"
                install_pi.install()

            self.assertEqual("test-revision\n",
                             (install / ".source-revision").read_text(encoding="utf-8"))
            self.assertEqual(["git", "checkout", "--force", "--detach", "FETCH_HEAD"], commands[2][0])
            self.assertEqual(["npm", "run", "hydrate:pinned-model-data"], commands[4][0])
            self.assertEqual(["npm", "run", "build:offline"], commands[5][0])
            self.assertIn("--prefix", commands[6][0])


if __name__ == "__main__":
    unittest.main()
