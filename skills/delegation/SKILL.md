---
name: delegation
description: Divide and coordinate work among agents. Use before spawning or assigning subagents, splitting work among running agents, deciding whether to wait for a worker, or integrating delegated results. Covers implementation, research, review, and writing. Does not authorize new work, replace domain-specific procedures, or govern human approval requests.
---

# Delegation

## Choose work and keep ownership

Derive the outcome and acceptance condition from the user's request, not the worker's assignment.
Delegate only authorized work that advances that condition or resolves a demonstrated prerequisite.
Prefer doing small inspections and integration repairs directly when delegation adds a handoff without useful independence or capability.

Delegate bounded outcomes rather than isolated components.
Prefer one worker owning a producer-to-consumer result and its acceptance check.
Split that path only when independent execution saves time or an ownership or capability constraint requires separate workers.
The parent remains responsible for coordination and integration.

Before assigning work, identify what the worker's result will unblock and choose a useful independent next action for the parent.
Look for evidence to analyze, preparation useful under either outcome, or another independent part of the same objective.
Do not reserve invented cleanup or repeat an unchanged review merely to stay busy.
If no useful independent action exists, compare direct execution with the capability or time saved by delegation.

For coupled implementation with unsettled shared contracts, use [the shared-contract check](references/shared-contracts.md).
Reuse settled contracts; separate files alone do not establish independence.

## Give a self-contained assignment

Provide the worker with:

- The governing question or outcome, acceptance condition, current evidence, and uncertainty.
- Relevant inputs and procedures, with their full text or resolved paths when the worker cannot discover them.
- Applicable repository/shared rules and semantic distinctions; do not assume the worker inherits the parent's context.
- Ownership and shared contracts, permitted effects, protected work, and explicit holds.
- The expected result, required checks, remaining integration work, and useful evidence to return.

For assignments requiring full-file coverage, specify separate, bounded read calls.
Continue from the last line actually returned, not the requested end of a truncated range.
Require workers to finish retrievable gaps before returning;
when access or tool failure prevents completion, report the exact unread ranges and blocker.

Choose a worker suited to the task's judgment and cost requirements using the harness's available capabilities.
Do not expand authority because a worker or tool can perform an action.
Allow preparation and investigation to proceed when only a later command or shared-contract decision must wait.
Reconcile worker instructions when the user changes a decision or removes a restriction.

### Frame independent scouting and review

Assign the user's outcome or diagnostic question, not the parent's suspected fix.
Preserve user requirements, settled decisions, the literal task, acceptance condition, and latest relevant user correction with its provenance.
Distinguish these inputs from:

- Observations and results, with evidence the worker can inspect.
- Parent hypotheses, proposed actions, and their rationale, labeled as provisional rather than requirements.
- Unknowns, separating missing evidence from decisions that require human judgment or authority.

Do not hide useful hypotheses or rationale; make them challengeable without asking the worker to endorse the parent's conclusion.
Supply the actual user workflow, existing facilities, a current use example when available, and evidence that could disprove the proposed approach.
Do not limit evidence entrypoints to files for the proposed mechanism.
For review, include cumulative added mechanisms, not just the latest patch.
Ask whether the proposed work is necessary and whether a smaller approach preserves the requirements, not only how to complete it.
Before treating an unknown as a blocker, check whether independent evidence inspection or preparation can proceed without the missing result or human decision.

## Continue before waiting

A blocking wait, such as `wait_agent` or waiting for every worker, declares that no useful independent authorized work remains before the required result arrives.
Before waiting, name the exact result needed and the action it blocks.
Distinguish a true result dependency from overlapping writes, resource contention, or a restriction introduced by the chosen experiment.
Reconsider self-imposed restrictions before treating them as blockers.

Check for three concrete alternatives:

1. Analyze evidence already available.
2. Prepare inputs or checks useful under either result.
3. Advance an independent part of the same authorized objective.

Hold only the operation that conflicts or needs the result, not the entire investigation.
For example, a timed benchmark may need to wait while source inspection and probe preparation continue.
Use [performance-investigation](../performance-investigation/SKILL.md) to decide which measurements need isolation; attribution does not automatically require controlled before/after precision.
Do not replace a blocking wait with repeated status polling.
Wait when the remaining authorized work genuinely depends on the result; do not invent more work to avoid waiting.

## Integrate and verify

Inspect returned work against the governing requirement and agreed boundaries, not only the worker's local criteria.
For implementation, inspect the actual diff and acceptance evidence from the required checks through the intended interfaces.
For research and review, inspect the supporting sources or raw evidence and distinguish observation from inference.
Independent verification requires inspecting underlying evidence, not necessarily repeating execution.
Reuse evidence after confirming that it covers the relevant artifacts, scope, and intended interfaces.
Rerun checks that are missing or invalidated by changes; a worker’s summary or test count alone does not establish acceptance.
Use independent review for consequential judgment.

Apply [review evidence standards](../review/references/evidence.md) when reporting local-only, integrated, or blocked results; this does not automatically start its full audit.
Worker completion alone does not establish readiness for dependent work.
Proceed only within the scope supported by verified evidence, including permitted partial results.
Integrate the remaining work or resolve its blockers before starting work that depends on it.
Keep remaining integration work and holds visible in existing task state.

If producer and consumer disagree about required behavior, pause work across that boundary.
Resolve the contract from authoritative requirements or ask for the missing user decision; neither worker may silently choose it.
Continue independent authorized work while that question remains unresolved.
