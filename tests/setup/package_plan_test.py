#!/usr/bin/env python3

import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class PackagePlanTests(unittest.TestCase):
    def test_generated_bootstrap_table_is_current(self) -> None:
        generated = ROOT / "tools/package-plan/bootstrap.generated.sh"
        before = generated.read_bytes()

        result = subprocess.run(
            ["dev/update-package-bootstrap"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(before, generated.read_bytes())

    def test_setup_runs_planner_before_privileged_main(self) -> None:
        setup = (ROOT / "setup.sh").read_text()
        full = setup[setup.index("setup_install_global ()"):]
        packages = setup[setup.index("setup_install_global_packages ()"):]
        privileged = (ROOT / "libexec/setup/setup_sudo.sh").read_text()

        self.assertLess(
            full.index("./dev/package-plan apply --yes"),
            full.index("./libexec/setup/setup_sudo.sh main"),
        )
        self.assertIn("./dev/package-plan apply --yes", packages)
        self.assertNotIn("package-plan", privileged)
        self.assertNotIn("install_features", privileged)

    def test_vendored_shim_translates_mise_sudo_forms(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory)
            log = directory / "doas.log"
            doas = directory / "doas"
            doas.write_text(
                "#!/bin/sh\n"
                'printf "%s" doas >> "$DOAS_LOG"\n'
                'for argument do printf " <%s>" "$argument" >> "$DOAS_LOG"; done\n'
                'printf "\\n" >> "$DOAS_LOG"\n'
            )
            doas.chmod(0o755)
            environment = os.environ.copy()
            environment.update(DOAS_LOG=str(log), PATH=f"{directory}:/usr/bin:/bin")
            shim = ROOT / "vendor/doas-sudo-shim/sudo"

            for arguments in (
                ["true"],
                ["env", "KEY=VALUE", "true"],
                ["-n", "true"],
            ):
                subprocess.run([shim, *arguments], env=environment, check=True)

            self.assertEqual(
                [
                    "doas <--> <true>",
                    "doas <--> <env> <KEY=VALUE> <true>",
                    "doas <-n> <--> <true>",
                ],
                log.read_text().splitlines(),
            )


if __name__ == "__main__":
    unittest.main()
