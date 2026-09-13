$ErrorActionPreference = "Stop"

function Test-Application($Command) {
    return $null -ne (Get-Command $Command -ErrorAction SilentlyContinue -CommandType Application)
}

function Install-WingetPackage($Id, $Override = $null) {
    $Arguments = @(
        "install", "--id", $Id, "--exact",
        "--accept-package-agreements", "--accept-source-agreements"
    )
    if ($null -ne $Override) {
        $Arguments += @("--override", $Override)
    }
    winget @Arguments
}

function Add-Path($NewPath) {
    $Current = [System.Environment]::GetEnvironmentVariable("Path", "User")
    $Entries = @($Current -split ";" | Where-Object { $_ })
    if ($Entries -notcontains $NewPath) {
        $Updated = (@($Entries) + $NewPath) -join ";"
        [System.Environment]::SetEnvironmentVariable("Path", $Updated, "User")
    }
    if (($env:Path -split ";") -notcontains $NewPath) {
        $env:Path = "$env:Path;$NewPath"
    }
}

function Install-PowerShell7() {
    if ($PSVersionTable.PSVersion.Major -ge 7) {
        return
    }
    Write-Output "Installing PowerShell 7"
    Install-WingetPackage "Microsoft.PowerShell"
    $PowerShell = Join-Path $env:ProgramFiles "PowerShell\7\pwsh.exe"
    if (! (Test-Path $PowerShell)) {
        throw "PowerShell 7 was installed but pwsh.exe was not found"
    }
    & $PowerShell $PSCommandPath
    exit $LASTEXITCODE
}

function Install-Link($Existing, $New) {
    if ((! (Test-Path $New)) -or ($null -ne (Get-Member -InputObject (Get-Item $New) -Name LinkType))) {
        if ((Get-Item $Existing).PSIsContainer) {
            $Type = "Junction"
        } else {
            $Type = "HardLink"
        }
        New-Item -ItemType $Type -Force -Path $New -Value $Existing | Out-Null
    } else {
        throw "refusing to overwrite existing file $New with link to $Existing"
    }
}

function Get-ConfigLinkPlan($InstallConfigPath, $WindowsDestinations) {
    $InstallConfig = Get-Content $InstallConfigPath -Raw | ConvertFrom-Json
    $Links = [ordered]@{}
    foreach ($Section in $InstallConfig) {
        if ($null -eq $Section.link) {
            continue
        }
        foreach ($Mapping in $Section.link.PSObject.Properties) {
            if ($Links.Contains($Mapping.Name)) {
                throw "duplicate config link destination: $($Mapping.Name)"
            }
            $Links[$Mapping.Name] = $Mapping.Value
        }
    }

    foreach ($UnixDestination in $WindowsDestinations.Keys) {
        $Source = $Links[$UnixDestination]
        if ($null -eq $Source) {
            throw "no config source is mapped for $UnixDestination"
        }

        $WindowsDestination = $WindowsDestinations[$UnixDestination]
        if ($WindowsDestination.Children) {
            foreach ($Child in Get-ChildItem (Join-Path $PSScriptRoot $Source)) {
                [PSCustomObject]@{
                    Existing = Join-Path $Source $Child.Name
                    New = Join-Path $WindowsDestination.Path $Child.Name
                }
            }
        } else {
            [PSCustomObject]@{
                Existing = $Source
                New = $WindowsDestination.Path
            }
        }
    }
}

function Install-Dotfiles() {
    $GitConfigDirectory = Join-Path $HOME ".config\git"
    New-Item -ItemType Directory -Path $GitConfigDirectory -Force | Out-Null

    $WindowsDestinations = [ordered]@{
        '$HOME/.config/git/ignore' = @{ Path = Join-Path $GitConfigDirectory "ignore" }
        '$HOME/.config/git/hooks' = @{ Path = Join-Path $GitConfigDirectory "hooks" }
        '$HOME/.config/git/config' = @{ Path = Join-Path $HOME ".gitconfig" }
        '$JJ_CONFIG_PATH' = @{ Path = Join-Path $env:APPDATA "jj\config.toml" }
        '$HOME/.keybindings.ahk' = @{ Path = Join-Path $HOME "Documents\AutoHotkey\keybindings.ahk" }
        '$HOME/.config/helix' = @{ Path = Join-Path $env:APPDATA "helix"; Children = $true }
    }
    foreach ($Link in Get-ConfigLinkPlan (Join-Path $PSScriptRoot "install.conf.json") $WindowsDestinations) {
        Install-Link (Join-Path $PSScriptRoot $Link.Existing) $Link.New
    }

    $BinDirectory = Join-Path $HOME ".local\bin"
    New-Item -ItemType Directory -Path $BinDirectory -Force | Out-Null
    foreach ($Command in Get-ChildItem "bin/*.bat") {
        Install-Link (Join-Path $PSScriptRoot "bin" $Command.Name) (Join-Path $BinDirectory $Command.Name)
    }
}

function Install-SystemPrograms() {
    Write-Output "Installing system applications using winget"
    foreach ($Package in @(
        "Git.Git",
        "KeePassXCTeam.KeePassXC",
        "jqlang.jq",
        "Tailscale.Tailscale",
        "OpenWhisperSystems.Signal"
    )) {
        Install-WingetPackage $Package
    }

    if (! (Test-Application "cl.exe")) {
        Install-WingetPackage "Microsoft.VisualStudio.2022.BuildTools" "--wait --passive --add Microsoft.VisualStudio.Component.VC.Tools.x86.x64 --add Microsoft.VisualStudio.Component.Windows11SDK.22000"
    }
}

function Install-Mise() {
    if (! (Test-Application "mise.exe")) {
        Write-Output "Installing mise using winget"
        Install-WingetPackage "jdx.mise"
        Add-Path (Join-Path $env:LOCALAPPDATA "Microsoft\WinGet\Links")
    }
    if (! (Test-Application "mise.exe")) {
        throw "mise was installed but mise.exe is not available"
    }

    $env:MISE_GLOBAL_CONFIG_FILE = Join-Path $PSScriptRoot "config\mise.toml"
    Add-Path (Join-Path $env:LOCALAPPDATA "mise\shims")
    mise install --yes
    mise reshim
    mise exec -- python -m pip install --quiet -r (Join-Path $PSScriptRoot "install\python.txt")
}

Set-Location $PSScriptRoot
Install-PowerShell7
Install-Dotfiles
Install-SystemPrograms
Install-Mise
