# Repository change guidelines

Run commands from the repository root.
See the [development index](README.md) for testing and maintenance tasks.

## Layout and conventions

Small user commands and command links live in `bin/`; independently invoked
subsystems, with their tests and documentation, live in `tools/<name>/`.
Shared internal implementations belong in `libexec/`, maintenance commands in
`dev/`, and cross-cutting tests in `tests/<feature>/`. Configuration belongs in
`config/`, system files in `global/`, sourced support and static assets in `lib/`,
vendored code in `vendor/`, and package manifests in `install/`.

Choose setup guidance by task:

- Change Unix setup: [setup commands](../README.md#setup-commands) and [their implementation](../setup).
- Change Windows setup: [PowerShell setup](../setup.ps1).
- Add installed dotfiles: [configuration layout](../config/README.md#grouped-sources) and [`track`](../track).
- Change user services: [service setup](../README.md#user-services) and [`setup_services`](../setup#L381).

Command wrappers use the installed `realpath` to locate support beside the script target rather than implement symlink walks.
Pass the original `$0`, not that target, to `shim_resolve` in `lib/shell/lib.sh` so PATH cleanup removes the invoked wrapper directory.

Keep scripts portable unless the existing file targets one platform. Match native
formatting rather than normalizing unrelated code. Declared POSIX `sh` scripts use
tab-indented blocks and explicit `set -e` or `set -u` when failure handling matters.
Python uses four-space indentation, standard-library `unittest`, type-friendly
signatures, and `Path` for filesystem work.

Comment implementation choices that preserve non-obvious historical constraints:
name the constraint and why the choice preserves it. Preserve concurrency when
consolidating independent operations. For batches, use a review surface suited to
many results rather than repeating the single-item interaction.

## Commands and validation

Read the relevant setup function before using `./setup` on a new machine.
`./track <existing file> [name]` moves a user file into `config/` and adds its Dotbot
mapping, or copies a system file into `global/` and records it in `install/global.txt`.

Use [Testing and probes](testing.md) for dependencies and isolation:

- `dev/test` runs the suite and repository checks.
- `python3 tools/open/tests/test_open.py` tests the editor/open wrapper.
- `python3 tests/wezterm/wezterm_test.py` tests selectors in `config/wezterm.lua`.
- `dev/test-environment python3 dev/check-shell.py` runs the ShellCheck pass without the other suites.

Keep subsystem tests under `tools/<name>/tests/` and cross-cutting tests under
`tests/<feature>/`. Name Python files `*_test.py` or `test_*.py`, and name test
methods after the protected behavior. Prefer temporary directories and mocks to
real home state. Config regex tests need positive and negative examples.

Before using an undocumented mutation API on production, test it end-to-end on an
owned disposable resource, verify the complete result, and restore or delete that
resource. Recovery tests must cover states left by failed recovery attempts, not
only clean startup and normal shutdown.

Validate configuration with its native parser or application where practical,
as well as repository tests. Examples: shell syntax checks, `jq empty
config/agents/claude/claude.json`, headless Neovim startup, Kitty's loader, and
`claude doctor`. Distinguish parser failures from unrelated runtime,
authentication, or environment warnings. Confirm the application loaded changes
before interpreting results, as required by the shared instructions.

## Review and bootstrap

Follow [commit-quality](../skills/commit-quality/SKILL.md) for atomic changes,
imperative subjects, and explanatory bodies. PRs state the user-visible change,
commands run, and platform assumptions; include screenshots only for visual
terminal or desktop behavior.

Follow the early safety constraints in [AGENTS.md](../AGENTS.md) for generated
outputs, VM repairs, credential scopes, privileged system files, and secrets.
When adding dotfiles or packages, review `install.conf.json` or `install/*.txt`
so bootstrap behavior stays predictable.

