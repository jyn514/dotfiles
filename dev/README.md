# Development and maintenance

Run the commands below from the repository root. See [configuration](../config/README.md)
for installing or adding dotfiles, and the [tools reference](../tools/README.md)
for subsystem-owned commands and tests.

## Testing and probes

Before running Pi tests or compaction replays, install the locked dependencies.
This requires Node/npm; Pi tests and replays also require Bun:

```sh
npm ci --ignore-scripts --no-audit --no-fund
```

This makes tests and replays use the locked Pi SDK instead of Bun's
auto-installed or cached version.

Run `dev/test` for the suite, including `tests/pi`, with the prerequisites above.
It invokes `dev/test-environment` automatically; a failing Pi test stops the runner.
For focused tests and ad-hoc Pi probes, including `--help` checks, use
`dev/test-environment COMMAND [ARGS...]`. For example:

```sh
dev/test-environment bun test tests/pi/luna_compaction_test.ts tests/pi/replay_compaction_test.ts
```

The wrapper requires Python 3 and creates a private HOME and Pi/XDG state
directories. It removes them after the child exits normally, nonzero, or by
forwarded signal, preserving stdin, stdout, stderr, and exit status. This is
environment isolation, not a filesystem sandbox: commands can still write
explicit paths outside HOME. The wrapper clears inherited `JJ_CONFIG` so Jujutsu
loads user configuration from the private HOME/XDG directories instead.

For `bb`, `java`, `jj`, and `rg`, the wrapper preserves explicit real-tool overrides
or resolves mise shims before changing HOME. Failed resolution stops the run before
a child starts. Repository-local exclusions keep dependencies, notes, test caches,
and editor sessions untracked even when private HOME hides global ignore rules.

An explicit `PI_PACKAGE_DIR` is preserved. Otherwise, the wrapper discovers the
installed Pi SDK under the original HOME before replacing HOME, so tests can
read the installed SDK without loading personal settings or using its caches.
For `dev/test --containers`, the runner also captures the validated host Pi
installation revision before replacing HOME. The runtime-image probe builds and
checks that commit. Missing or invalid revision metadata stops the runner before
any tests; repair the installation with `mise run pi-install`.

The native prompt-section regression needs an installed Pi build with
`systemPromptOptions.sections`; the locked test SDK predates that API. Run it
without Bun's module mocks:

```sh
dev/test-environment node --test tests/pi/native_prompt_sections.mjs
```

Do not wrap the [configured startup benchmark](../tools/codex-sandbox/README.md#measure-interactive-startup)
or live `dev/replay-compaction` requests: those intentionally use installed
configuration, caches, or authentication. Isolated runs do not measure that setup.

## Bootstrap maintenance

Run `dev/update-bootstrap-lock --dry-run` to preview newer plugin revisions,
release assets, and checksums. Run it without `--dry-run` to update
`install/bootstrap.lock.json` and `install/bundles.json`, then review the diff
and run `dev/test`. The updater uses `GITHUB_TOKEN` when it is already set,
but does not require or export one.

## Replay a compaction

A replay makes a live Luna request and may incur model cost. It uses normal Pi
authentication or the sandbox model broker; do not run it through
`dev/test-environment`. Install the [locked dependencies](#testing-and-probes) first.

To compare [compaction instruction](../config/pi-agent/pi-extensions/compaction.md)
changes against a saved compaction, run:

```sh
dev/replay-compaction SESSION.jsonl [COMPACTION_ID]
```

By default, the command selects the latest compaction on the session's active
branch; an entry ID selects a specific one. It saves `original.md`, `new.md`,
the input and instructions, and token usage in a private temporary directory
for manual comparison. The session file is never modified; failed requests
retain the replay inputs.

Replay uses the recorded cut point and previous checkpoint, not today's retention
settings. It uses current instructions, SDK serialization, and the default model
budget; original custom compaction instructions and generation settings are not
recorded and cannot be reconstructed. Caller-added repository status is excluded
from the comparison and input when saved checkpoint metadata identifies it;
older summaries without that metadata remain intact.

The offline [replay tests](../tests/pi/replay_compaction_test.ts) run with the
focused test command above. See the [extension guide](../config/pi-agent/pi-extensions/README.md#compaction)
for compaction behavior and instruction updates.
