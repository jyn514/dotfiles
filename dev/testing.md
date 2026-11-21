# Testing and probes

Run commands from the repository root.
See the [development index](README.md) for change guidelines and maintenance tasks.

## Dependencies and setup

Before running native JavaScript suites or compaction replays, install the locked dependencies on first setup or after dependency changes.
This requires Node/npm; Pi tests and replays also require Bun.
Run the install before starting tests, not alongside them:

```sh
npm ci --ignore-scripts --no-audit --no-fund
npm ci --prefix tools/pi-link --ignore-scripts --no-audit --no-fund
npm ci --prefix tools/search-bsky-likes --ignore-scripts --no-audit --no-fund
```

The second command installs the local pi-link fork's locked WebSocket dependency for its native regression tests.
The third installs the Bluesky likes tool's locked dependencies for its native regression tests.
This makes tests and replays use the locked Pi SDK instead of Bun's auto-installed or cached version.

Install the Python runtime requirements in `install/python.txt` in the same environment as pytest.
Native integration cases also use SQLite's `sqlite3` command, Java, `xdg-mime`, Codex, mosh, and restic;
individual suites report unavailable optional tools as skips.
If a sandbox provides transport wrappers instead of offline executables, select installed native binaries with
`DOTFILES_TEST_JAVA_REAL` and `DOTFILES_TEST_CODEX_REAL`.
Set `PI_PACKAGE_DIR` to the installed Pi SDK directory when it is not under the original HOME.
Installed-Pi tests need that build's APIs, not the older locked unit-test SDK in `node_modules/`.

## Run the full suite

Run `dev/test` for the fast suite. It excludes the process, socket, tmux, and
runtime integration files listed in `dev/integration-tests.txt`, plus the native
adapters in `tests/native/`.
Run `dev/test --integration` for the fast and non-native integration suites.
Run `dev/test --native` for the complete suite, including native adapters.
Container and Lima modes include the non-native integration suite automatically.
Every manifest path must exist; the runner fails instead of silently dropping a
renamed integration file. Both broader modes remove the manifest exclusions, so
the standard pytest discovery route remains the single authority for collection.
The complete suite checks for Bun on PATH before dispatch and stops with installation guidance if Bun is missing.
It invokes `dev/test-environment` automatically.
The runner uses pytest-sugar for progress and immediate failure output in terminals.
Noninteractive runs use pytest's standard reporter instead of forcing terminal rendering.
Do not also enable pytest-instafail; it conflicts with sugar and inflates pass counts.
See [pytest-sugar #222](https://github.com/Teemu/pytest-sugar/issues/222).
The runner uses installed pytest only after a successful plugin check.
Otherwise it uses `uv` and the pinned requirements in `install/test.txt`, or prints installation guidance if `uv` is unavailable.
Pytest performs one collection and execution pass.
Python tests and, with `--native`, the native-suite adapters in `tests/native/` share the existing pytest-xdist scheduler with `--dist loadfile`.
Every mode defaults to eight pytest workers. Native adapters separately admit two
subprocesses at a time so Codex, Node, SQLite, and other runtimes cannot exhaust
host memory through concurrent virtual-memory reservations. Use `--jobs N` or
`TEST_JOBS` to override pytest workers, and `TEST_NATIVE_JOBS` to override the
native subprocess limit.
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
Every reported diagnostic fails the runner, regardless of ShellCheck's native severity.
Discovery, dependency, and ShellCheck execution or report failures also fail the runner.
Pytest discovery follows `pytest.ini`: `*_test.py` and `test_*.py` under `tests/` and `tools/`, including the native-suite adapters.
Put each independently invoked default native suite in its own adapter file under `tests/native/` so `loadfile` can schedule it separately.
Keep the command and its native framework's test scope unchanged when adding an adapter.
Other suites need an existing discovery route or explicit dispatch in `dev/test`, by default or through a documented opt-in mode.
Check that intended cases execute through that route, not only through a focused command.

## Run focused tests

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
dev/test-environment bun test ./tests/pi/luna_compaction_test.ts ./tests/pi/replay_compaction_test.ts
```

Prefix focused Bun file arguments with `./` to select exact paths rather than substring filters that can also match copied suites.

## Isolation and permissions

The wrapper provides HOME and XDG environment isolation, not a filesystem sandbox.
Commands can still write explicit paths outside HOME.
Check generated-source freshness with check-only commands or a disposable checkout, not an updater targeting the working copy.
For wrapper behavior, persistent Cargo state, and real-tool selection, see [test-environment details](test-environment.md).
For Neovim test prerequisites and invocation, see the [Neovim config test guide](../tests/nvim/README.md).
For installed-Pi-specific test recipes, see the [Pi configuration guide](../config/pi-agent/README.md#testing).

## Real-configuration exceptions

Do not wrap the [configured startup benchmark](../tools/codex-sandbox/development.md#measure-interactive-startup).
Do not wrap live `dev/replay-compaction` requests.
Those use installed configuration, caches, or authentication, so isolated runs do not measure that setup.
For replay prerequisites and usage, see [replay a compaction](compaction-replay.md).

