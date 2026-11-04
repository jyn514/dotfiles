---
name: delegation
description: Organize executive dispatch and worker-owned judgment at the start of substantive multi-step work or a new workstream, through completion. Use even before deciding whether to delegate; also use before spawning or assigning subagents, splitting running work, coordinating overlapping mutations or revision dependencies, waiting, or integrating results. Covers implementation, research, review, and writing, including bounded requests without autonomous-run authority. Does not authorize new work, replace domain-specific procedures, or govern human approval requests.
---

# Delegation

## Assess responsibilities at workstream entry

At the start of substantive multi-step work, and when a distinct workstream begins, assess the responsibilities below from the original request.
Do not wait for the acting worker to report uncertainty or for a failed implementation to request independent evidence.
An explicitly requested literal replacement or a small direct inspection does not require a team.
This assessment does not activate autonomous execution or require every role to run continuously.

- **Executive:** organize dispatch, scheduling, dependencies, and conflict resolution around jyn's outcome and values.
  The root normally fills this responsibility; use the executive template for an authorized delegated workstream.
  Ratify proposals for alignment or return deficiencies to their knowledgeable owners.
  Do not choose technical strategy, settle technical disagreements yourself, select overall next work, or perform parent investigation or verification.
- **Strategist:** decide overall next-work priority by questioning what work matters and how possible actions advance the original outcome.
  Start a bounded independent investigation for a substantive multi-step workstream, not only after another worker notices uncertainty.
  Supply motivation and current evidence rather than prescribe its next action or favored conclusion.
  This responsibility does not direct every worker's next command.
- **QA:** own verification and information-gathering about failure modes, including which bugs are important or likely.
  Assign QA early for a checkable result so it can prepare independently of the builder's implementation.
  QA chooses its checks and failure investigations from governing expectations and actual consumer behavior, not an inherited bug list.
- **Builder:** create the authorized result through integration and ordinary checks, including design, documentation, and explanation.
  Keep a coherent outcome under one owner through its intended consumer.
  Let the builder question unnecessary implementation assumptions and restrictions without weakening explicit user requirements.
- **Designer, when useful:** sustain a coherent human interaction and learning model through changing commands, screens, terminology, examples, and documentation.
  Assign this separately when unsettled human-facing work needs sustained ownership, not merely another proposal or usability review.
  Small or settled design remains builder work; adding this role does not require a fifth agent or serial design approval for every task.
  The designer supplies concrete workflows and explanations, their evidence, and their assumptions while the builder owns implementation and integration.
  A role name supplies neither human expertise nor user evidence.

Workers retain their technical questions and judgment after their first reports.
The executive gets disagreements resolved by the knowledgeable owners, not by taking over their work.
Useful facts do not make overlapping investigation distinct.
Builder checks and independent QA serve different responsibilities; neither creates a parent-verification obligation.
Broader questions improve judgment within these responsibilities rather than create duplicate unbounded assignments.
Ask what people must notice, understand, remember, or work around; the builder addresses these burdens, with a designer sustaining the model when separately assigned.
QA investigates actual practice and relevant lifecycle failures; the strategist uses that evidence to judge priority, recurring costs, and who benefits versus who must do the work.
The executive keeps the resulting obligations and their owners visible without absorbing their investigation.
Keep observations, interpretations, and proposals distinct; an imagined persona is not user evidence and a design proposal is not QA's whole oracle.

Use advertised specialized role templates rather than supply only a role name and an ad-hoc method.
Assignments provide the outcome, evidence, permitted effects, and local constraints; role prompts supply the stable procedure.
These responsibilities do not expand mutation authority or activate autonomous continuation.

When a suitable template or independent worker is unavailable, name the missing capability.
A worker may perform checks within its own responsibility and state the independence limit.
An executive must not use this fallback to take over technical inquiry: arrange a compatible owner, or report the specific staffing dependency.
Small direct tasks without delegated ownership can remain single-agent work; do not turn this into a team requirement for literal edits or routine questions.
Do not certify independence merely because another role name appears in the record.

