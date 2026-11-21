---
name: delegation
description: Participate in coordinated work with other agents. Use when taking an assigned part of a joint activity, actually splitting or coordinating work, replacing a confused owner with fresh context, handing off evidence or artifacts, or resolving ownership conflicts. Covers all subagents, including technical workers who do not spawn agents. Not for ordinary bounded work done directly, regardless of its number of steps or files. Participation does not require a team or grant new authority.
---

# Delegation

You own part of a joint activity, not merely an isolated answer or artifact.
Understand how your assigned outcome contributes to the original request and who depends on your decisions, evidence, or result.
Your responsibility includes making consequential changes usable by those consumers; a finished report does not transfer the question to the executive.
The assignment and governing instructions bound your effects, not your role name or another worker's request.

Where these responsibilities are assigned, the executive owns dispatch, scheduling, dependencies, and ratifying alignment with jyn's outcome and values.
The strategist owns overall work priority; QA owns independent verification and failure investigation; the builder owns creation and integration.
An optional designer sustains its assigned interaction and learning model, while small or settled design remains builder work.
These are responsibilities within a joint activity, not a requirement to run five agents or seek five approvals.
Workers choose local methods and resolve technical disagreements with the knowledgeable owners; the executive organizes resolution rather than choosing the technical winner.

A peer reference names an assigned responsibility, not an agent that must exist.
Use its existing owner when assigned; otherwise keep ordinary work and checks within your assignment and return questions outside it to your caller.
Name the missing decision, expertise, or independent evidence instead of requesting a role merely because the prompt mentions it.

## Choose your responsibility

A technical owner using bounded helpers retains its own task, judgment, integration, and acceptance.
Handle ordinary bounded work directly; add helpers only when a useful independent output, required independent evidence, or parallel execution earns the handoff cost.
Neither task size nor root status selects the dedicated executive role.

Read the [executive policy](references/executive.md) when assigned to organize a workstream as its executive or when owning an explicitly authorized autonomous root run.
That policy owns the dedicated role, including its technical-ownership limits.
Bounded-helper callers and specialists participating in a joint activity use this skill without adopting that role.

For example, a bounded CLI repair can stay with its direct owner or one builder through ordinary consumer checks.
Independent verification requires a separate assignment only when jyn requires it or its evidence earns the handoff cost.
An unsettled overall-priority question can justify a strategist; neither the repair's file count nor its need for checks creates that question.

## Work through your dependencies

Notice when a decision, failure, changed requirement, or usable artifact changes another owner's next action.
Send that change and its evidence to the affected owner while it can still change the work, not only in your final report.
Use direct peer exchange when available; otherwise route the original evidence through the executive without making its summary the only source.
Communicate changed ownership and reroute pending requests; a request already in flight can follow an earlier assignment.

Communication consumes the sender's time, the receiver's attention, and the work of reconstructing context.
Give the receiver enough to make its next decision: what changed, why it matters to its question, and where the usable evidence or artifact is.
Do not commission another search merely because a peer's existing evidence also informs your decision.
Shared methods or sources do not imply competing ownership: builder-local checks and deliberately independent QA can exercise the same consumer for different purposes.
Keep observations, interpretations, and proposals distinct.
Distinguish sent, received, used, and demonstrated; putting an artifact on disk or delivering a message does not establish consumption or success.

## Record material findings when discovered

When you discover a material failure or gap in the requested outcome, update its owning issue before handing off the finding.
Record the observed failure and decisive evidence while investigation or repair continues; do not wait for the assignment to finish or the cause to be known.
Follow [durable records](../references/durable-records.md) and the project's tracker procedure.
Use an existing issue when it owns the gap; create one only when none does and your authority permits it.
Do not create a separate issue for every example of the same problem.

In a handoff reporting a material gap, include the issue reference and its current disposition, such as unresolved, repaired but unverified, or verified resolved.
Distinguish the observed failure from a suspected cause or proposed repair.
Correct the same issue when later evidence changes the finding.

If tracker mutation is outside your authority or unavailable, send an explicit recording request to an authorized owner with the finding, evidence, and remaining action.
Sending that request does not establish that the issue is recorded.
Do not delay an urgent warning to complete a tracker update; follow through on recording after sending the warning.
Recording a finding outside your assignment does not authorize investigating or repairing it.

