---
name: autonomous-work
description: Pursue an explicitly requested autonomous or unattended task, or an active user-authorized tracked goal, through verified completion. Use for implementation, research, writing, planning, or review, including resuming an established run. Do not use for an ordinary bounded request without run authority, passive goal tracking, or a paused, blocked, or budget-limited goal alone. Preserve the requested activity; autonomy does not authorize implementing a plan, fixing review findings, publishing writing, or other unrequested effects.
---

# Autonomous work

Confirm either an explicit autonomous-run request or an active user-authorized tracked goal before starting.
An active user-authorized tracked goal supplies run authority within its objective; an ordinary request for a fix, answer, draft, plan, or review does not.
Reassess activation when the task changes; having this skill in context does not activate it for the next task.
Respect paused, blocked, and budget-limited states and the harness's resume requirements.
An inactive goal is saved state, not permission to continue.

This skill owns run-level work selection, dependency readiness, iteration, resumable state, and stopping.
Activity-specific skills own their procedures; goal tools own status changes and budgets.
Autonomy authorizes persistence within the task, not a different activity or additional effects.

u got this buddy <3 i believe in u

## Establish authority and acceptance

Read the request, governing requirements, repository guidance where applicable, and current artifacts or evidence.
Identify the permitted activity, protected work, acceptance criteria, and effects before starting:

- **Implementation:** deliver the requested behavior through its intended consumer and required checks, within the authorized change scope.
- **Research:** answer the agreed question from evidence, distinguishing supported conclusions, conflicting sources, and unresolved uncertainty.
- **Writing:** produce or revise the agreed artifact against its brief and factual requirements; drafting does not authorize publication.
- **Planning:** produce a usable, evidence-grounded plan with dependencies and uncertainties; planning does not authorize execution.
- **Review:** complete the agreed inspection and substantiate findings; review does not authorize repairs.

Do not invent human approval or substitute a different activity for an unmet result.
A review-ready artifact can complete a draft request, but not a goal that explicitly requires the user's approval.
Ask before changing scope, acceptance criteria, preservation requirements, permissions, or the selected design.
Do not ask again for investigation, edits, or repairs the task already authorizes; a failed attempt does not impose a one-attempt limit.

Derive remaining outcomes from the full governing request, not worker assignments, progress summaries, or optional cleanup.
Narrowing an investigation does not narrow the goal or milestone.
In the required acceptance order, identify the next unmet condition and its observable result, current evidence, missing work, and cheapest realistic check.
Use the task's actual criteria: sources and reasoning for research, the brief for writing, feasibility for planning, inspection evidence for review, and consumer behavior for implementation.
Keep each condition open until its required evidence passes; an explicitly scoped feasibility or component result does not complete downstream obligations.

Use existing goal, plan, or session state rather than creating another tracking system.
Record acceptance cases before substantive work and refine them only within the governing scope.
Read-only work may retain state in the session; recording progress does not authorize project-file edits.
Create a harness goal only when explicitly requested; unavailable goal tools do not prevent an otherwise authorized run.

## Choose work that advances the objective

Before each task, name the acceptance case it advances and the missing evidence, reproduced failure, or demonstrated prerequisite it addresses.
Work may advance the current condition, a demonstrated prerequisite, or another independent authorized part of the objective.
Preserve required milestone order and current integration obligations; another unmet item alone does not justify abandoning them.
Keep unmet conditions and their scoped blockers visible while independent work proceeds.
Advance acceptance and integration only when governing prerequisites and required evidence permit.

Before adding prerequisite work, name the unmet dependency, the acceptance check it prevents, and the supporting evidence.
Distinguish governing requirements from restrictions introduced by the chosen approach or experiment.
Before adding instrumentation, changing a diagnostic question, or delegating prerequisite work, compare the smallest existing-tool alternative that preserves the outcome, constraints, and selected design.
Make this comparison even when the last probe produced useful partial evidence.
Reconsider approach-imposed restrictions before treating them as prerequisites.
Repair obvious mechanical failures directly when they need no new mechanism or change of question.
An unrelated bug is not a prerequisite; do not repeatedly review an unchanged boundary or add defenses for hypothetical failures.

