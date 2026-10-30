---
name: delegation
description: Divide and coordinate work among agents. Use before spawning or assigning subagents, splitting work among running agents, deciding whether to wait for a worker, or integrating delegated results. Covers implementation, research, review, and writing. Does not authorize new work, replace domain-specific procedures, or govern human approval requests.
---

# Delegation

## Choose work and keep ownership

Derive the outcome and acceptance condition from the user's request, not the worker's assignment.
Delegate only authorized work that advances that outcome or resolves a demonstrated prerequisite.
Prefer doing small inspections and integration repairs directly when delegation would add a handoff without useful independence or capability.

Assign bounded outcomes, not isolated components.
Prefer one worker owning the result from producer through consumer, including its acceptance check.
Give the worker authority for the ordinary checks, failure inspection, and in-scope corrections its assigned activity permits.
For implementation assignments, include edits and checks through the first intended-consumer result without returning for permission at each step.
Require the worker to return before making an unresolved consequential choice, crossing an ownership conflict, or exceeding the assignment's permitted effects or resource limits.
Do not split routine preparation and execution into separate approval handoffs; retain explicit user-imposed limits and approvals.
Split the outcome only when independent execution saves time or ownership or capability constraints require separate workers.
The parent remains responsible for coordination and integration.

For coupled implementation with unsettled shared contracts, use [the shared-contract check](references/shared-contracts.md).
Reuse settled contracts; separate files alone do not establish independence.

## Give a self-contained assignment

Prefer references to accessible canonical requirements, procedures, and evidence over restating them.
A self-contained assignment names what to read and supplies task-specific decisions, ownership, overrides, and otherwise unavailable context.
It need not reproduce the referenced material.

Provide the worker with:

- The governing question or outcome, why it advances the user's overall goal, acceptance condition, current evidence, and uncertainty.
- Relevant inputs and procedures, with their full text or resolved paths when the worker cannot discover them.
- Applicable repository/shared rules and semantic distinctions; do not assume the worker inherits the parent's context.
- Ownership and shared contracts, permitted effects, protected work, and explicit holds.
- The expected result, required checks, remaining integration work, and useful evidence to return.

Request the smallest sufficient evidence set for the receiving agent to judge the result and take its next action.
Preserve the task's purpose, consequential constraints and access to underlying evidence; brevity is not a reason to omit them.
Reuse applicable tests, logs and artifacts; require new evidence only for a missing or invalidated claim.
Summarize the result, unresolved issues and evidence locations in the handoff rather than reproducing the evidence or creating another report format.

### When prescribing a prerequisite or method

Before prescribing a prerequisite or method that constrains execution, check governing guidance or actual implementation for its necessity and availability.
Do not make permission conditional on an assumed mechanism.
If the workflow is uncertain, include bounded inspection within the assignment's permitted activity rather than prescribing an unverified method as a prerequisite.
For example, require regeneration only after establishing that the target is generated and identifying its source; an authoritative data file may instead require direct edits.

### When an assignment would add a resource owner

When an assignment would add a process, container, network, daemon, cache, store, or lifecycle owner, include the architecture owner's reuse dispositions.
Cover nearby existing resources.
Do not encode a new resource as settled implementation work when reuse was not compared first.
If the packet lacks that comparison, assign a bounded inspection before implementation.
The worker returns the existing candidates and what requirement, if any, rejects each one.

### For full-file coverage

For assignments requiring full-file coverage, specify separate, bounded read calls.
Continue from the last line actually returned, not the requested end of a truncated range.
Require workers to finish retrievable gaps before returning;
when access or tool failure prevents completion, report the exact unread ranges and blocker.

### When selecting and coordinating a worker

Choose a worker suited to the task's judgment and cost requirements using the harness's available capabilities.
Do not expand authority because a worker or tool can perform an action.
Allow preparation and investigation to proceed when only a later command or shared-contract decision must wait.
Reconcile active worker instructions when governing decisions or agent-selected restrictions change.
Within existing authorization, state which earlier ownership limits, prescribed methods, and holds are superseded and which remain in force.
Update the affected assignments, not only coordinator summaries; a broad permission message does not resolve a conflicting specific instruction.

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

## While work is outstanding

Advance useful independent work when available; otherwise wait.
Do not invent supporting work or poll repeatedly to avoid being idle.
Hold only the operation that conflicts or needs the result, not the entire investigation.
Use [performance-investigation](../performance-investigation/SKILL.md) to decide which measurements need isolation; attribution does not automatically require controlled before/after precision.

## Integrate and verify

Inspect returned work against the governing requirement and agreed boundaries, not only the worker's local criteria.
For implementation, inspect the actual diff and acceptance evidence from the required checks through the intended interfaces.
For research and review, inspect the supporting sources or raw evidence and distinguish observation from inference.
Use [review evidence standards](../review/references/evidence.md) to inspect underlying evidence, decide what needs rerunning, and report local-only, integrated, or blocked results.
Consulting those standards does not start the full audit.
Make parent verification address the remaining uncertainty: inspect the changed work and applicability of existing evidence, rather than repeat the worker's investigation.
Record the acceptance decision and any new reconciliation in the canonical result; link to supporting evidence instead of retelling it.
Use independent review for consequential judgment, with a specific correctness question or failure class to investigate.
Proceed only within the scope supported by verified evidence, including permitted partial results.
Integrate the remaining work or resolve its blockers before starting work that depends on it.
Keep remaining integration work and holds visible in existing task state.

If producer and consumer disagree about required behavior, pause work across that boundary.
Resolve the contract from authoritative requirements or ask for the missing user decision; neither worker may silently choose it.
Continue independent authorized work while that question remains unresolved.
