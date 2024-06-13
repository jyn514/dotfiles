# Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
$ErrorActionPreference = "Stop"

# check if this is powershell 5
if ($PSVersionTable.PSVersion.Major -lt 7) {
    Write-Output "Re-execing with powershell 7"
    if (! (where.exe pwsh)) {
        curl.exe https://github.com/PowerShell/PowerShell/releases/download/v7.4.2/PowerShell-7.4.2-win-x64.msi -L -o powershell.msi
        .\powershell.msi /quiet
        Remove-Item powershell.msi    
    }
    pwsh $PSCommandPath
    exit $LASTEXITCODE
}

function Test-Application($cmd) {
    return (Get-Command $cmd -ErrorAction SilentlyContinue -CommandType Application | Measure-Object).Count -gt 0
}

function Install-ConfigLink($existing, $new) {
    Install-Link (Join-Path $PSScriptRoot "config" $existing) $new
}

function Install-Link($existing, $new) {
    if ((! (Test-Path $new)) -or ($null -ne (Get-Member -InputObject (Get-Item $new) -name LinkType))) {
        if ((Get-Item $existing).PSIsContainer) {
            $type = "Junction"
        } else {
            $type = "HardLink"
        }
        # Overwrite the existing link
        New-Item -ItemType $type -Force -Path $new -Value $existing | Out-Null
    } else {
        # Error out.
        Write-Error ("refusing to overwrite existing file " + $new + " with link to " + $existing)
    }
}

function Install-Dotfiles() {
    # most of these aren't relevant. vim, gdb, etc aren't installed on windows. just setup git.
    # todo: set up global hooks and youtube-dl?
    $git_config_dir = Join-Path $HOME ".config" "git"
    New-Item -ItemType Directory -Path $git_config_dir -Force | Out-Null
    foreach ($conf in "gitignore", "githooks") {
        Install-ConfigLink $conf $(Join-Path $git_config_dir ($conf -replace "^git",""))
    }
    Install-ConfigLink "gitconfig" $(Join-Path $HOME ".gitconfig")
    Install-ConfigLink jj.toml $(jj config path --user)

    $bin_dir = Join-Path $HOME ".local" "bin"
    New-Item -ItemType Directory -Path $bin_dir -Force | Out-Null
    foreach ($cmd in Get-ChildItem bin/*.bat) {
        Install-Link (Join-Path $PSScriptRoot "bin" $cmd.Name) $(Join-Path $bin_dir $cmd.Name)
    }
    # TODO: install vscode settings to %APPDATA%\Code\User\settings.json
}

function Install-Programs() {
    Write-Output "Installing tools from winget"
    winget install --source winget rustup git.git keepassxc jq python3
    # TODO: add python bin dir to path
    # [Environment]::SetEnvironmentVariable("Path", $env:Path, [System.EnvironmentVariableTarget]::User)

    if (! $(Test-Application cargo)) {
        # Rustup unfortunately doesn't have a way for us to ask it to install the MSVC build tools for us.
        # Do it manually here.
        $t = Join-Path $env:TEMP vs_community.exe
        curl.exe -L "https://aka.ms/vs/17/release/vs_community.exe" -o $t
        & $t --wait --focusedUi --addProductLang En-us --add "Microsoft.VisualStudio.Component.VC.Tools.x86.x64" --add "Microsoft.VisualStudio.Component.Windows11SDK.22000"
        Remove-Item $t
        rustup toolchain add nightly --profile minimal -c clippy -c miri
        rustup default nightly
    }

    if (! $(Test-Application cargo-binstall)) {
                # https://github.com/cargo-bins/cargo-binstall#installation
                Write-Output "Installing cargo-binstall"
                curl -L --proto '=https' --tlsv1.2 -sSf https://raw.githubusercontent.com/cargo-bins/cargo-binstall/main/install-from-binstall-release.sh | bash
    } else {
                # update to latest version; old versions often hit a rate limit
                Write-Output "Updating cargo-binstall"
                cargo binstall cargo-binstall
    }

    Write-Output "Installing Rust tools using cargo-binstall"
    cargo binstall -y --rate-limit 10/1 $(Get-Content rust.txt)
    # Disable microsoft's garbage windows store aliases
    foreach ($py in "python", "python3") {
        Remove-Item -ErrorAction SilentlyContinue $env:LOCALAPPDATA\Microsoft\WindowsApps\$py.exe
    }
    python -m pip install --user -r python.txt
}

Set-Location $PSScriptRoot
Install-Dotfiles
Install-Programs
