# Simplify before elaborating

Compare required behavior with the guarantees and representations a proposal adds.
These examples show how to make that comparison, not permission to drop requirements or an exercise required for every design.

## Remove an intermediary where its capability is already supplied

**Request:** Simplify a sandbox connection: guest → gateway → host TCP bridge → broker on host loopback.
The gateway restricts access to selected services.

**Candidate:** Replace the bridge's handwritten forwarding loop with a networking library for buffering and half-close handling.
First check whether the bridge is needed.
Tracing supported backends shows that the VM already forwards its host address to host-loopback listeners.
The gateway can reach the broker directly, preserving its listener and session-token authentication.
A generic container backend's host address does not establish that capability.

**Decision:** Bypass the bridge on the VM backend; retain it where connectivity still needs it.
This removes a listener, forwarding loop, and lifecycle tracking without a new library.
Keep the gateway's restricted connectivity.
Check admission, disconnect propagation, and cleanup as well as reachability.
Source inspection and component fixtures support the candidate, not acceptance on an untested deployed backend.

**Transfer:** Compare retention, replacement, and bypass against the same required capabilities.
Use the smallest check that establishes what adjacent endpoints supply; fewer hops cannot replace required isolation, authorization, or lifecycle behavior.

## Start with the existing operation

**Request:** Restart sessions without losing work their pause operation can save.

**Candidate:** Build a socket protocol with save requests, receipts, status queries, and retry identities to prove a save succeeded.
Instead, trace pause through durable save, successful exit, reopening, and restoration.
Suppose it already supports save-and-exit and leaves a verifiable record.
Compare it with the protocol for save failure, crash before exit, already-paused sessions, and partial restart.
Exit alone cannot distinguish save from crash; the saved record may supply the missing evidence without a receipt service.

**Decision:** If that lifecycle and record meet the preservation requirement, adapt the launcher around them.
If sessions must acknowledge a specific save while continuing to run, save-and-exit is insufficient.
Keep the acknowledgment requirement and find a supported way to meet it.

**Transfer:** Trace the operation producing the result, not just the proposed coordination interface.
A missing preferred transport is not a missing capability.
The smaller solution wins by meeting the full outcome, not by component count.

## An added guarantee creates the machinery

**Request:** Warn before a later edit makes an earlier editing response's changes no longer separately selectable for a commit.
The suggested response boundary is a candidate, not a requirement to commit every response.

**Candidate:** Persist checkpoints across reloads, attribute dirty changes to authors, retain every historical boundary, and acknowledge warnings through a tool.
These mechanisms serve added guarantees: durable history, precise ownership, protection of every boundary, and acknowledgment state.
Their coherence does not establish a need for those guarantees.

**Comparison:** One in-memory checkpoint for the latest editing response and one warning may cover the concrete failure.
Working-copy tracking avoids attribution machinery, but must not call unrelated dirty changes the agent's work or authorize committing them.

Replacing the acknowledgment tool with a fingerprint permitting only an identical retry still enforces the response.
For an advisory candidate, clear the checkpoint when issuing the warning and decline the attempted write.
The next attempt, even a different edit, uses normal write checks without a retry ticket or the retired boundary.
That is retirement, not proof of acknowledgment.

Reloads forget this checkpoint, earlier boundaries are replaced, shell writes are not intercepted, and warning retires protection.
Present and confirm that coverage before selecting it; protecting every boundary would require a different design.
Retain persistence, attribution, or explicit approval if they are governing requirements.

**Decision:** The user accepted this advisory version, including retirement on warning.
Persistence, history, attribution, acknowledgment tooling, and retry fingerprints became unnecessary because their guarantees were unrequested, not because reliability ceased to matter.

**Transfer:** Trace a guarantee to its source before designing its protocol or store.
Distinguish delivering advice from enforcing the recipient's response; an agent-selected guarantee remains a proposal.

## The existing primitive changes the unit of work

**Request:** Before writing a file, check whether an earlier checkpoint remains selectable by the existing patch splitter, `agent-split`.

**Candidate:** Materialize a hypothetical repository tree per write, including unrelated metadata.
Claim whole-checkpoint selectability and update an expected-current revision after every write to detect intervening changes.

**Inspection:** Follow the splitter from diff production to containment.
Its decision is per file: selection in one file borrows no allowances from another.
A structured edit or write changes one target, and Pi's write already receives exact proposed contents.

Compare the target's parent, checkpoint, current, and proposed contents.
Warn when checkpointed changes in that file remain selectable now but would not after the write.
Temporary directories containing just that path can reuse canonical diff and containment rules.
Use the splitter's supported read-only interface, or propose exposing that decision; private functions are not a public API.
Neither an overlapping-lines heuristic nor a reimplementation of Pi's text replacement is equivalent.

Make the claim match the scope: “This edit would make the checkpointed changes in this file no longer separately selectable.”
With file-specific coverage accepted, direct comparisons replace expected-current revision tracking.
Unrelated changes need not invalidate the checkpoint; a changed parent/base still does.
This cannot replace required whole-checkpoint protection without approval.

**Check and decision:** Compare authored containment fixtures using multi-file and target-only diffs.
In this case they agreed, supporting target-only comparison without whole-tree materialization.
A disagreement would require inspecting the exposed dependency before claiming independence.
The user accepted file-specific warnings and removal of expected-current tracking.
These facts settle scope, not repository access, interception, cancellation, lifecycle correctness, or implementation completion.

Accepted and checker-unavailable outcomes can share final target verification and cancellation checks.
After warning retires the boundary, the next attempt uses that same path, not a special retry bypass.
Remove duplicated enforcement, not safety requirements.

**Transfer:** Inspect what an operation consumes before building a broader representation.
Use a dependency trace or test to establish that narrower inputs suffice, and match the claim to them.
File independence does not generalize to decisions spanning several files.

## Preserve the distinction, not its machinery

**Problem:** Ninja distinguishes dependency-metadata inputs from manifest inputs.
For a missing input with no producer, metadata-only provenance must not fail planning as a missing source; manifest provenance still requires an error.
The older representation supplied synthetic `phony` producer edges for dependency-discovered inputs.

**Trace:** In `DyndepBuildDiscoverOutputAndDepfileInput`, `out.d` names `tmp.imp` as an input of `out`, creating a synthetic producer.
A later dynamic-dependency file identifies `tmp.imp` as another output of the real command producing `tmp`.
The synthetic producer made this look like two rules generating one file.
The [2021 repair](https://github.com/ninja-build/ninja/commit/fa577b6d5364d103e57784ba5d6efa973b96a5c3) marked dependency-loader edges so a real producer could replace them, but not a genuine competitor, including a manifest-authored `phony` rule.

**Simplification:** The [2023 change](https://github.com/ninja-build/ninja/commit/a744eea2b6c9b37024b12e749e61170e5c87d171) removed synthetic edges and their replacement path.
A node flag retained the provenance needed for missing-input handling; manifest insertion cleared it even for existing nodes.
Planning checked the flag when a missing node lacked a producer.
The revised test leaves `tmp.imp` without a producer after loading `out.d`, then supplies the real producer through dynamic dependencies.
It still expects commands to build the dependency file, produce `tmp` and `tmp.imp`, then build `out`, in that order.

**Transfer and limits:** The distinction remained necessary; representing it as a producer did not.
Tests retain errors for genuine competing producers and missing manifest inputs.
This account rests on patch and test-source inspection, not executed reproduction.
It supports a bounded representation change, not a claim that build-graph complexity is unnecessary.
Deleting edges without preserving provenance would break the requirement; the flag removes placeholder lifecycle and reconciliation while keeping the information consumers need.
