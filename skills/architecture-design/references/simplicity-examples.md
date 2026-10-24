# Simplify before elaborating

These contrasting examples show how to distinguish requested behavior from added guarantees and inspect the operation's actual scope.
They illustrate the skill's requirement-to-mechanism comparison, not permission to drop user requirements or a separate exercise for every design.

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