Use [creative-inquiry](../creative-inquiry/SKILL.md) when the approach remains uncertain or local successes repeatedly fail to advance the requested outcome.
Before a diagnostic follow-up changes its question or adds instrumentation, ask which possible finding would change the next action.
Do not produce another assessment without a decision it can change.
Record permitted defaults as assumptions; leave missing judgments unresolved.
Route a genuine software-design fork to [design-deliberation](../design-deliberation/SKILL.md), not to an improvised experiment restriction.

## Compare opportunities before extending repeated work

While the run is active, reassess before extending repeated similar batches, even when they succeed.
Also reassess a chain of supporting tasks that succeeds locally without advancing the acceptance condition, even when the tasks differ and none has stalled.
Look for a more valuable next action, not necessarily another investigation.

Use a configured fresh-context scout template when available and follow its advertised caller contract without restating the procedure or supplying a preferred task.
Include evidence entrypoints for the main user activity as well as current work, so the current candidate does not define the search space.
Preserve the latest relevant user correction and its provenance; quote it only when the exact text is available.
Without a template, make a read-only search yourself: inspect an existing example of the main user activity and outcome evidence; do not claim independence.

Look beyond the current subsystem or line of inquiry for missing core capabilities, including incomplete use of existing machinery.
Choose a bounded next action without turning discovery into an exhaustive project audit.
Compare the recommendation with the strongest credible competing action as well as continuing current work.
Explain the user benefit and its evidenced or estimated scale, including the work through actual delivery, verification, and coordination.
A correct finding, novelty, coverage total, or completed batch does not establish user-facing quality or justify priority alone.
If uncertain benefit or cost determines the choice, identify the smallest check that distinguishes the competing actions rather than defaulting to the recommendation.
Do not assume an investigation will justify follow-up work or turn missing evidence into a claimed failure.
Decide when the evidence supports a recommendation or identifies a concrete blocker; do not impose a fixed lookup or time limit.

No better alternative found is a successful result; name missing context rather than inventing work.
The parent retains task-selection authority and explains why accepting a recommendation beats the competing actions under the governing constraints.
A scout report alone is not progress.
Do not scout after every tool call or repeat an unchanged search without new evidence.

## Continue independent work before waiting

Before awaiting a long-running check or milestone decision, identify valuable authorized work independent of its result and advance or delegate it.
Preserve the candidate under verification; isolate parallel edits when they would invalidate its inputs or evidence.
Serialize only dependent decisions, conflicting mutations, and resource-constrained operations, not all work toward the goal.
If no useful independent work remains, wait rather than inventing work.

Use [delegation](../delegation/SKILL.md) for assignments, shared contracts, waiting, review, and integration.
Judge returned work against the governing requirement and supporting evidence, not merely the worker's local criteria.
Keep each result's demonstrated scope and remaining obligations visible.

## Apply implementation procedures only to implementation

For implementation work, use these companion procedures when their conditions apply:

