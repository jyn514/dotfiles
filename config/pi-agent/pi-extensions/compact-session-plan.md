# Implementation plan: agent-authored session compaction

Status: implemented with jyn's October 27, 2026 authorization.
The 90 focused Bun checks and seven installed-Pi checks, including real-reader recovery and symlinked bundle loading, pass.
The grouped native adapter passes; broader repository checks fail on unrelated files, assertions, and environment prerequisites.
The full-run log is `target/compact-session-20261027/dev-test.log` (ignored, relative to the repository root).

## Contract

Add `compact_session` to the existing Pi extension bundle.
The active agent writes a checkpoint, passes it to the tool, and continues in the same session with that checkpoint replacing the preceding conversation in model context.
Persisted history remains recoverable through `read_session`; this is not a new session, fork, handoff, or deletion of the transcript.
System instructions, tools, and independently managed goal or worker state remain owned by their existing providers.
Compaction does not grant authority, change goal status, or resume paused work.

**Decided by the conversation:** use an extension in dotfiles, reuse [compaction.md](compaction.md) with small self-authoring adjustments, and have the tool supply the recovery locator.
Keep checkpoint-writing guidance there rather than adding a skill or duplicating it in `autonomous-work`.
**Implementation choice:** use `compact_session({ report: string })`; `report` is a checkpoint, not instructions for another summarizer.
Do not invoke a model to rewrite it.

**Implementation choice:** commit a native compaction entry at `turn_end`, after Pi persists the assistant message and its tool results.
The installed Pi exports `CompactionEntryDraft` with `firstKeptEntryId: null`, which explicitly keeps no preceding entries, and supports boundary entries plus `continue: true`.
These APIs are documented in installed Pi's `docs/extensions.md` and declared in `src/core/extensions/types.ts`.
Use them instead of editing JSONL, mutating agent messages, or passing the report to `ctx.compact({ customInstructions })`, which would request another summary.
This requires the installed Pi boundary APIs; the older locked unit-test SDK is not evidence that this path works.
No Pi fork change, dependency update, new service, or persistent pending-request store is planned.

### One request, one completed-turn transition

The tool description points to the resolved source location of `compaction.md` and says to read it before preparing the report.
Resolve this location as the existing Luna extension does, including symlinked installation.
Do not inject the entire document into every system prompt.

Validate the report with the existing nonempty-checkpoint and `Objective and authority` heading checks.
Keep its text unchanged before the caller-owned appendix; structural validation does not certify the report's accuracy.
Require this to be the only tool call in its assistant message, so the report cannot silently omit results of sibling calls that have not executed yet.
Reject the `compact_session` call in a mixed batch, leaving the other calls and old context intact.

Tool execution stages the validated report for its own session, branch, and tool-call ID, and returns a short acknowledgement that compaction is pending.
At the matching successful `turn_end`, consume that request once and return a compaction draft with `firstKeptEntryId: null` and `continue: true`.
Preserve other handlers' proposed boundary entries rather than replacing them.
Let Pi's boundary dispatcher preview and validate the returned entries; the extension does not rebuild the projection.
Do not start a second run through `sendUserMessage`, `newSession`, or handoff APIs.

Only the matching completed turn can consume the staged request.
Cancellation, an unsuccessful tool result, a session/branch change, or extension shutdown clears it without compacting another turn or session.
A rejected request retains the old context and reports why; it must not fall back to generated compaction.
Leave actual persistence and context projection to Pi, including its error handling and queued-input ordering.

### Caller-produced capture and recovery

Reuse the existing bounded repository capture and recovery-footer behavior in [luna-compaction.ts](luna-compaction.ts), sharing only the code both compaction paths need.
The appendix identifies the current session and raw capture without asking the agent to manufacture IDs or paths.
Keep `checkpointLength` so later Luna compaction excludes the caller appendix from its summarization input.
A failed repository-status probe records unknown state rather than rejecting a valid checkpoint; cancellation still cancels the transition.

Preserve Luna's existing recorded edit/write-target collection and inheritance.
Carry already-recorded targets from the active checkpoint through self-compaction so a subsequent Luna checkpoint does not lose them.
Do not add a second file-operation tracker or claim that inherited targets include intervening tool calls.
Omit target-count metadata when no such collection is available rather than reporting an observed empty list.
Keep the current distinction between ordinary history recovery through `read_session` and raw capture details, which that reader omits.
For in-memory sessions, identify the session but explicitly report the absence of a persisted recovery file.

## Implementation steps and logical commit

