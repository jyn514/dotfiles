# Simplify before elaborating

These examples distinguish requested behavior from added guarantees, inspect the operation's actual scope,
and separate required distinctions from their existing representation.
They illustrate the skill's requirement-to-mechanism comparison, not permission to drop user requirements or a separate exercise for every design.

## Start with the existing operation

**Request:** Restart running sessions without losing the work their existing pause operation can save.

**Tempting design:** The restart launcher needs proof of a successful save, so build a socket protocol with save requests, receipts, status queries, and retry identities.
The protocol may be coherent, but its absence does not establish that the existing operation cannot support restart.

**Concrete comparison:** First trace the pause operation through durable save, successful exit, reopening the saved session, and restoration.
Suppose it already supports save-and-exit and leaves a record the launcher can verify.
Compare that path with the proposed protocol against the same requirements, including save failure, crash before exit, already-paused sessions, and partial restart.
A process exit alone does not distinguish a successful save from a crash; inspect whether the saved record supplies the missing evidence before inventing a receipt service.

**Decision:** If the existing lifecycle and verifiable saved record meet the preservation requirement, adapt the launcher around them rather than adding a second control interface.
If a governing requirement instead needs live sessions to acknowledge a specific save while continuing to run, save-and-exit cannot satisfy it.
Retain the necessary acknowledgment mechanism or find another supported operation; do not weaken that requirement to obtain a smaller design.

**Transfer:** Trace the operation that could produce the result, not only the proposed interface that would coordinate it.
A missing preferred transport is not proof of a missing capability.
The simpler path wins only when it satisfies the full required outcome, not because it has fewer components.

## An added guarantee creates the machinery

**Request:** Warn an agent before a later edit makes an earlier editing response's changes no longer separately selectable for a commit.
The user suggests the end of a response as a candidate boundary, not a declaration that every response must become a commit.

**Tempting design:** Persist every checkpoint across reloads, attribute dirty changes to their authors, retain all historical boundaries, and add a tool for acknowledging warnings.
Each mechanism solves a problem introduced by a stronger guarantee: durable history, precise ownership, protection of every boundary, or explicit acknowledgment state.
The design can be internally coherent without establishing that the user needs those guarantees.

**Smaller reasoning:** Separate the requested warning from the guarantees the agent added.
One in-memory checkpoint for the latest editing response and a single warning may cover the concrete failure without a checkpoint-management system.
Tracking working-copy state avoids attribution machinery, but the warning must not call unrelated dirty changes the agent's own work.
It also does not authorize committing them.

Replacing the acknowledgment tool with a fingerprint that permits only an identical retry still enforces how the agent responds.
For this advisory candidate, clear the checkpoint when issuing the warning and decline the attempted write.
The next attempt proceeds through normal write checks without a retry ticket or its invalidation rules.
A different next edit also proceeds without checking that retired boundary; this is an explicit trade-off, not proof of acknowledgment.

This candidate has weaker coverage: reloads forget it, earlier boundaries are replaced, shell writes are not intercepted, and warning retires the boundary.
Present those differences and confirm the coverage before selecting it; do not silently reinterpret a requirement to protect every boundary as permission to protect only the latest one.
If durable protection, attribution, or explicit approval is actually required, keep that requirement and justify the machinery against it.

**Decision:** In this case the user accepted the advisory version, including retirement on warning.
Persistence, historical retention, attribution, an acknowledgment tool, and a retry fingerprint were unnecessary.
The simplification came from rejecting unrequested guarantees, not from making their implementation less reliable.

**Transfer:** Before designing a retry service, history store, or coordination protocol, name the guarantee that requires it and where that guarantee came from.
For an advisory feature, distinguish delivering information from enforcing the recipient's response.
An agent-selected guarantee is a candidate to discuss, not a governing requirement.

## The existing primitive changes the unit of work

**Request:** Before writing a file, check whether an earlier checkpoint remains selectable by an existing patch splitter, `agent-split`.

**Tempting design:** Construct a hypothetical repository tree for every proposed write, then compare the checkpoint with that tree.
Treat temporary-tree construction, unrelated file metadata, and whole-repository materialization as implementation problems to solve.
Claim that the entire checkpoint remains selectable, tracking an expected-current revision and updating it after every write to detect intervening changes.

**Inspection:** Follow the existing splitter from its caller through diff production to the containment decision.
In this case containment is decided per file: one file's selection does not borrow allowances from another.
A structured edit or write changes one target file, and Pi's write operation already receives its exact proposed contents.
The broader representation was an assumption, not a requirement.