## Retain your responsibility

Strategists follow the one-off lifecycle in [Before assigning a worker](#before-assigning-a-worker), not the continuing ownership below.

A report can finish an episode while leaving your assigned question with you.
Revisit it when relevant evidence, implementation, or requirements change, within the same authority.
Return missing evidence or an inadequate proposal to its owner instead of treating its first report as a transfer of responsibility.
A new peer message supplies evidence or a question, not permission for a different task or additional effects.
When nothing useful within your responsibility can advance, wait; retained ownership does not require constant activity or routine status messages.
Retire the responsibility when its obligation is discharged or superseded, not merely because a turn ended.

## Integrate independently useful results

For authorized implementation, distinguish the assignment's full acceptance from the unit ready to integrate.
A ticket may own several behaviors without requiring one combined delivery.
When an independently useful behavior passes its required integration checks, integrate it without waiting for unfinished sibling features.
Those checks include intended-consumer evidence and any independent verification required before integration.
Commit that result when commits are authorized.
Keep the whole assignment open until all governing acceptance conditions pass.
Do not separate changes whose correctness depends on being delivered together.

## Replace a confused owner

Reassess ownership when an agent repeats a corrected misunderstanding, returns to a rejected premise, treats its own earlier choice as a requirement, or cannot distinguish current instructions from superseded ones.
Stop dependent expensive runs and consequential mutations while resolving that confusion.
A difficult bug, failed test, long runtime or revised hypothesis alone is not evidence that the owner needs replacement.
Distinguish a new technical finding from failure to apply an already established correction.

Recover the controlling facts or instructions when they are missing.
If the same confusion returns after those facts and the correction are clear, transfer the assignment to a fresh agent before another expensive run or consequential mutation.
An owner that cannot reliably apply the corrected task should request replacement rather than another correction loop.
Do not wait for context exhaustion or treat compaction as a fresh start.
This applies to coordinators as well as workers.

1. Stop the old owner's conflicting writes before transferring ownership.
   Identify its running processes; preserve useful work on immutable inputs and do not interrupt unrelated work.
2. Preserve the working changes, decisive evidence, exact reproducer and unresolved questions.
   Distinguish verified results from unfinished implementation; replacement does not authorize resetting or discarding either.
3. Start a fresh agent without forking the old conversation.
   Give it a concise brief containing the current objective, governing decisions, permitted effects, acceptance conditions and evidence references.
   Separate established facts from hypotheses and do not copy the accumulated repair narrative or require preservation of agent-selected mechanisms.
   Recover original authority when its meaning remains uncertain rather than passing an interpretation off as a requirement.
4. Transfer ownership and reroute pending requests explicitly.
   The old owner may provide a read-only factual handoff, but must not continue competing implementation.
   Keep independent QA and valid evidence unless they share the confusion or no longer apply.

Retain responsibility for the unfinished outcome, not necessarily the original agent.
Agent replacement does not complete the assignment or expand its authority.

## Coordinate conflicting work

A shared checkout or another active agent alone does not justify a hold.
Name the concrete overlapping mutation or revision dependency before asking an owner to pause it.
When tools preserve authored work and reject a conflicting operation, accept a retry rather than stopping independent work.
Hold only the conflicting operation, release it with the resulting revision IDs, and continue independent authorized work.

## Before assigning a worker

Strategists are categorically one-off.
Give each strategist one assignment in a fresh conversation, without forking another agent's context.
Never reuse, resume, or send follow-up questions to a strategist, even to clarify or revisit its original assignment.
Every follow-up requires a new strategist with fresh context.
Do not arrange callbacks or peer updates that reopen a strategist; send later evidence to its caller.
Provide the relevant original request, evidence and prior findings in its assignment rather than continuing the previous conversation.
This rule overrides continuing-ownership and worker-resumption guidance, including role-specific guidance.

Start a fresh agent with fresh context for every new task.
A different outcome or review question is a new task, even when the subsystem and artifacts are the same.
Do not repurpose an existing worker or fork its previous task's transcript for that task.
Resume an existing worker only to continue or correct its original assignment, including its outstanding verification.

Apply the remaining assignment and scheduling procedures only when you assign or manage workers.

If you are a root agent, use your `pi-link-tools` to ensure you have a semantic `link-name` and link group set *before* you spawn your first subagent.
Once you have set a name and group, do not change them again.

Choose workers suited to the task's judgment and cost requirements; tools and capability do not expand authority.
Use advertised role templates when they fit the assigned responsibility, supplying task-specific outcomes, evidence, effects, and limits.
When assigning archivist coverage, select the `archivist` template on Pi; on other harnesses, assign an equivalent bounded source-recovery role.

### Assign bounded outcomes

Split work only when independent execution saves time, independent evidence is needed, or ownership or capability constraints require it.
Count the cost of producing, reading, and reconstructing context across the handoffs as well as the work that can overlap.
Name each assignment's question or decision, usable output, evidence need, and stopping condition.
Distinct role names do not make two unbounded versions of the same inquiry independent.
An intentionally independent check can revisit the same question; make its purpose explicit.

**Bound uncertain judgment before delegating repeated work.**
Identify which decisions the worker must make and what establishes a good choice.
If consequential choices remain unsettled, authorize one representative result before authorizing repeated implementation.
Keep the overall objective distinct from the worker's current execution authority.
The worker returns after that result; the caller reviews it before deciding whether to authorize expansion.
Review the actual result and its rationale against the intended activity—not its reports, counts or passing checks.
Expand only when that review supports a reusable decision rule.
Ask jyn when the missing criterion depends on her intent; do not require approval for established routine choices.
Reuse an already demonstrated approach rather than imposing a pilot on mechanical work.

Keep implementation, integration, and intended-consumer checks assigned through completion, not merely through an isolated patch.
Keep coupled creation and integration coherent.
When work passes to a separate integrator, agree at dispatch on an independently useful candidate they can integrate.
The handoff identifies the exact candidate, any required verification verdict and its evidence, and the candidate's benefits, costs and remaining obligations.
For overlapping edits, identify the included paths or hunks and any coupled changes, so unfinished work stays separate from the verified candidate.
Use the normal handoff message to link existing issues and artifacts.
For coupled changes, name an integration owner and use the [shared-contract check](references/shared-contracts.md).
Accountability does not require that agent to perform every task; separate files do not establish independence.
Preserve required independent verification.
Within existing authorization, include ordinary failure inspection and in-scope corrections without another permission handoff at every step.
Retain explicit user-imposed limits and approvals.
Require return before an unresolved consequential choice, conflicting ownership, or effects outside the assignment's authority or resource limits.

For work already tracked, use native issue fields to record current ownership, state and dependencies within your mutation authority.
Use labels for useful routing or waiting distinctions that existing fields do not express.
Follow project conventions and tracker procedures; do not introduce a standard label set for every run.
Update those fields when work starts, responsibility changes, a candidate enters review, or a blocker appears or clears.
Put rationale and evidence in comments rather than using comments as the only record of current state.
An agent finishing its turn does not establish issue completion.

### Give a self-contained assignment

Provide the governing outcome and why it matters, acceptance and stopping conditions, original sources, relevant corrections, and current evidence.
State permitted effects, resource limits, ownership, and protected work.
Do not repeat guidance the worker already receives.
Link task-specific procedures or evidence when the worker needs them to understand or perform the assignment.
The advertised role hint names only role-specific additions to this packet.
Do not assume a worker inherits the parent's prompt or prior reads; generic workers still need the task's responsibility framing.
Supply actual inputs and evidence entrypoints for the requested activity, not only files for your preferred mechanism.
Request the smallest evidence set the receiver needs to judge the result and take its next action; reuse applicable evidence instead of demanding new reports by default.

Before prescribing a prerequisite or method, check governing guidance or the implementation for its necessity and availability.
Do not make permission conditional on an assumed mechanism.
If uncertain, permit bounded inspection within the assigned activity instead of requiring an unverified method.
For example, require regeneration only after establishing that the target is generated and identifying its source; an authoritative data file may instead require direct edits.
A broken installed parser calls for restoring file opening with a compatible parser—not automatically a recurring startup migration.
Supply the observed mismatch and installation paths so the worker can compare one-off cleanup with a source change.
If supported setup recreates the mismatch, fixing its source may be necessary; leftover state from a one-time operation does not establish a need for persistent automation.
A required host operation that a worker cannot execute can return as a command rather than become a new guest-writable mechanism.

When an assignment would add a runtime resource or lifecycle owner, include the dispositions required by the [runtime-resource reuse check](../references/code-structure.md#justify-new-mechanisms).
If the comparison is missing, assign bounded inspection rather than encode the new resource as a settled choice.
For full-file coverage, specify bounded read calls and continue from the last line actually returned, not the requested end of a truncated range.
Finish retrievable gaps before returning; report exact unread ranges and the blocker when access or tool failure prevents completion.

### Frame independent investigation and review

Explain the original outcome, why it matters, and the current difficulty or uncertainty without prescribing the investigator's next action or favored conclusion.
Preserve explicit user choices, the literal task, acceptance conditions, permitted effects, and the latest relevant correction with its provenance.
Distinguish observations and prior attempts from provisional explanations and agent-selected mechanisms.
Let the strategist challenge which questions matter as well as the explanations offered for them.
Carry applicable evidence forward in the self-contained assignment.
A review needs the supplied design as its object, not as a required conclusion.
Include cumulative mechanisms and evidence that could disprove the approach, not just its latest patch.

### Report combined progress

When several assignments need a combined progress report to their parent, have one existing owner, such as the integrator or sub-coordinator, deliver it.
Other owners send intermediate findings directly to their consumers rather than echoing that progress upward.
Preserve independent QA verdicts and direct escalation whenever the parent must act.
When normal completion delivery is available, do not send a separate status message that merely repeats an imminent final report.

### Delegate coordination

Give a sub-coordinator responsibility for its group's local scheduling, integration, and acceptance follow-through within its assignment.
Keep local technical exchanges with the assigned workers, integration owner, and QA rather than routing them through the parent.
Report completed group outcomes, changes affecting the parent's dependencies, cross-group conflicts, and decisions outside the group's authority upward.
Keep intermediate evidence in existing artifacts and send it directly to affected owners; copy the parent only when its next action changes.
A parent receiving routine local detail returns any needed action to the group owner rather than opening a second coordination loop.

When delegating coordination, assign archivist coverage at the same time rather than waiting for overload.
Tell the archivist which workstreams it covers, including any newly delegated group.
Have it maintain sourced current decisions, superseded instructions, and unresolved questions in existing permitted task state.
The archivist reconciles records; it does not decide technical acceptance or grant authority.

## Schedule, wake, and reconcile

Allow preparation while a later action must wait, and hold only concrete conflicting operations or dependencies.
Use the [measurement-scope check](../performance-investigation/references/measurement-scope.md) when deciding which measurements need isolation.
That consultation does not itself start a performance investigation.

Workers send completion messages; respond to those events or use available wait tools when their result is the only remaining dependency.
Before waiting for worker feedback, decide when a useful finding or result should arrive using the [feedback-budget guidance](../work-selection/SKILL.md#keep-feedback-fast).
If that time passes without useful feedback, inspect the worker's recent session to identify its current operation and progress before waiting again.
If the session is unavailable or does not explain the delay, ask the owner for a brief status.
Use that evidence to decide whether to keep waiting, request findings already available, remove a blocker, or reconsider the approach.
Choose the next check from the current operation and expected result instead of restarting the same wait automatically.
A wait-tool timeout does not authorize retrying the worker's underlying operation.

For example, if a worker has finished its model calls but is still writing the report, ask for the provisional result while verification and reporting continue.

Do not reason, poll, or invent overlapping investigation merely to remain active.
Keep owners available after their first reports for outstanding work on their original assignment.
Reconcile active instructions when governing decisions, ownership, or agent-selected restrictions change.
Communicate the change to affected workers, identify superseded limits and still-binding constraints, and reroute pending requests.
A broad permission message or executive summary does not settle a conflicting specific instruction.
End reconciliation by recording the controlling sources, resolved action, residual disagreement, and affected holds released or retained in existing task state.
Send the disposition to owners whose next action changes; do not seek another round of confirmations from unaffected owners.
Reopen a resolved question only when a message supplies changed evidence or identifies an unresolved conflict with that disposition.
Check the original source or current affected artifact when needed to distinguish new evidence from a replay; delivery time does not establish decision order.
Do not infer deliberate bypass from a request already in flight under an earlier assignment.
When your tools cannot perform a required staffing or lifecycle operation, return that operation to the owning parent.
