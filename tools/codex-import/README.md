# Repair the Codex session index

[`codex-import`](../../bin/codex-import) repairs missing synced sessions in Codex's local index while other Codex sessions run.

Use this when synced rollout files exist locally but sessions are missing from the resume picker.
It requires Codex on PATH and Python 3.11 or later for `tomllib`.
`CODEX_HOME` selects the destination home (default `~/.codex`) and must name an existing directory.

```sh
codex-import
codex-import --force
```

## Automatic startup repair

The [`codex` wrapper](../../bin/codex) runs it before interactive startup; import failures print a warning and startup continues.
Administrative commands, help, version checks, and noninteractive commands such as `exec` skip startup import.

## Receipt and invalidation

A receipt in `CODEX_HOME/codex-import-receipt.json` avoids launching an app-server when index coverage and previously scanned unindexed files are unchanged.
Indexed sessions can keep growing without invalidating the receipt.
New files, changed unindexed files, deleted paths, lost index coverage, configuration changes, and replaced executables trigger a full repair.
The fast path reads Codex 0.162.1's `state_5.sqlite` schema without modifying it; unsupported layouts and custom `sqlite_home` configuration fall back to full repair.
Use `codex-import --force` to bypass the receipt, including when retrying a file Codex silently omitted during an earlier scan.

## Full repair and compatibility

Full repair starts a temporary `codex app-server --stdio` and pages through `thread/list` with scan-and-repair enabled for current and archived sessions, across providers and source kinds.
It leaves the persistent daemon running and does not resume sessions, reset the backfill marker, or edit SQLite directly.
Codex owns the index repairs; transcripts stay unchanged.

## Results and failure recovery

Completion reports the number of sessions listed, not the number newly imported or a guarantee that every rollout parsed successfully.
On failure, completed page repairs may remain; retry `codex-import`.
The scan-and-repair behavior was verified with Codex 0.162.1; it depends on Codex's implementation of `thread/list`.
