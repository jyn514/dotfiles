#!/usr/bin/env python3

import json
import shutil
import subprocess
import tempfile
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

    def test_a_config_source_rename_only_changes_the_shared_mapping(self) -> None:
        config = json.loads((ROOT / "install.conf.json").read_text())
        links = next(section["link"] for section in config if "link" in section)
        links["$HOME/.config/git/ignore"] = "config/renamed-ignore"

        with tempfile.TemporaryDirectory() as temporary_directory:
            config_path = Path(temporary_directory) / "install.conf.json"
            config_path.write_text(json.dumps(config))
            escaped_path = str(config_path).replace("'", "''")
            result = self.run_powershell(
                "$ast = [System.Management.Automation.Language.Parser]::ParseFile("
                "(Resolve-Path './setup.ps1'), [ref]$null, [ref]$null); "
                "$function = $ast.Find({ param($node) "
                "$node -is [System.Management.Automation.Language.FunctionDefinitionAst] "
                "-and $node.Name -eq 'Get-ConfigLinkPlan' }, $true); "
                "Invoke-Expression $function.Extent.Text; "
                "$destinations = [ordered]@{ "
                "'$HOME/.config/git/ignore' = @{ Path = 'windows-ignore' } }; "
                f"Get-ConfigLinkPlan '{escaped_path}' $destinations | ConvertTo-Json -Compress"
            )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(
            {"Existing": "config/renamed-ignore", "New": "windows-ignore"},
            json.loads(result.stdout),
        )

    def test_link_plan_merges_all_link_sections(self) -> None:
        config = [
            {"link": {"$HOME/.config/git/ignore": "config/first-ignore"}},
            {"defaults": {"link": {"create": True}}},
            {"link": {"$HOME/.config/git/config": "config/second-gitconfig"}},
        ]

        with tempfile.TemporaryDirectory() as temporary_directory:
            config_path = Path(temporary_directory) / "install.conf.json"
            config_path.write_text(json.dumps(config))
            escaped_path = str(config_path).replace("'", "''")
            result = self.run_powershell(
                "$ast = [System.Management.Automation.Language.Parser]::ParseFile("
                "(Resolve-Path './setup.ps1'), [ref]$null, [ref]$null); "
                "$function = $ast.Find({ param($node) "
                "$node -is [System.Management.Automation.Language.FunctionDefinitionAst] "
                "-and $node.Name -eq 'Get-ConfigLinkPlan' }, $true); "
                "Invoke-Expression $function.Extent.Text; "
                "$destinations = [ordered]@{ "
                "'$HOME/.config/git/ignore' = @{ Path = 'windows-ignore' }; "
                "'$HOME/.config/git/config' = @{ Path = 'windows-gitconfig' } }; "
                f"@(Get-ConfigLinkPlan '{escaped_path}' $destinations) | ConvertTo-Json -Compress"
            )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(
            [
                {"Existing": "config/first-ignore", "New": "windows-ignore"},
                {"Existing": "config/second-gitconfig", "New": "windows-gitconfig"},
            ],
            json.loads(result.stdout),
        )

    def test_link_plan_rejects_duplicate_destinations_across_sections(self) -> None:
        destination = "$HOME/.config/git/ignore"
        config = [
            {"link": {destination: "config/first-ignore"}},
            {"link": {destination: "config/second-ignore"}},
        ]

        with tempfile.TemporaryDirectory() as temporary_directory:
            config_path = Path(temporary_directory) / "install.conf.json"
            config_path.write_text(json.dumps(config))
            escaped_path = str(config_path).replace("'", "''")
            result = self.run_powershell(
                "$ast = [System.Management.Automation.Language.Parser]::ParseFile("
                "(Resolve-Path './setup.ps1'), [ref]$null, [ref]$null); "
                "$function = $ast.Find({ param($node) "
                "$node -is [System.Management.Automation.Language.FunctionDefinitionAst] "
                "-and $node.Name -eq 'Get-ConfigLinkPlan' }, $true); "
                "Invoke-Expression $function.Extent.Text; "
                "$destinations = [ordered]@{ "
                "'$HOME/.config/git/ignore' = @{ Path = 'windows-ignore' } }; "
                f"Get-ConfigLinkPlan '{escaped_path}' $destinations"
            )

        self.assertNotEqual(0, result.returncode)
        self.assertIn(f"duplicate config link destination: {destination}", result.stderr)

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
