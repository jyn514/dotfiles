#set page(paper: "a4", margin: 22mm)
#set text(size: 10.5pt)
#set par(leading: 0.65em)
#set heading(numbering: "1.1")

= Commit-boundary warning

*Status:* Implemented and tested; jyn manually verified the feature in a sandbox session, without establishing global activation or universal extension loading.
This document records the design and implementation ownership for a small advisory feature in the Pi extension bundle and the existing `agent-split` tool.
It does not authorize automatic commits.

== Problem and selected behavior

An agent can finish one useful change, then rewrite it while making another.
The final files can be correct even though `agent-split` can no longer select the earlier change separately.
Today the agent discovers this only when preparing commits.

For example, one response reorganizes shared instructions and moves a section without changing its wording.
A later response extracts that section into a skill and replaces it with a short trigger.
Selecting the reorganization alone would put the old wording at its new location, but that wording is absent from the final diff at that location.
The splitter rejects the intermediate version.
Committing the reorganization before the extraction would have preserved the separation.

At the end of an editing response, capture an ordinary Jujutsu snapshot and record its immutable working-copy revision as a candidate boundary shared by all workers in that working copy.
Before a later structured write, check whether its proposed result would cause the splitter to reject selecting the checkpointed changes in that file.
If so, retire the checkpoint and decline the write with a warning.
The agent can commit first if the separation matters, retry the same edit, or choose a different edit.
Calls started after the warning do not check the retired boundary; no retry recognition is needed.

This is an advisory boundary, not a requirement to create a commit.
The warning means that `agent-split` rejects that file's separation, not that Jujutsu cannot represent any suitable intermediate history.
It makes no claim that the entire old checkpoint remains selectable across other files.

== Deliberately limited scope

- Keep only the latest finished editing response's immutable revision ID in an ignored working-copy-local cache, not per-worker or per-session memory.
- Track working-copy state, not authorship.
  The remembered diff includes pre-existing unrelated edits; it never authorizes committing them.
- Cover structured `edit` and `write` operations before their actual writes.
- Support regular UTF-8 files and ordinary file creation in version one.
  Skip symlinks, binary files, and file-kind conversions; this narrows warning coverage, not the underlying tools' editing permissions.
- Do not preview shell commands, watch the filesystem, infer tasks, or classify user intent.
- Do not add an acknowledgment tool, user confirmation dialog, automatic commit, recovery framework, service, dependency, or public tool.
- Guarded native and guest writes, including root and fresh workers with the integration loaded, use the same record for the actual working copy.
  Protection does not depend on a worker, manager, session, or process remaining alive.
- An unusable comparison forgets the matching boundary and permits normal editing, subject to cancellation and target-state verification.
  Unexpected producer execution errors fail the checker command; the harness reports the actual error once, conditionally forgets the checked boundary, and permits editing through normal finalization.

The feature need not protect every useful boundary.
It must catch the example above without turning normal drafting into repeated approval requests.

== Ownership and integration

The boundary harness owns response settlement, ordinary wrapped Jujutsu snapshot and immutable-ID capture, the shared record, warning text, and conditional retirement.
The record is `target/jj-split/commit-boundary.json` relative to the actual working copy and must be ignored: it must never enter a Jujutsu snapshot.
Its entire payload is a JSON string containing the immutable commit ID, for example `"0123..."`.
A missing or empty file means no boundary.
Do not persist repository/root identity, parent identity, generation tokens, timestamps, or host/guest absolute paths.
The same relative path addresses each actual working copy's namespace; separate working copies do not share protection.
Host and guest path spellings are routing details, not stored identity.

The record is an ignored on-disk cache, not a retained source copy or a recovery framework.
Reloads, session and branch changes, worker exits, manager shutdown, and process restarts do not by themselves clear it.
There is no manager-owned checkpoint map, bus, handoff, or authoritative guest-worker state.
Equal revision IDs identify the same protected selection; retirement compares the checked revision, not a session or generation token.
A late result may forget only a record whose revision still equals the revision it checked; a different replacement must survive.
Capture writes a fresh temporary inode and atomically renames it over the record.
Forgetting opens the record with `r+`, reads and compares the checked ID from that same file descriptor, then truncates that same descriptor only on a match.
Never unlink the record or write another ID in place: a fresh capture therefore survives a late truncation of the old inode.
These approved, probed primitives need no helper, lock, or generation token.

