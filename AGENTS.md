# Repository Guidelines

## Project Structure & Module Organization

This repository stores dotfiles and bootstrap scripts.
User command links and small standalone commands live in `bin/`;
self-contained executable subsystems, including their tests and documentation, live in `tools/<name>/`.
Shared internal implementations remain in `libexec/`, repository-maintenance commands in `dev/`, and cross-cutting tests in `tests/<feature>/`.
User configuration lives in `config/`, system files in `global/`, sourced support and static assets in `lib/`, vendored code in `vendor/`, and package manifests in `install/`.
Setup entry points are `setup`, `setup.ps1`, and `track`.

## Build, Test, and Development Commands

- `./setup`: installs or links tools and dotfiles for the current platform.
  Read the relevant function before using it on a new machine.
- `./track <existing file> [name]`: moves a user file into `config/` and adds its Dotbot mapping, or copies a system file into `global/` and records it in `install/global.txt`.
- `python3 tools/open/tests/test_open.py`: runs unit tests for the editor/open wrapper behavior.
- `python3 tests/wezterm/wezterm_test.py`: validates selector patterns in `config/wezterm.lua`.
- `dev/test`: runs the test suite and repository checks.
- `shellcheck setup track bin/* dev/* libexec/**/*.sh tools/**/*.sh`: checks shell scripts where applicable;
  some entries are not shell scripts.

## Coding Style & Naming Conventions

Keep scripts portable unless a file already targets one platform.
Shell scripts use POSIX `sh` where declared, tab-indented blocks in existing files, and explicit `set -e` or `set -u` when failure handling matters.
Python uses standard-library `unittest`, type-friendly signatures, `Path` for filesystem work, and four-space indentation.
Match each config file's native style rather than normalizing unrelated formatting.

For shell and generated configuration, preserve producer failures.
Avoid nested command substitutions and unchecked pipelines that can mask an earlier error;
source generated output only after its producer succeeds, and update persistent caches transactionally.
Add regression tests for both success and failure paths.

When a simple implementation choice preserves a non-obvious historical constraint, add a brief comment explaining the constraint and why that choice preserves it.

For Pi UI extensions, verify documented hooks against the installed implementation and reuse Pi's authoritative providers instead of duplicating resource discovery.

## Testing Guidelines

Keep subsystem-owned tests under `tools/<name>/tests/`;
add cross-cutting tests under the matching `tests/<feature>/` directory.
Name Python test files `*_test.py` or `test_*.py`, and name test methods after the behavior under protection.
Prefer temporary directories and mocks over touching real home-directory state.
For config regex changes, include positive and negative examples.

For undocumented mutation APIs, test end-to-end on an owned disposable resource, verify the complete result, and restore or delete the resource before touching production.
For recovery commands, test states left by failed recovery attempts, not only clean startup and normal shutdown.

Validate configuration with its native parser or application when practical, in addition to repository tests.
Examples include shell syntax checks, `jq empty config/claude.json`, headless Neovim startup, Kitty's configuration loader, and `claude doctor`;
distinguish parser failures from unrelated runtime, authentication, or environment warnings.

## Commit & Pull Request Guidelines

Use Jujutsu (`jj`) by default for inspection and change management: `jj status`, `jj diff`, and `jj log`.
Use a short imperative subject, for example `Fix PATH entry detection`.
Add a commit body when the motivation, failure mode, design constraint, or verification would not be obvious to a future reader.
Keep commits narrow and name the affected tool when useful.
Pull requests should state the user-visible change, list commands run, note platform assumptions, and include screenshots only for visual terminal or desktop behavior.

## Security & Configuration Tips

When repairing VM configuration, also update its host-owned setup source so the repair survives recreation.

Do not commit secrets, tokens, private hostnames, or machine-local paths unless they are already intentionally tracked.
Be careful with `global/` changes: they may be copied with elevated privileges.
Review `install.conf.json` when adding dotfiles and `install/*.txt` when adding packages so bootstrap behavior remains predictable.
