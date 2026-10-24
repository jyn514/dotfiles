# Preserve the latest editing response across workers

## Selected contract

A finished editing response protects its working-copy diff: for example, worker A reorganizes rules and exits, then fresh worker B extracts those rules.
Before B's structured write makes A's changes no longer separately selectable by `agent-split`, warn once and leave the file unchanged.
Protection belongs to the working copy, not a worker or parent session.

**Decided:** the dotfiles boundary harness owns the ignored `target/jj-split/commit-boundary.json` record, containing only an immutable revision ID.
At editing-response settlement it runs ordinary wrapped JJ snapshotting and captures immutable `@`; it does not call `agent-split --checkpoint`.
Equal revision IDs represent the same protected selection; there are no generation tokens.
Read-only turns and child/manager exits do not clear this record.
Only a late result matching the checked revision may retire the record; storage validation and retirement belong to that harness, not this package's manager.
An empty record means no protected selection.

Native and guest structured writes use the same production boundary integration.
Before writing, it reads the record and invokes read-only `--check-file` from the workspace cwd with `{revision, path, actual, proposed}`.
`revision` is immutable; `path` is literal workspace-relative; `actual` is retained native bytes as `{content: base64, executable: boolean}` or `null` for absence; `proposed` is base64.
The CLI derives the parent from the revision.
The harness skips unsupported file types rather than rereading or converting actual bytes.

The reply is `{status: 'preserved' | 'would-lose' | 'unusable', reason?: string}`; `would-lose` requires a reason.
Preserved permits the write and retains protection.
Would-lose retires the matching shared record before warning and blocking the write.
Unusable retires the matching record and permits the write.
Unexpected CLI failures remain ordinary nonzero commands or transport errors, not JSON diagnostic fields.
The harness's common finalization forgets the matching selection, reports the actual error once and fails open; cancellation and target changes still fail without writing.

There is no manager checkpoint ownership, cross-worker transport, restore acknowledgment, automatic commit/authorship, shell interception, new service/tool, recovery mechanism, or retained source copy.
Remove the former private helper protocol rather than maintaining compatibility between jointly changed internal callers.
Other link, pause, startup, error, and shutdown behavior stays unchanged.
Normal sandbox launchers already inject guest integration; no special user template or configuration is required.
Existing internal guest settlement requests remain permitted; they are not new model tools or splitter CLI modes.

## Implementation steps

These are logical review units, not instructions to commit or deploy.

1. **Remove worker checkpoint transport.**
   Surgically remove checkpoint maps, notification interception, restore/startup/shutdown support from `core.ts`, helper commands/listeners from `child-helper.ts`, and `checkpoint.ts` from published files.
   Delete the checkpoint peer/filter and manager handoff tests, remove their fake-child support and driver phase, preserving unrelated lifecycle fixtures.
   Run focused source-backed manager/link/pause suites.
2. **Implement shared harness ownership in the companion dotfiles change.**
   The dotfiles owner changes `commit-boundary.ts`, shared native/guest integration, storage validation/retirement, CLI `--check-file` and removal of `--checkpoint`, and domain tests.
   This checkout neither imports external production paths nor owns that implementation.
   Coordinate the exact request/reply contract above before final integration runs.
3. **Replace the workflow regression and documentation.**
   Update `test/boundary-integration.test.ts` to use production boundary integration, real JJ, and source-backed native and guest tools: A edits, settles and exits; a new manager/parent starts different B, which attempts extraction and is blocked without file changes; a read-only turn preserves protection; retry after retirement succeeds.
   Update `README.md`, `test/SOURCE-CORE.md`, and driver references to remove obsolete per-worker guarantees.

## Acceptance and verification

- In both native and guest phases, ignore `/target/jj-split/` before the baseline commit and require the shared record after A exits.
  Use ordinary `spawn_agent` for A's rules reorganization, observe completed status and process exit, then spawn B with a distinct worker/session/PID after manager recreation.
  B's separating write warns once and leaves the file unchanged.
  A later retry succeeds.
  Unrelated working-copy changes remain intact.
- Exercise a read-only turn before the warning and resumed-worker retry.
  Protection survives process and manager lifetimes; independent working copies remain isolated.
  Domain storage tests in the companion change cover cross-process latest-record retirement and equal-ID semantics rather than invented worker isolation.
- Companion native tests cover parent-to-child and child-to-parent writes when their public fixture supports those paths; do not invent a platform or new harness here.
- Run package nondomain checks while the companion is changing.
  Then run `PI_TEST_COMMIT_BOUNDARY_SOURCE=/src/dotfiles /src/dotfiles/dev/test-environment bun packages/pi-codex-subagents/test/run-source-tests.ts packages/pi-codex-subagents/test/boundary-integration.test.ts` and the full `bun run test:subagents` through the same source-backed environment.
  Keep exact commands and raw logs in ignored `.pi/checkpoint-evidence/`.

The source-backed driver and public Pi runtime described in `test/SOURCE-CORE.md` are authoritative for these tests; installed SDK tests or unconfigured skips are not substitutes.
Run final integration against the companion implementing this contract; passing the old source contract does not establish shared protection.