The existing `agent-split --check-file` operation owns base validation, immutable revision reads, temporary materialization, canonical diff production, and containment.
It is read-only: it must not snapshot the workspace, change history, or invoke a real split.
The harness captures checkpoints with ordinary wrapped Jujutsu commands; there is no splitter `--checkpoint` mode.
An existing internal guest lifecycle capture request may remain as a thin call to these same capture and storage operations, not a separate owner or model-facing tool.
Reuse the splitter implementation rather than importing private functions into the extension or porting rules into TypeScript.

Pi's normal edit implementation continues to own argument validation, matching, line-ending handling, and proposed file contents.
Intercept its pluggable file write operation after those contents have been computed, inside its existing file-mutation queue.
Do not simulate edits separately in a `tool_call` handler.
The normal write tool needs the equivalent interception.
For `edit`, retain the target state from Pi's native read while the call runs; do not reread a newer version and treat it as the original.
For `write`, capture the target state, including expected absence for a new file, before any checker or finalization work.
These per-call values are transient, not persistent source snapshots.
A declined write must not create, truncate, or otherwise modify the target file.
The normal write tool may already have prepared parent directories; this guarantee concerns the target file, not rollback of that preparation.

In a sandbox session, intercept the guest's actual write and run the file-check operation in the guest.
Send its Jujutsu reads through the existing inspection route; do not add a proxy endpoint for the file-check operation.
The host extension must not inspect guessed host equivalents of guest paths.
The same policy applies to native and guest tools; no alternate metadata-access route is introduced.

The shared-record contract applies only where the boundary integration is loaded.
The normal sandbox-subagent wrapper explicitly injects guest tools despite `--no-extensions`; once the integration is loaded, fresh Luna sandbox workers need no special template.
Native nonsandbox subagents intentionally disable extension discovery, and the current native configuration does not list these extensions; do not assume automatic native-child loading.
This design authorizes neither global extension configuration changes nor deployment.
Runtime or image activation tests are not evidence that the current deployed worker has this integration.

== Shared capture and read-only request

An editing response ends when Pi has finished its automatic processing, not after every model/tool iteration.
Use the settled-response lifecycle; `turn_end` is too frequent and `agent_end` can precede automatic continuation.
Accumulate successful structured writes until settlement, then snapshot with ordinary wrapped Jujutsu commands, capture the immutable commit ID of `@`, and replace the shared record.
A response without successful structured writes does not replace an existing record.
A failed or cancelled attempt alone cannot establish a boundary.
Capture must exclude the ignored record itself from every snapshot.

Native and guest integrations use the same harness operations to read, replace, and conditionally forget the record.
The manager does not carry a checkpoint in guest request metadata or apply retirement metadata from a terminal reply.
Guest tools check and finalize where the actual write occurs, using the existing routing and cancellation path.
No new model-facing arguments, streaming frame, acknowledgment exchange, or lifecycle service is needed.
A transport failure remains a transport failure; do not replay a possibly completed write or query for a recovery receipt.

Before a supported proposed write, read the record and call `--check-file` from the actual workspace's current working directory.
The exact request has only these fields:

```json
{
  "revision": "<immutable commit ID>",
  "path": "<literal workspace-relative path>",
  "actual": {"content": "<base64>", "executable": false},
  "proposed": "<base64>"
}
```

Use `actual: null` for an absent target.
`actual.content` contains the bytes already observed by the native tool and `actual.executable` its executable mode; the checker must not reread the target to replace that observation.
The harness skips unsupported kinds rather than converting them into this regular-file contract.
The checker derives the workspace from its current working directory and the parent/base from the immutable revision, not from request fields.

The exact reply is `{"status":"preserved"|"would-lose"|"unusable","reason"?:string}`.
A `would-lose` reply requires a concrete reason.
`preserved` permits the write and retains the record; `would-lose` blocks with a warning and forgets the matching record; `unusable` permits the write and forgets the matching record.
There are no diagnostic, retirement, or compared-revision fields in the reply.
Unexpected producer execution errors return a normal nonzero process failure, not a status reply or diagnostic field.
The harness catches that failure, conditionally forgets the checked revision, reports the actual error once, and fails open through the existing target-verification and cancellation finalization.

