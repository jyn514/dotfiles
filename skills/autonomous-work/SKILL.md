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

This skill owns run authority, persistence, required acceptance order, resumable state, and stopping.
[Work-selection](../work-selection/SKILL.md) owns next-action selection, dependency justification, reassessment, and scouting within the authorized task.
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

## Keep a useful outcome graph for multi-outcome goals

For an authorized autonomous goal with multiple independently verifiable outcomes or dependent workstreams, reuse an existing issue graph or create the smallest useful one with [goal-to-issue-graph](../goal-to-issue-graph/SKILL.md) before sustained execution.
Check an existing graph against current authority, artifacts, and evidence before using it; do not blindly follow a stale task list.
Cover root acceptance, remaining outcomes, genuine dependencies, and integration checks appropriate to the permitted activity.
A single bounded task may use its existing acceptance criteria without a graph.
Use permitted existing goal, plan, tracker, or session state; this requirement neither mandates a new tracking system nor authorizes tracker mutation or project-file edits for read-only work.

Initial investigation may precede decomposition.
Keep downstream work provisional where discovery or an unresolved choice can change it; do not require an exhaustive audit before the first consumer path.
As evidence or the approach changes, update or supersede obsolete tasks and dependencies while preserving the governing outcomes.
Working from the graph means advancing an unmet root outcome and closing work on evidence, not obeying abandoned mechanisms or treating revisable agent assumptions as user requirements.
Graph work does not expand scope, change the authorized activity or effects, or resume an inactive goal.
The graph skill owns decomposition; work-selection still owns the next action.

## Select work within the authorized run

Use [work-selection](../work-selection/SKILL.md) to choose the next action, justify dependencies, and compare continuing with other authorized approaches.
Also use it before extending repeated similar batches during an active run, even when they succeed.
Keep unmet acceptance conditions and scoped blockers visible while advancing independent authorized work.
Advance acceptance and integration only when governing prerequisites and required evidence permit.

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

- Use [change guidelines](../references/change-with-evidence.md#design-choices) for unresolved modeling, interface, ownership, or invariant decisions, and [testing guidance](../references/testing.md) for test-strategy choices.
  For an established pattern, follow the surrounding code and tests without another design procedure.
- [Review evidence standards](../review/references/evidence.md) distinguish local/component checks, integration, and required real-input evidence.
  Consult them for milestone readiness; run the full audit only after substantial owned implementation is complete.
  A routine localized change needs a diff review and appropriate native checks, not a full audit.
- For a new independently invoked tool, use [new-tool-development](../new-tool-development/SKILL.md) to check readiness.
  This skill neither approves its artifacts nor selects its design.

For an implementation acceptance case, identify the actual entrypoint, authoritative inputs, intervening interfaces, final consumer, and cheapest realistic check.
Require end-to-end evidence unless the governing scope explicitly declares a feasibility or component milestone.
Do not replace that condition with a helper's local success.
Before extending prerequisite or capability work without a new consumer-visible result, attempt the nearest intended-consumer check.
If it cannot run, identify the missing dependency and use work-selection to compare repair with the smallest authorized alternative.
Connect each handoff to the intended consumer or remove the temporary path before extending it with another fixture-only capability.
If a repair displaces integration, retain integration as the next action for that acceptance condition.
If blocked, retain downstream obligations rather than silently deferring them.
Missing real inputs do not block integration using valid fixture inputs, but fixtures do not satisfy requirements for real-input evidence.
Where acceptance permits partial results, keep unsupported cases explicitly held while supported cases reach the consumer.
This does not narrow the milestone or certify held cases.
Reuse producer outputs that remain valid for the required consumer and repair the failing boundary; regenerate only invalidated or missing work.
Record implementation results as integrated, local-only, or blocked with the exact check and evidence.

Commit only when the task or repository policy authorizes repository changes and commits; use [commit-quality](../commit-quality/SKILL.md).
For authorized implementation runs, commit integrated results rather than waiting until the end of the session.
Do not turn read-only research or review into repository mutations to satisfy an implementation procedure.

## Record decisions and preserve resumable state

Record corrections, constraints and their sources, failed approaches, and decision-changing untried alternatives in existing authoritative task state.
Keep governing requirements distinct from revisable agent choices in saved state; summaries must not promote the latter into user instructions.
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
For completed implementation, apply the review threshold above and [completion review](../review/references/completion.md) when required.
For research, writing, planning, and review, verify the requested answer or artifact without executing the proposed work or repairing findings unless separately authorized.

If only externally blocked obligations remain, report partial completion, exact blockers, and the next possible action.
If interrupted by time, budget, or tool failure, report paused work and preserve the next action.
Neither state is completion; do not spend the run on unrelated cleanup or change goal status outside its controls.
