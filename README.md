# dotfiles
Configuration and options for various common Unix commands.

See the [`tools/` reference](tools/README.md) for the repository's standalone commands and executable subsystems.

Partly taken (with love) from Charles Daniels' [excellent repository](https://github.com/charlesdaniels/dotfiles).

## Maintenance

Run `dev/update-bootstrap-lock --dry-run` to preview newer plugin revisions,
release assets, and checksums. Run it without `--dry-run` to update
`install/bootstrap.lock.json` and `install/bundles.json`, then review the diff
and run `dev/test`. The updater uses `GITHUB_TOKEN` when it is already set,
but does not require or export one.

## Pi compaction

The Luna extension uses [`compaction.md`](config/agents/pi/pi-extensions/compaction.md) for one checkpoint covering
history and any split-turn prefix. If Luna fails or is unavailable, the active
model uses the same instructions; if generation fails, session history is kept.

After generation, the extension appends full `jj status` output, the session's
working directory, and a capture timestamp. Failed captures, including the
10-second timeout, report unknown state. Saved checkpoint metadata keeps this
caller-produced block out of the next summarization request. It is a snapshot,
not evidence of task completion; later edits can make it stale.

Before running Pi tests or `dev/replay-compaction`, install the locked
dependencies from the repository root. This requires Node/npm and Bun:

```sh
npm ci --ignore-scripts --no-audit --no-fund
```

This makes tests and replays use the locked Pi SDK instead of Bun's
auto-installed or cached version.

Run `/reload` in Pi after extension changes. Instructions are read afresh for each
compaction. Run `bun test tests/pi/luna_compaction_test.ts` for offline tests,
including native extension loading and resumed-context reconstruction.

To compare instruction changes against a saved compaction, run:

```sh
dev/replay-compaction SESSION.jsonl [COMPACTION_ID]
```

Requires Bun and the existing Pi SDK dependency. By default, it selects the
latest compaction on the session's active branch; an entry ID selects a specific
one. The command makes a live Luna request using normal Pi authentication or the
sandbox model broker, so it may incur model cost. It saves `original.md`,
`new.md`, the input and instructions, and token usage in a private temporary
directory for manual comparison. The session file is never modified; failed
requests retain the replay inputs.

Replay uses the recorded cut point and previous checkpoint, not today's retention
settings. It uses current instructions, SDK serialization, and the default model
budget; original custom compaction instructions and generation settings are not
recorded and cannot be reconstructed. Caller-added status is excluded when the
saved checkpoint offset is available; older summaries without it remain intact.
Run `bun test tests/pi/replay_compaction_test.ts` for offline replay tests.





























[Games?](https://candybox2.github.io/)