== Checkpoint and comparison

The immutable revision refers to Jujutsu's existing revision storage, not new retained copies of source files.
Do not pin revisions or create persistent references to extend their lifetime.
An unresolvable revision makes the comparison `unusable`.
Version one supports a single-parent working-copy revision; other parent layouts make the comparison `unusable`.

For each supported proposed write, the harness reads the shared record and calls the file-check operation once when a checkpoint is present.
The following comparison steps belong inside that operation, not in the Pi adapter:

+ Resolve the checkpoint's parent and confirm that the current working-copy parent still matches it.
  A changed base returns `unusable`; unrelated working-copy edits do not invalidate the checkpoint.
+ Let `P` be the parent derived from the checkpoint revision, `C` the checkpoint, and `A` the actual target state retained for this call.
  Materialize only the affected path from `P` and `C`, plus `A`, in disposable storage, preserving absence, bytes, kind, and executable mode.
  Use the native tool's retained target state for `A`, not a newly snapshotted working-copy revision.
  All diffs below cover only that path; do not construct a hypothetical repository tree or fetch unrelated file contents.
  If the checkpoint has no change on this path, return `preserved` without either containment comparison.
  Otherwise, check that the checkpoint selection `diff(P, C)` is still accepted within `diff(P, A)`.
  If not, that file's boundary was already lost before this edit; return `unusable`, without blaming the proposal.
+ Make an independent copy of the materialized actual path and substitute the exact proposed file contents there.
  No checkout source files or repository history are changed by this construction.
+ Ask the same per-file containment implementation whether `diff(P, C)` is accepted within the diff from `P` to the proposed path.
  Accepted returns `preserved`.
  Rejected returns `would-lose` with the concrete rejection reason.
  Unavailable returns `unusable`.

Without a checkpoint, the adapter skips the operation.
Every completed result, missing checkpoint, skipped comparison, or caught producer execution error proceeds through the adapter's common finalization routine.
For a caught producer error, the harness conditionally forgets the checked revision and reports the actual error once before permitting the ordinary write, subject to target verification and cancellation.
A `would-lose` result becomes a warning outcome; all other results permit a write subject to that routine's checks.
A successful write leaves the shared record unchanged; no per-write revision snapshot or tracking update is required afterward.
At the next editing-response settlement, successful writes can establish a new checkpoint.

Reuse the splitter's canonical materialization and diff producer rules in `agent-split.clj`, including `diff-output` and `normalize-diff-paths`.
The producer uses `git diff --no-index --binary --no-renames`, canonical path prefixes, and lossless UTF-8 decoding.
The existing containment implementation retains authority over line occurrences, edit regions, and newline state.
Its broader binary support does not expand this extension's initial coverage.
Require lossless UTF-8 decoding and no NUL bytes in each present file version; absence is valid for ordinary file creation.
Symlinks, binary content, and conversions between file kinds return `unusable` without attempting specialized materialization.
Preserve ordinary regular-file modes when producing diffs.
Do not add a TypeScript duplicate or reduce the comparison to overlapping line ranges or matching strings.
An already-lost boundary or an unavailable comparison returns `unusable`, without blaming the proposal.
Unsupported kinds are skipped by the harness.
Unexpected producer execution errors fail the checker process; the harness reports the actual error once, conditionally forgets the checked revision, and fails open through common finalization.
Cancellation and target-state verification failures retain their own handling.

== One warning, then ordinary editing

On a rejected proposal with an unchanged target and no cancellation, conditionally forget the checked revision before returning a normal failed tool result:

#block(inset: 10pt, stroke: 0.5pt + luma(180))[
  Could not edit file: `<path>`.
  This edit would make the earlier changes to this file no longer separately selectable by `agent-split`.
  No file was changed.
  Commit first if that separation matters, or retry to proceed.
]

The checker reply retains the splitter's concrete rejection reason; the user warning does not expose it.
Do not ask the human to choose a commit boundary.
The agent remains subject to normal commit authorization and work-ownership rules.