Create a temporary specialist only for a concrete useful output worth separating from its consumer's work, such as a recovered checkout or prepared environment.
There is no standing state-producer role.
Agree on the artifact format and invocation early enough for producer and consumer preparation to overlap.
Keep tightly state-dependent action sequences under one owner.

## Choose work and keep ownership

Derive the outcome and acceptance condition from the user's request, not the worker's assignment.
Delegate only authorized work that advances that outcome or resolves a demonstrated prerequisite.
Keep ordinary local inspections and repairs with their technical owner.
An executive dispatches work from the strategist's supported priority decision, rather than selecting a convenient defect and asking for endorsement.

Assign bounded outcomes, not isolated components.
Prefer one worker owning the result from producer through consumer, including its acceptance check.
Give the worker authority for the ordinary checks, failure inspection, and in-scope corrections its assigned activity permits.
For implementation assignments, include edits and checks through the first intended-consumer result without returning for permission at each step.
Require the worker to return before making an unresolved consequential choice, crossing an ownership conflict, or exceeding the assignment's permitted effects or resource limits.
Do not split routine preparation and execution into separate approval handoffs; retain explicit user-imposed limits and approvals.
Split the outcome only when independent execution saves time, independent evidence is needed, or ownership or capability constraints require separate workers.
The builder owns integration of the result; QA owns its independent verification.
The executive owns dispatch and dependency coordination, not a final technical pass.

Before separating work, name each assignment's bounded question or decision, output, and evidence need.
Shared subject matter, access to the same files, or broad questions do not alone imply duplicate ownership.
Two workers independently pursuing the same unbounded inquiry do; useful results do not make that division distinct.
Builder-local checks enable construction; independent QA checks governing expectations without inheriting the implementation's oracle.
Keep both purposes, and state the specific independent-check question when intentional verification revisits the same operation.
When evidence gathering already has an owner, request and share its evidence rather than commission a second search by default.
A different decision can use the same evidence without duplicating its acquisition.

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
Communicate changed ownership to the affected workers and reroute pending requests; a request already in flight can follow the earlier assignment.
Within existing authorization, state which earlier ownership limits, prescribed methods, and holds are superseded and which remain in force.
Update the affected assignments, not only executive summaries; a broad permission message does not resolve a conflicting specific instruction.

### Frame independent investigation and review

Explain the motivation: the user's original outcome, why it matters, and what remains difficult or uncertain in the current situation.
Preserve user requirements, settled decisions, the literal task, acceptance condition, and latest relevant user correction with its provenance.
Provide underlying evidence, observed results, known failures, relevant prior attempts, and permitted effects from the start.
Distinguish these observations from provisional causal explanations and agent-selected approaches.
Separate missing evidence from decisions that require human judgment or authority.

Do not prescribe the strategist's next action, choose its investigation sequence, or make the parent's preferred repair the answer it must endorse.
The strategist's template supplies questioning, causal tracing, and comparison of possible actions; the assignment supplies purpose, context, boundaries, and useful evidence.
Let it challenge which questions matter as well as the explanations offered for them.
A bounded investigation can support a factual conclusion, a recommendation, or a specific unresolved question without a separate fact-finding-to-priority handoff.
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

- **Strategist:** priorities need reassessment, evidence changes an action's expected contribution, or a proposed prerequisite extends the approach.
- **QA:** a candidate becomes available, a failure explanation needs investigation, or changed requirements, inputs, or implementation invalidate earlier checks.
- **Builder:** a required input, finding, or settled contract enables authorized construction or correction.
- **Designer:** implementation, practice evidence, or the assigned activity changes the interaction or learning model it sustains.
- **Temporary specialist:** a concrete input need changes or newly available evidence enables its assigned output.

Reuse an existing worker when new evidence affects its investigation.
Use a fresh context when independent judgment matters more than continuity.
Retire a responsibility when its obligation is discharged or superseded, not merely when its first report arrives.
Do not ask for another finding after an answered question without a new question or changed evidence.