One coherent commit: **Add agent-authored session compaction**.
Land behavior, tests, and usage documentation together; no separate preparatory refactor is needed.

1. **Share checkpoint capture without changing automatic compaction.**
   Extract the reused validation, repository snapshot, and appendix construction from `luna-compaction.ts` into a narrowly scoped sibling helper if needed.
   Keep Luna model selection, fallback, file-operation collection, and existing persisted capture fields unchanged.
   The two callers can supply different optional capture metadata; do not require self-compaction to impersonate `session_before_compact` preparation.
   Existing Luna and replay tests must pass after this step.
2. **Add and register the tool.**
   Implement `compact-session.ts` with the tool, completed-turn handler, and scoped pending-request cleanup.
   Register it once through [index.ts](index.ts); the existing installed directory and bundle setting already cover sibling modules.
   Keep manual and automatic Luna compaction available through their current entry points.
3. **Adapt the existing instruction owner and usage section.**
   In `compaction.md`, change the opening to cover both an external summarizer and the active agent writing for its next context.
   Clarify that “output only the checkpoint” means the `report` value for self-compaction.
   Preserve the sections and authority/evidence rules.
   Update the existing Compaction section in [README.md](README.md) with tool usage, the installed-Pi requirement, recovery limits, and `/reload` instructions.
   Do not edit unrelated README changes already present in the working copy.
4. **Add focused and installed-Pi regressions.**
   Use `tests/pi/compact_session_test.ts` for validation and pending-request cases.
   Add `tests/pi/native_compact_session.mjs`, following `native_commit_boundary.mjs` for the installed SDK and disposable session/provider setup.
   Include the new native test in `tests/native/test_native_pi_native.py` so normal repository validation runs it.
   Extend the opt-in real-reader integration pattern from `native_session_reader_title.mjs` to cover a self-compacted session; do not substitute fabricated reader output.

## Verification and acceptance

Use private temporary sessions and a scripted local provider; no paid provider requests or mutation of real sessions is needed.
Run probes through `dev/test-environment` from the dotfiles root.
Install the existing locked prerequisites first as documented in [the testing guide](../../../dev/README.md#testing-and-probes).

- **Actual context replacement:** put a distinct marker in old history, call the tool through an installed-Pi agent turn, and inspect the next provider request.
  It contains the exact report and recovery appendix, but no old marker or orphaned tool-result messages.
  The session ID, configured tools, and system instructions remain unchanged, and exactly one continuation request occurs.
- **Persistence and recovery:** reopen the persisted session and verify the same compacted projection.
  Its raw history still contains the original messages and completed compaction call/result pair.
  With `PI_SESSION_SEARCH_PACKAGE_DIR` pointing to the real reader package, use `read_session` on this disposable recording to recover a pre-compaction message by the supplied session identity.
  Record a skipped real-reader check as unverified recovery integration, not acceptance of that requirement.
- **Validation and request ownership:** empty text, a missing required heading, and a mixed tool-call batch produce actionable errors without a compaction entry.
  Aborted/error turns, a mismatched tool-call ID, a branch/session switch, shutdown, and reload cannot apply a stale report.
  Repeated successful requests append one compaction each without accumulating continuation loops.
- **Queued work:** queue a user input while the compaction call completes and assert it reaches the resumed request once, in Pi's native order.
  Exercise another boundary handler alongside this extension and assert its entries are not silently dropped.
- **Capture and automatic-compaction regression:** test a failed status probe, Unicode report text, symlinked instruction lookup, and absent persisted session file.
  Then run self-compaction followed by Luna compaction: the report is included, its old caller appendix is excluded, and Luna's existing capture/target-inheritance tests still pass.
- **Instruction owner and loading:** loading the installed bundle exposes one `compact_session` tool whose description resolves the canonical document.
  Reading changed `compaction.md` requires no code reload; loading changed extension code does.
  Confirm both paths use the same document rather than copied guidance.

Focused checks after implementation:

```sh
dev/test-environment bun test tests/pi/compact_session_test.ts tests/pi/luna_compaction_test.ts tests/pi/replay_compaction_test.ts
dev/test-environment node --test tests/pi/native_compact_session.mjs
```

Also run the real-reader integration with its documented package-path opt-in and the repository's `dev/test` route.
Distinguish failed checks and unavailable integrations from successful acceptance.
Cancellation/lifecycle rejection and self-to-Luna inheritance are covered by focused tests; context replacement, persistence, queued input, and recovery also run through installed Pi.