There is no acknowledgment state or special retry path.
A subsequent call, whether identical or different, runs normally without the retired boundary; a newly recorded boundary still applies.
The warning informs the agent; it does not enforce how the agent responds.
Retiring a checkpoint does not authorize a commit or bypass the tool's normal validation.

== Common finalization

Accepted edits, unavailable comparisons, caught producer errors, calls without a checkpoint, and containment rejections converge on one finalization routine.
Subsequent attempts after a warning use this same routine, not a separate retry implementation.

+ Recheck the target against the state retained for this call, including content, file identity, or expected absence.
  Retain the verification result or error until the cancellation check completes.
+ Check the cancellation signal after asynchronous verification and before any warning or write.
  If cancelled, conditionally forget the checked revision and propagate cancellation, even if verification also failed.
+ If the target changed, conditionally forget the checked revision, fail the tool without writing, and require a fresh attempt.
  Do not apply the stale proposal or automatically recompute it.
  An inability to verify the target also fails without writing; preserve the verification error rather than reporting a containment rejection.
+ For a warning outcome, retire the compared checkpoint and return the warning without writing.
  Otherwise, invoke the underlying filesystem write.

For an `unusable` result or a caught producer error, conditionally forget the checked revision too.
All forgetting uses the shared harness operation, in native and guest execution alike.
A late outcome cannot clear a different replacement record; equality with the checked revision is the only retirement identity.
Changes elsewhere in the repository neither require an after-write tracking update nor block an otherwise valid write.

The check is advisory, not an atomic transaction over all repository writers.
Keep the existing per-file mutation queue, but do not treat it as excluding external writers.
A writer can still change the target after the final recheck.
Do not add a store-wide lock or block other agents.

== Lifecycle and failure behavior

The record survives extension reloads, session or conversation-branch replacement, and process or manager restarts.
It is scoped by its working-copy-local location, not by a remembered repository identity.
A commit that changes the working-copy parent makes the next comparison `unusable` and forgets only the matching record.
Unrelated file edits leave the record in place; changes to the target before a call are handled by its direct comparison against the checkpoint.
There is no attempt to reconstruct a boundary across a changed base or to retain unavailable source revisions.

Pass the tool's cancellation signal through the checker and its subprocesses.
Cancellation takes precedence over checker results and target-verification errors; it must propagate as cancellation, not become an unavailable comparison.
The common finalization routine performs the final cancellation check for every outcome.

A failed or cancelled write does not establish a checkpoint merely because it was attempted.
If a write may have happened but its completion is unknown, conditionally forget the checked revision and preserve the tool's original error.
Do not replay a possibly completed write automatically.

An `unusable` comparison permits the ordinary edit, not permission to bypass cancellation or target-state verification.
Unexpected producer execution errors remain normal nonzero checker-command failures.
The harness catches them, conditionally forgets the checked revision, reports the actual error once, and permits ordinary editing only through common finalization.
Only a completed containment rejection with an unchanged target and no cancellation produces the deliberate retry warning.

== Implementation references

The relevant existing owners are:

- `config/pi-agent/pi-extensions/guest-tools.ts`: host-to-guest tool delegation.
- `tools/codex-sandbox/image/tool-worker.mjs`: guest tool construction.
- Pi's `core/tools/edit.ts` and write-tool implementation: proposed writes and file mutation ordering.
- Pi's extension lifecycle declarations: settled responses, session replacement, and branch changes.
- `tools/agent-split/src/scripts/containment.clj`: the per-file containment decision.
- `tools/agent-split/src/scripts/agent-split.clj`: selected-path materialization and canonical diff production in preflight.
- `tools/agent-split/README.md` and `design.typ`: supported selections and conservative rejections.

The read-only check interface and write interception are owned by this feature's implementation.
Retain Pi's authoritative file operations and routing.

== Acceptance

The canonical fixture comparison in `target/commit-boundary/probe-containment.clj` ran the existing 54 authored text and binary cases.
It compared multi-file and target-only canonical diffs at contexts 3 and 1; all 959 assertions passed, as recorded in the adjacent `.txt` output.
This supports per-file containment equivalence for those fixtures; the binary cases test the existing splitter, not version-one extension coverage.

