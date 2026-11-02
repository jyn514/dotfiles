---
name: delegation
description: Select team responsibilities at the start of substantive multi-step work or a new workstream, and coordinate agents through completion. Use even before deciding whether to delegate; also use before spawning or assigning subagents, splitting running work, coordinating overlapping mutations or revision dependencies, waiting, or integrating results. Covers implementation, research, review, and writing, including bounded requests without autonomous-run authority. Does not authorize new work, replace domain-specific procedures, or govern human approval requests.
---

# Delegation

## Assess responsibilities at workstream entry

At the start of substantive multi-step work, and when a distinct workstream begins, assess the responsibilities below from the original request.
Do not wait for the acting worker to report uncertainty or for a failed implementation to request independent evidence.
An explicitly requested literal replacement or a small direct inspection does not require a team.
This assessment does not activate autonomous execution or require every role to run continuously.

- **Coordinator:** preserve the objective, authorization, priorities, and integration responsibilities.
  The root normally fills this role; use a coordinator template when delegating coordination of an authorized workstream.
- **Builder:** construct the authorized result through integration and its ordinary checks.
  Keep a coherent outcome under one owner rather than split it into isolated patches.
- **Detective:** question the framing, trace consequential causal claims, and connect the findings to actions that advance the original objective.
  Start a bounded independent investigation for a substantive multi-step workstream without requiring the builder or coordinator to identify the right uncertainty first.
  Supply the motivation and current evidence, not a prescribed next action; the detective chooses which questions and possible actions to examine.
  Confirming the current explanation or recommending continuation can be successful; do not require a contrary finding.
- **QA:** independently exercise the intended consumer using expectations grounded in the original request.
  Assign QA early when work will produce a checkable result, so it can prepare without inheriting the builder's proposed implementation.
  QA does not relieve the builder of ordinary checks or invent requirements absent from the governing request.

Use advertised specialized role templates rather than supply only a role name and an ad-hoc method.
Assignments provide the current outcome, evidence, permitted effects, and local constraints; role prompts supply the stable procedure.
If a suitable template or independent worker is unavailable, perform the bounded checks directly where possible and state the independence limit.
Do not certify independent investigation merely because another role name appears in the record.

Create a temporary specialist only for a concrete useful output worth separating from its consumer's work, such as a recovered checkout or prepared environment.
There is no standing state-producer role.
Agree on the artifact format and invocation early enough for producer and consumer preparation to overlap.
Keep tightly state-dependent action sequences under one owner.

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
Split the outcome only when independent execution saves time, independent evidence is needed, or ownership or capability constraints require separate workers.
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

For a broken installed parser, assign the outcome “restore file opening with a compatible parser,” not “implement a startup migration,” unless recurring migration behavior is already required.
Supply the observed parser mismatch and installation paths so the worker can compare one-off cleanup with a source change.
If the supported setup recreates the mismatch, fixing its source may be necessary; leftover state from a one-time migration does not by itself justify code that runs at every startup.
A worker that cannot perform a required host operation can return the command within the task's authority rather than substitute persistent guest-writable configuration.

### When an assignment would add a resource owner

