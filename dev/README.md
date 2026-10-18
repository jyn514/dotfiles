# Development and maintenance

Run the commands below from the repository root. See [configuration](../config/README.md)
for installing or adding dotfiles, and the [tools reference](../tools/README.md)
for subsystem-owned commands and tests.

## Repository change guidelines

### Layout and conventions

Small user commands and command links live in `bin/`; independently invoked
subsystems, with their tests and documentation, live in `tools/<name>/`.
Shared internal implementations belong in `libexec/`, maintenance commands in
`dev/`, and cross-cutting tests in `tests/<feature>/`. Configuration belongs in
`config/`, system files in `global/`, sourced support and static assets in `lib/`,
vendored code in `vendor/`, and package manifests in `install/`.
Setup entry points are `setup`, `setup.ps1`, and `track`.

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

### Commands and validation

Read the relevant setup function before using `./setup` on a new machine.
`./track <existing file> [name]` moves a user file into `config/` and adds its Dotbot
mapping, or copies a system file into `global/` and records it in `install/global.txt`.

Use [Testing and probes](#testing-and-probes) for dependencies and isolation:

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

### Review and bootstrap

Follow [commit-quality](../skills/commit-quality/SKILL.md) for atomic changes,
imperative subjects, and explanatory bodies. PRs state the user-visible change,
commands run, and platform assumptions; include screenshots only for visual
terminal or desktop behavior.

Follow the early safety constraints in [AGENTS.md](../AGENTS.md) for generated
outputs, VM repairs, credential scopes, privileged system files, and secrets.
When adding dotfiles or packages, review `install.conf.json` or `install/*.txt`
so bootstrap behavior stays predictable.

## Testing and probes

Before running Pi tests or compaction replays, install the locked dependencies on first setup or after dependency changes.
This requires Node/npm; Pi tests and replays also require Bun.
Run the install before starting tests, not alongside them:

```sh
npm ci --ignore-scripts --no-audit --no-fund
npm ci --prefix tools/pi-link --ignore-scripts --no-audit --no-fund
```

The second command installs the local pi-link fork's locked WebSocket dependency for its native regression tests.
This makes tests and replays use the locked Pi SDK instead of Bun's auto-installed or cached version.

Install the Python runtime requirements in `install/python.txt` in the same environment as pytest.
Native integration cases also use SQLite's `sqlite3` command, Java, `xdg-mime`, Codex, mosh, and restic;
individual suites report unavailable optional tools as skips.
If a sandbox provides transport wrappers instead of offline executables, select installed native binaries with
`DOTFILES_TEST_JAVA_REAL` and `DOTFILES_TEST_CODEX_REAL`.
Set `PI_PACKAGE_DIR` to the installed Pi SDK directory when it is not under the original HOME.
Installed-Pi tests need that build's APIs, not the older locked unit-test SDK in `node_modules/`.

Run `dev/test` for the suite, including `tests/pi`, with these prerequisites.
It checks for Bun on PATH before running any suite and stops with installation guidance if Bun is missing.
It invokes `dev/test-environment` automatically.
The runner uses installed pytest only after a successful plugin check.
Otherwise it uses `uv` and the pinned requirements in `install/test.txt`, or prints installation guidance if `uv` is unavailable.
Python tests and the native-suite adapters in `tests/native/` share the existing pytest-xdist scheduler: eight workers and `--dist loadfile`.
Use `--jobs N` or `TEST_JOBS` to change the worker count.
Each adapter runs its existing native command with a separate private HOME and XDG state; native frameworks still discover and run their own cases.
`bunfig.toml` excludes `target/**` from Bun discovery so retained benchmark sources do not run as tests.
Separate adapter files let xdist overlap whole suites, not individual native test cases.
Native failures use pytest's exit status and include the native command's captured output in the failure report.
Other test items follow pytest's normal failure policy; a failed pytest run stops subsequent repository checks and opt-in integrations.
The ShellCheck stage requires ShellCheck and ripgrep on PATH and replaces the former `sh -n` pass.
It checks files beginning with `#!/bin/sh` in the existing setup, command, library, and test roots.
Discovery honors root and nested `.gitignore` rules, including negations, and includes non-ignored hidden scripts.
Ripgrep configuration and other ignore-file formats cannot override those rules.
SC2015 (compound guards) and SC1091 (unfollowed sources) are suppressed.
Reviewed codes SC1007, SC2002, SC2016, SC2034, SC2119, SC2120, SC2237, SC2317, and SC3013 print nonblocking warnings.
Every other diagnostic fails the runner, regardless of ShellCheck's native severity; new SC2086 quoting findings still fail.
Discovery, dependency, and ShellCheck execution or report failures also fail the runner.
Pytest discovery follows `pytest.ini`: `*_test.py` and `test_*.py` under `tests/` and `tools/`, including the native-suite adapters.
Put each independently invoked default native suite in its own adapter file under `tests/native/` so `loadfile` can schedule it separately.
Keep the command and its native framework's test scope unchanged when adding an adapter.
Other suites need an existing discovery route or explicit dispatch in `dev/test`, by default or through a documented opt-in mode.
Check that intended cases execute through that route, not only through a focused command.
For focused Python suites, use `dev/pytest`:

```sh
dev/pytest -q -p no:cacheprovider tests/chat-history/chat_history_test.py
```

Both `dev/test` and `dev/pytest` select pytest inside the isolated environment.
They use an installed pytest with the required plugins when it works, or fall
back to `uvx` with the pinned requirements in `install/test.txt`. Install uv if
pytest is unavailable there: user-installed Python packages are hidden by the
private HOME. Pytest arguments and exit status pass through unchanged.
For focused tests and ad-hoc Pi probes, including `--help` checks, use `dev/test-environment COMMAND [ARGS...]`:

```sh
dev/test-environment bun test tests/pi/luna_compaction_test.ts tests/pi/replay_compaction_test.ts
```

The wrapper provides HOME and XDG environment isolation, not a filesystem sandbox.
Commands can still write explicit paths outside HOME.
Check generated-source freshness with check-only commands or a disposable checkout, not an updater targeting the working copy.
For wrapper behavior, persistent Cargo state, and real-tool selection, see [test-environment details](test-environment.md).
For Neovim test prerequisites and invocation, see the [Neovim config test guide](../tests/nvim/README.md).
For installed-Pi-specific test recipes, see the [Pi configuration guide](../config/pi-agent/README.md#testing).

The profile tests in `tests/setup/profile_test.py` and Neovim tests in `tests/nvim/` need permission to create local TCP and Unix sockets.
Sandbox launcher and proxy tests in `tools/codex-sandbox/tests/` need that permission too.
If an execution sandbox denies socket creation with `PermissionError: [Errno 1] Operation not permitted`, rerun the affected command outside it.
Use the harness's approval mechanism for the rerun.
Keep the `dev/test-environment` wrapper; HOME isolation does not grant socket permissions.

Do not wrap the [configured startup benchmark](../tools/codex-sandbox/development.md#measure-interactive-startup).
Do not wrap live `dev/replay-compaction` requests.
Those use installed configuration, caches, or authentication, so isolated runs do not measure that setup.
For replay prerequisites and usage, see [replay a compaction](#replay-a-compaction).

### Broker-backed live provider probe

This probe makes a live model request through the sandbox broker and may incur model cost.
See the [sandbox development guide](../tools/codex-sandbox/development.md#broker-backed-live-provider-probe) for the procedure.

## Bootstrap maintenance

Run `dev/update-bootstrap-lock --dry-run` to preview newer plugin revisions,
release assets, and checksums. Run it without `--dry-run` to update
`install/bootstrap.lock.json` and `install/bundles.json`, then review the diff
and run `dev/test`. The updater uses `GITHUB_TOKEN` when it is already set,
but does not require or export one.

## Replay a compaction

See [compaction replay guidance](compaction-replay.md) for the replay command, its limits, and the comparison workflow.