**Smaller reasoning:** Read the target's parent and checkpoint versions and compare them with its actual current and proposed contents.
Warn only when the checkpointed changes in that file remain selectable now but would not after the proposed write.
Use temporary directories containing just that path and reuse the splitter's canonical diff production and containment rules.
Do not substitute an overlapping-lines heuristic or reimplement Pi's text replacement.
If no supported read-only entrypoint exists, propose exposing the existing decision rather than treating private functions as a public API.

Make the claim match that comparison: "This edit would make the checkpointed changes in this file no longer separately selectable."
Do not claim that the entire checkpoint is still selectable.
With file-specific coverage accepted, direct comparisons replace the expected-current revision and its after-write updates.
Unrelated checkout changes need not invalidate the checkpoint; a changed parent/base still does.
A more precise claim removes bookkeeping, but cannot replace a required whole-checkpoint guarantee without approval.

**Decision-changing check:** Run the existing authored containment fixtures with both multi-file and target-only diffs.
Agreement supports removing whole-tree materialization from the proposal.
A disagreement requires inspecting the dependency it exposes before claiming file independence.
This check addresses diff scope; it does not establish protected-repository access, write interception, cancellation, or checkpoint lifecycle behavior.

**Decision:** In this case the fixture comparison agreed, supporting a target-file comparison without copying unrelated files into the hypothetical result.
The user also accepted file-specific warnings and removal of expected-current revision tracking.
That acceptance selects the coverage; the fixture results do not establish lifecycle correctness or a completed implementation.

The final write path can also be shared: accepted and checker-unavailable outcomes converge on the same target verification and cancellation checks.
After retirement on warning, the next attempt uses that same path; there is no special retry bypass.
Remove duplicated enforcement, not its safety requirements.

**Transfer:** Before designing around a large intermediate representation, inspect what the underlying operation actually consumes.
A dependency trace may settle the choice; otherwise test the narrower representation before building the broader one.
Match the claim to the inspected scope instead of maintaining broader state solely to support an unrequested promise.
Do not generalize file independence to operations whose decisions depend on several files together.

## Preserve the distinction, not its machinery

**Problem:** Ninja must distinguish an input learned from dependency metadata from an input explicitly named in the build manifest.
If a metadata-only input is missing and has no known producer, planning must not reject it as a missing source file; a missing manifest input with no producer still requires an error.
The older representation gave a dependency-discovered input a synthetic `phony` producer edge to obtain that behavior.

**Concrete trace:** In Ninja's `DyndepBuildDiscoverOutputAndDepfileInput` regression test, `out.d` first names `tmp.imp` as an input of `out`, creating a synthetic producer for `tmp.imp`.
Later, a dynamic-dependency file identifies `tmp.imp` as another output of the real command that produces `tmp`.
The synthetic producer made this look like two rules generating the same file.
The [2021 repair](https://github.com/ninja-build/ninja/commit/fa577b6d5364d103e57784ba5d6efa973b96a5c3) marked dependency-loader edges and allowed the real producer to replace only that synthetic edge.
It did not permit replacing a genuine competing producer, including a manifest-authored `phony` rule.

**Smaller representation:** The [2023 simplification](https://github.com/ninja-build/ninja/commit/a744eea2b6c9b37024b12e749e61170e5c87d171) removed those synthetic edges and their special replacement path.
A node flag retained the distinction needed by missing-input handling, and manifest insertion cleared that flag even when the node already existed.
Planning checked the flag directly when a missing node had no producer.
In the revised regression test, `tmp.imp` has no producer after loading `out.d`; the dynamic-dependency file then supplies its real producer without a replacement exception.
The test still expects the commands to build the dependency file, produce `tmp` and `tmp.imp`, and finally build `out`, in that order.

**Limits and transfer:** The distinction remained necessary; representing it as a producer did not.
The patch retained the multiple-producer error, and tests still specify rejection of genuine competing producers and missing manifest inputs.
This account rests on patch and test-source inspection, not an executed reproduction.
This bounded representation change does not show that all build-graph complexity is unnecessary.
For a similar refactor, compare the required behavior with the proposed representation: this case removed placeholder lifecycle and reconciliation while preserving the information their consumers actually needed.
A replacement that merely deleted the edges without retaining missing-input provenance would not preserve the requirement.
