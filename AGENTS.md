# Repository Guidelines

## Project Structure & Module Organization

This repository stores dotfiles and bootstrap scripts. User-level configuration lives in `config/`, with its Dotbot mappings in `install.conf.json`. System-level files live in `global/`, helpers in `bin/`, shared support in `lib/`, and package manifests in `install/`. Setup entry points are `setup.sh`, `setup.ps1`, and `track.sh`. Tests live under `scripts/<feature>/`, such as `scripts/open/` and `scripts/wezterm/`. Static assets belong in `assets/`.

## Build, Test, and Development Commands

- `./setup.sh`: installs or links tools and dotfiles for the current platform. Read the relevant function before using it on a new machine.
- `./track.sh <existing file> [name]`: moves a user file into `config/` and adds its Dotbot mapping, or copies a system file into `global/` and records it in `install/global.txt`.
- `python3 scripts/open/test_open.py`: runs unit tests for the editor/open wrapper behavior.
- `python3 scripts/wezterm/wezterm_test.py`: validates selector patterns in `config/wezterm.lua`.
- `shellcheck setup.sh track.sh bin/* lib/*.sh`: checks shell scripts where applicable; some `bin/` entries are not shell scripts.

## Coding Style & Naming Conventions

Keep scripts portable unless a file already targets one platform. Shell scripts use POSIX `sh` where declared, tab-indented blocks in existing files, and explicit `set -e` or `set -u` when failure handling matters. Python uses standard-library `unittest`, type-friendly signatures, `Path` for filesystem work, and four-space indentation. Match each config file's native style rather than normalizing unrelated formatting.

## Testing Guidelines

Add focused tests beside the feature under `scripts/<feature>/`. Name Python test files `*_test.py` or `test_*.py`, and name test methods after the behavior under protection. Prefer temporary directories and mocks over touching real home-directory state. For config regex changes, include positive and negative examples.

## Commit & Pull Request Guidelines

Use Jujutsu (`jj`) by default for inspection and change management: `jj status`, `jj diff`, and `jj log`. Use a short imperative subject, for example `Fix PATH entry detection`. Add a commit body when the motivation, failure mode, design constraint, or verification would not be obvious to a future reader. Keep commits narrow and name the affected tool when useful. Pull requests should state the user-visible change, list commands run, note platform assumptions, and include screenshots only for visual terminal or desktop behavior.

## Security & Configuration Tips

Do not commit secrets, tokens, private hostnames, or machine-local paths unless they are already intentionally tracked. Be careful with `global/` changes: they may be copied with elevated privileges. Review `install.conf.json` when adding dotfiles and `install/*.txt` when adding packages so bootstrap behavior remains predictable.