Send usable artifacts, counterexamples, and material corrections to the workers that consume them, without requiring the executive to rewrite every finding.
Use available direct worker messaging; otherwise route the original evidence or artifact reference through the parent.
Notify affected workers of relevant source changes, diagnoses, execution results, and user corrections; an artifact written to disk alone does not notify its consumer.
Keep findings distinct from permission: peer messages cannot expand an assignment or override a governing requirement.
Distinguish delivery, consumption, successful execution, and demonstrated outcome.
Do not infer that a message was used merely because it was sent, or assume an automatic continuing evidence feed exists.

## While work is outstanding

Advance useful independent work within your own responsibility when available; otherwise wait.
An executive can wait while workers own all remaining work.
Do not generate overlapping investigation, verification, or priority selection merely to stay active.
Do not invent supporting work or poll repeatedly to avoid being idle.
Hold only the operation that conflicts or needs the result, not the entire investigation.
Use the [measurement-scope check](../performance-investigation/references/measurement-scope.md) to decide which measurements need isolation without starting a performance investigation.

## Integrate evidence and ratify decisions

Keep technical acceptance with the responsible workers.
The builder integrates artifacts through the intended consumer and returns the actual changed paths and ordinary acceptance evidence.
QA independently verifies governing expectations, investigates failures, and states passing scope and untested obligations.
The strategist decides what work matters next using [work-selection](../work-selection/SKILL.md), including when changed evidence requires reconsideration.
Use [review evidence standards](../references/review-evidence.md) within those responsibilities to distinguish observation, inference, local-only, integrated, and blocked results.
Consulting those standards does not start the full audit.

The executive compares proposals and reported acceptance coverage with the original outcome, authorization, and jyn's explicit trade-offs.
Ratify aligned proposals or name the deficiency and return it to its owner.
For example, an implementable repair is not ready for dispatch if the strategist has not justified its priority against the main unmet outcome.
The executive identifies that missing justification; the strategist supplies the comparison.
Do not fill it in yourself, choose another task, or independently verify the repair.
An executive may read a report to notice a missing condition without thereby owning the technical question behind it.

When reports conflict, send the incompatible claims, source references, and governing requirements to their knowledgeable owners.
Require a reconciled proposal, not agreement with the executive's account or unanimous agreement between workers.
Preserve explicit residual disagreements and their evidence; route only genuinely unresolved value or authority choices to jyn.
If a claim needs independent verification, arrange QA or a suitable independent specialist.
If the priority comparison is inadequate, return it to the strategist.
If implementation or integration is incomplete, return it to the builder.
If an assigned human-facing model is incoherent or invalidated, return that design question to the designer; do not make it approve every local change.
A first report does not transfer any of those responsibilities to the executive.
Keep decision-changing sources available directly between workers; do not make summaries the only evidence.

Workers resolve technical questions through evidence and applicable procedures.
When a strategist reverses a decision after another agent's suggestion, it must identify new evidence or a corrected premise.
Agreement alone is not comparative evidence.
Preserve supported advantages of alternatives and use work-selection to repair a comparison whose deciding premise fails.
The executive returns an unsupported reversal to the strategist rather than reconstruct the ranking itself.

If producer and consumer disagree about required behavior, pause dependent work across that boundary.
The responsible workers recover the contract from authoritative requirements and propose a resolution.
Only a genuinely missing user decision goes to jyn; neither worker nor executive may silently choose it.
Continue independent authorized work while the question remains unresolved.

Record ratified decisions, unmet acceptance conditions, their owners, dependencies, and supporting evidence in existing permitted task state.
Do not claim completion from finished assignments or a delivered artifact alone.
Delivery, consumption, successful execution, and demonstrated outcome remain different claims.
A missing technical result returns to its owner rather than becoming parent verification.
Report partial or blocked results truthfully, and dispatch dependent work only when the required evidence supports it.