- [Design-for-change](../design-for-change/SKILL.md#design-for-testing) owns unresolved modeling, interface, ownership, invariant, and test-strategy choices.
  For an established pattern, follow the surrounding code and tests without loading it.
- [Double-check's evidence standards](../double-check/SKILL.md#evidence-and-integration-status) distinguish local/component checks, integration, and required real-input evidence.
  Consult them for milestone readiness; run the full audit only after substantial owned implementation is complete.
  A routine localized change needs a diff review and appropriate native checks, not a full audit.
- For a new independently invoked tool, use [new-tool-development](../new-tool-development/SKILL.md) to check readiness.
  This skill neither approves its artifacts nor selects its design.

For an implementation acceptance case, identify the actual entrypoint, authoritative inputs, intervening interfaces, final consumer, and cheapest realistic check.
Require end-to-end evidence unless the governing scope explicitly declares a feasibility or component milestone.
Do not replace that condition with a helper's local success.
For end-to-end implementation, two consecutive completed subtasks without a new consumer-visible result trigger approach reassessment before more prerequisite or capability work.
Attempt the nearest intended-consumer check; if it cannot run, identify the exact missing dependency and compare repair with the smallest authorized alternative.
Explicit feasibility or component milestones retain their own acceptance conditions.

Connect each handoff to the intended consumer or remove the temporary path before extending that path with another fixture-only capability.
If blocked, retain downstream obligations rather than silently deferring them.
Missing real inputs do not block integration using valid fixture inputs, but fixtures do not satisfy requirements for real-input evidence.
Where acceptance permits partial results, keep unsupported cases explicitly held while supported cases reach the consumer.
This does not narrow the milestone or certify held cases.
Reuse producer outputs that remain valid for the required consumer and repair the failing boundary; regenerate only invalidated or missing work.
If a repair displaces integration, retain integration as the next action for its acceptance condition.
Record implementation results as integrated, local-only, or blocked with the exact check and evidence.

Commit only when the task or repository policy authorizes repository changes and commits; use [commit-quality](../commit-quality/SKILL.md).
For authorized implementation runs, commit integrated results rather than waiting until the end of the session.
Do not turn read-only research or review into repository mutations to satisfy an implementation procedure.

## Record decisions and preserve resumable state

Record corrections, constraints, failed approaches, and decision-changing untried alternatives in existing authoritative task state.
Record user decisions before dependent delegation and reconcile superseded holds, questions, and worker instructions without dropping constraints that still apply.
Do not rely on compaction to retain everything needed to resume.

Before compaction, interruption, or handoff, preserve:

- the governing objective, permitted activity and effects, and protected boundaries;
- unmet acceptance conditions, next actions, and integration displaced by repairs;
- precisely scoped blockers and other independent obligations;
- completed evidence and artifact references, with their demonstrated scope;
- assumptions, pending judgments and worker effects, and checks needing rerun.

Persist only state expensive to reconstruct and use a permitted existing surface.
On resume, read that state and reconcile it with later user instructions before choosing work.
Check current artifacts, pending workers, and evidence freshness; do not replay completed mutations or trust stale summaries over current state.

## Ask, block, pause, or finish honestly

"Autonomous" does not mean jyn is gone; it means she is not actively paying attention.
Use `ask_user` when available for missing decisions and continue independent authorized work while awaiting an answer.
Do not guess missing semantics, invent approval, or certify held results.

Before declaring the run blocked, compare the dependency with the full objective and governing requirements.
Record what it prevents, supporting evidence, the input or decision needed, and independent work that can proceed.
A blocked investigation is not a blocked goal; continue useful authorized work when only one path is blocked.
Distinguish a missing external dependency from an in-scope repair or an unavailable tool for which an authorized alternative exists.
Use [creative-inquiry](../creative-inquiry/SKILL.md) if another approach could reach the same outcome with fewer assumptions.
Declare the whole run blocked only when no meaningful authorized progress remains, then explain the dependency.

At completion, compare the actual result with the original request and acceptance cases using the permitted activity's evidence standards.
Require concrete evidence for every explicit requirement and no required work remaining; a worker report or the model's confidence does not supply missing evidence or human approval.
For completed implementation, apply the review threshold above and [double-check](../double-check/SKILL.md) when required.
For research, writing, planning, and review, verify the requested answer or artifact without executing the proposed work or repairing findings unless separately authorized.

If only externally blocked obligations remain, report partial completion, exact blockers, and the next possible action.
If interrupted by time, budget, or tool failure, report paused work and preserve the next action.
Neither state is completion; do not spend the run on unrelated cleanup or change goal status outside its controls.
