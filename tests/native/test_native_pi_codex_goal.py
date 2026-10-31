"""Run the goal package's locked native checks without changing its source tree."""

from pathlib import Path
import shutil
import tempfile


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "tools/pi-codex-goal"


def test_pi_codex_goal(run_native_suite):
    with tempfile.TemporaryDirectory(prefix="dotfiles-pi-codex-goal-") as temporary:
        package = Path(temporary) / "pi-codex-goal"
        shutil.copytree(SOURCE, package, ignore=shutil.ignore_patterns(
            "node_modules", "dist", "work", "target", "*.tgz",
        ))
        run_native_suite([
            "npm", "--prefix", str(package), "ci", "--ignore-scripts",
            "--no-audit", "--no-fund",
        ])
        run_native_suite(["npm", "--prefix", str(package), "run", "check"])
