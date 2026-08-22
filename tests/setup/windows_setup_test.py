#!/usr/bin/env python3

import json
import shutil
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PWSH = shutil.which("pwsh")


@unittest.skipUnless(PWSH, "PowerShell is not available")
class WindowsSetupTests(unittest.TestCase):
    def run_powershell(self, script: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [PWSH, "-NoProfile", "-NonInteractive", "-Command", script],
            cwd=ROOT,
            text=True,
            capture_output=True,
        )

    def test_setup_is_valid_powershell(self) -> None:
        result = self.run_powershell(
            "$errors = $null; "
            "[System.Management.Automation.Language.Parser]::ParseFile("
            "(Resolve-Path './setup.ps1'), [ref]$null, [ref]$errors) | Out-Null; "
            "if ($errors.Count) { $errors | ForEach-Object { Write-Error $_ }; exit 1 }"
        )
        self.assertEqual(0, result.returncode, result.stderr)

    def test_winget_install_arguments_are_executed_as_separate_values(self) -> None:
        result = self.run_powershell(
            "$ast = [System.Management.Automation.Language.Parser]::ParseFile("
            "(Resolve-Path './setup.ps1'), [ref]$null, [ref]$null); "
            "$function = $ast.Find({ param($node) "
            "$node -is [System.Management.Automation.Language.FunctionDefinitionAst] "
            "-and $node.Name -eq 'Install-WingetPackage' }, $true); "
            "Invoke-Expression $function.Extent.Text; "
            "$script:captured = $null; "
            "function winget { $script:captured = @($args) }; "
            "Install-WingetPackage 'example.package' '--wait --passive'; "
            "$script:captured | ConvertTo-Json -Compress"
        )
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(
            [
                "install",
                "--id",
                "example.package",
                "--exact",
                "--accept-package-agreements",
                "--accept-source-agreements",
                "--override",
                "--wait --passive",
            ],
            json.loads(result.stdout),
        )


if __name__ == "__main__":
    unittest.main()