The read-only deployed-route probe in `target/commit-boundary/probe-protected-reads.py` fetched a regular UTF-8 source file at a saved revision and its parent.
It used the existing proxy route with child-scoped `JJ_PROXY_INSPECT=1`, and a repeated immutable-revision read returned identical bytes.
The adjacent `.json` records the IDs, byte counts, and digests.
This verifies those deployed immutable-file reads, not checkpoint capture, a real containment invocation, shared-record storage, or cancellation.
No new proxy capability is required for the demonstrated regular-file reads.

The first integration case must reproduce the motivating sequence through both native and guest tools in an owned disposable repository:

+ Start with an unrelated dirty formatting hunk.
+ Perform a structured reorganization, settle the response, and confirm the ignored shared record exists.
+ Let that worker exit, start a distinct fresh worker on the same working copy, and perform a read-only response without replacing the record.
+ In the fresh worker, attempt the later extraction that makes the earlier diff unselectable.
+ Confirm one warning before any target-file mutation.
+ Retry identically and confirm the edit succeeds, with the unrelated hunk intact.

Also verify these cases:

- An independent edit that preserves containment, including a path absent from the checkpoint diff, proceeds without a warning.
- Containment materializes and reads file contents only for the affected path, even with unrelated dirty files.
  It checks the parent/base but neither tracks intervening revisions nor snapshots after every write.
- Target-only canonical text diffs retain the authored containment outcomes of multi-file diffs, including newline state.
- Ordinary UTF-8 file creation is supported; symlinks, binary files, malformed UTF-8, and file-kind conversions skip comparison and still use normal write protections.
- One file-check invocation owns base validation, revision reads, diff production, and containment; the adapter constructs no per-write Jujutsu query templates.
- The checkpoint survives successive accepted edits within the next response.
- A warning immediately retires the checkpoint even if no retry follows; it creates no acknowledgment or retry state.
- Both identical and different subsequent edits proceed without checking the retired boundary.
- A target whose checkpointed changes were already lost before the call discards the checkpoint without blaming the proposed edit.
- An unresolved checkpoint revision or changed parent discards stale state.
- Reload, session/branch replacement, worker exits, and manager/process restarts preserve the shared record without retaining source snapshots.
- With the integration loaded, guarded native and guest writes, including root and fresh workers, read the same actual-working-copy record; independent working copies remain isolated.
- Fresh sandbox workers use normal wrapper-injected guest tools without a special template; native-child checks require an explicitly loaded integration and do not establish automatic discovery.
- Every capture excludes the ignored record from the ordinary Jujutsu snapshot.
- The payload is a JSON string containing only the immutable revision, with no persisted path identity, parent, token, or timestamp; a missing or empty record means no boundary.
- Capture atomically renames a fresh inode; forgetting compares and truncates the same open descriptor without unlinking or replacing the ID in place. A late truncation cannot erase a freshly renamed capture.
- An `unusable` reply permits the ordinary edit subject to pre-write checks. Unexpected producer execution failure is a normal nonzero command failure; the harness conditionally forgets the checked revision, reports the actual error once, and fails open through those same checks.
- Another writer changes the target while the checker runs: the tool fails without writing and preserves the other writer's contents.
- An unrelated file change leaves the checkpoint in place and permits the write when its target is unchanged.
- Target-state verification failure stops the write and preserves the verification error.
- Cancellation while the checker is pending stops the checker, propagates cancellation, and leaves the target unchanged.
- All outcomes use the same finalization routine; cancellation or a changed target also prevents writing with no checkpoint or an unavailable checker.
- A warning-only response does not re-establish a checkpoint; successful writes can establish one when the response settles.
- Tool failure/cancellation does not publish a false successful checkpoint.
- Native and guest execution check the files actually being written.
- Guest checks use shared harness storage, not checkpoint request/reply metadata, manager handoff, or authoritative worker memory.
- A late result forgets only a record equal to its checked revision; a different replacement survives, while equal IDs represent the same selection.
- A lost reply never triggers automatic write replay or a recovery protocol.
- Read-only responses do not replace a checkpoint; model/tool iterations do not create extra boundaries.

Completion means those behaviors are exercised through the real tool path, using the actual containment implementation.
Compilation of this document or unit tests of an approximate overlap heuristic do not establish that behavior.