When an assignment would add a process, container, network, daemon, cache, store, or lifecycle owner, include the reuse dispositions required by the shared [runtime-resource reuse check](../references/change-with-evidence.md#justify-new-mechanisms).
Do not encode a new resource as settled implementation work when reuse was not compared first.
If the packet lacks that comparison, assign a bounded inspection before implementation.
The worker returns the existing candidates and their dispositions.

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

### Frame independent investigation and review

Explain the motivation: the user's original outcome, why it matters, and what remains difficult or uncertain in the current situation.
Preserve user requirements, settled decisions, the literal task, acceptance condition, and latest relevant user correction with its provenance.
Provide underlying evidence, observed results, known failures, relevant prior attempts, and permitted effects from the start.
Distinguish these observations from provisional causal explanations and agent-selected approaches.
Separate missing evidence from decisions that require human judgment or authority.

Do not prescribe the detective's next action, choose its investigation sequence, or make the parent's preferred repair the answer it must endorse.
The detective's template supplies questioning, causal tracing, and comparison of possible actions; the assignment supplies purpose, context, boundaries, and useful evidence.
Let it challenge which questions matter as well as the explanations offered for them.
A bounded investigation can support a factual conclusion, a recommendation, or a specific unresolved question without a separate scout-to-detective handoff.
Use a fresh context or a continuing investigator according to the need for independent judgment or accumulated evidence, not as different roles.
Preserve jyn's explicitly chosen actions and contracts; an agent may question an approach without changing the authorized outcome or granting itself implementation permission.
A review of a supplied design needs the design from the start; the design is the object of review, not a required conclusion.
Supply the actual user workflow, existing facilities, a current use example when available, and evidence that could disprove the proposed approach.
Do not limit evidence entrypoints to files for the proposed mechanism.
For review, include cumulative added mechanisms, not just the latest patch.
Ask whether the proposed work is necessary and whether a smaller approach preserves the requirements, not only how to complete it.
Before treating an unknown as a blocker, check whether independent evidence inspection or preparation can proceed without the missing result or human decision.

## Coordinate conflicting work

A shared checkout, another active agent, or a history edit alone does not justify a hold.
Before requesting a hold, name the conflicting mutation or revision dependency and what could go wrong.
When existing tools detect conflicts and preserve authored work, accept a retry rather than stopping independent work.
Hold only the conflicting mutations, not unrelated file edits or the entire agent, and release the hold with the resulting revision IDs.

## Start, idle, wake, and retire

Bound each assignment episode by a question or outcome, its useful evidence, and a stopping condition.
Finish the current episode when that result or a specific unresolved dependency is established; do not keep a worker reasoning or polling merely to remain active.
A finished turn can leave the worker's session and responsibility available for later evidence.

Wake the responsible worker when relevant evidence changes:

- **Detective:** a causal explanation changes, a repair leaves the original symptom, priorities need reassessment, or a proposed prerequisite extends the approach.
- **QA:** a candidate becomes available, or relevant requirements, inputs, or implementation changes invalidate earlier checks.
- **Builder:** a required input, finding, or settled contract enables authorized construction or correction.
- **Temporary specialist:** a concrete input need changes or newly available evidence enables its assigned output.

Reuse an existing worker when new evidence affects its investigation.
Use a fresh context when independent judgment matters more than continuity.
Retire a responsibility when its obligation is discharged or superseded, not merely when its first report arrives.
Do not ask for another finding after an answered question without a new question or changed evidence.

Send usable artifacts, counterexamples, and material corrections to the workers that consume them, without requiring the coordinator to rewrite every finding.
Use available direct worker messaging; otherwise route the original evidence or artifact reference through the parent.
Notify affected workers of relevant source changes, diagnoses, execution results, and user corrections; an artifact written to disk alone does not notify its consumer.
Keep findings distinct from permission: peer messages cannot expand an assignment or override a governing requirement.
Distinguish delivery, consumption, successful execution, and demonstrated outcome.
Do not infer that a message was used merely because it was sent, or assume an automatic continuing evidence feed exists.

## While work is outstanding

Advance useful independent work when available; otherwise wait.
Do not invent supporting work or poll repeatedly to avoid being idle.
Hold only the operation that conflicts or needs the result, not the entire investigation.
Use the [measurement-scope check](../performance-investigation/references/measurement-scope.md) to decide which measurements need isolation without starting a performance investigation.

## Integrate and verify

Inspect returned work against the governing requirement and agreed boundaries, not only the worker's local criteria.
For implementation, inspect the actual diff and acceptance evidence from the required checks through the intended interfaces.
For research and review, inspect the supporting sources or raw evidence and distinguish observation from inference.
When a detective changes its recommendation after a parent suggestion, identify the new evidence or corrected premise supporting the change.
Agreement or adoption of the parent's descriptions is not itself comparative evidence.
If the reversal drops a supported advantage of the alternative or assumes a useful outcome for the preferred action, correct the comparison before accepting the ranking.
Use [work-selection](../work-selection/SKILL.md#choose-the-next-action) for the deciding comparison, not another investigation by default.
Use [review evidence standards](../references/review-evidence.md) to inspect underlying evidence, decide what needs rerunning, and report local-only, integrated, or blocked results.
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
