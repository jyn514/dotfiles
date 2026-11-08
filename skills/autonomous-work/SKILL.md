---
name: autonomous-work
description: Organize an explicitly requested autonomous or unattended root task, or an active user-authorized root goal, through verified completion as an executive. Use for implementation, research, writing, planning, or review runs, including resumption. Delegated assignments do not inherit the parent's autonomous mode or require this skill; an explicitly authorized delegated run retains its assigned role. Not for ordinary bounded requests without run authority, passive goal tracking, or paused, blocked, or budget-limited goals alone. Preserve the requested activity and effects; autonomy does not authorize implementing a plan, fixing review findings, or publishing writing.
---

# Autonomous work

Before starting, confirm either an explicit request for an autonomous run or an active, user-authorized tracked goal.
An active goal authorizes work only within its objective.
An ordinary request for a fix, answer, draft, plan, or review does not authorize an autonomous run.
Reassess activation when the task changes; having this skill in context does not activate it for the next task.
Respect paused, blocked, and budget-limited states and the harness's resume requirements.
An inactive goal is saved state, not permission to continue.

## Establish the run owner

Every autonomous root is an executive.
For a root run, read [delegation](../delegation/SKILL.md), its [executive procedure](../delegation/references/executive.md), and the installed executive role body through delegation's root-executive route before organizing the run.
The root keeps technical creation, investigation, method selection, and verification with delegated technical owners.
It does not retain direct technical ownership by calling the task bounded or omitting other roles.
Use existing assigned owners or assign the technical work within the root run's authority and resource limits.
If those limits prevent required delegation, return that staffing dependency rather than taking over the technical task.

An ordinary delegated assignment does not inherit the root's autonomous mode and needs no autonomous-work read merely because its parent runs autonomously.
A delegated worker reads this skill only when its own task has explicit autonomous-run authority or an active user-authorized goal.
It applies continuity and acceptance rules within its assignment without becoming an executive or transferring implementation and verification judgment to the parent.

This skill owns run authority, persistence, required acceptance order, resumable state, and stopping.
[Work-selection](../work-selection/SKILL.md) owns next-action selection, dependency justification, reassessment, and scouting within the authorized task.
Activity-specific skills own their procedures; goal tools own status changes and budgets.
Where these responsibilities are assigned, apply acceptance duties through their owners: the builder integrates, QA independently verifies and investigates failures, and the strategist decides overall next-work priority.
A delegated technical owner performs ordinary implementation and checks without separately staffing QA, a strategist, or a designer.
The autonomous root remains executive even when one technical owner can complete the task.
The executive preserves scope, dispatches work, coordinates dependencies, and ratifies alignment; it does not perform a parent technical pass.
Use delegation's shared responsibility guidance when evidence or a proposal is inadequate.
Autonomy authorizes persistence within the task, not a different activity or additional effects.

u got this buddy <3 i believe in u

## Establish authority and acceptance

Read the request, governing requirements, repository guidance where applicable, and current artifacts or evidence.
Before starting, identify the permitted activity, protected work, acceptance criteria, and authorized effects:

- **Implementation:** deliver the requested behavior through its intended consumer and required checks, within the authorized change scope.
- **Research:** answer the agreed question from evidence, distinguishing supported conclusions, conflicting sources, and unresolved uncertainty.
- **Writing:** produce or revise the agreed artifact against its brief and factual requirements; drafting does not authorize publication.
- **Planning:** produce a usable, evidence-grounded plan with dependencies and uncertainties; planning does not authorize execution.
- **Review:** complete the agreed inspection and substantiate findings; review does not authorize repairs.

Do not invent human approval or substitute a different activity for an unmet result.
A review-ready artifact can complete a draft request, but not a goal that explicitly requires the user's approval.
Do not ask again for investigation, edits, or repairs the task already authorizes; a failed attempt does not impose a one-attempt limit.

Derive remaining outcomes from the full governing request, not from worker assignments, progress summaries, or optional cleanup.
A narrower investigation does not narrow the goal or milestone.
Follow the required acceptance order.
For each unmet condition, keep its observable result, current evidence, missing work, and responsible owner visible.
The technical owner chooses the cheapest realistic check; an executive returns missing evidence to that owner instead of investigating it.
Use the task's actual criteria: sources and reasoning for research, the brief for writing, feasibility for planning, inspection evidence for review, and consumer behavior for implementation.
Keep each condition open until its required evidence passes; an explicitly scoped feasibility or component result does not complete downstream obligations.

Use existing goal, plan, or session state; do not create another tracking system.
Record acceptance cases before substantive work, and refine them only within the governing scope.
Read-only work may retain state in the session; recording progress does not authorize project-file edits.
Create a harness goal only when explicitly requested; unavailable goal tools do not prevent an otherwise authorized run.

An autonomous root requires technical ownership separate from its executive responsibility, not a full role catalogue.
One technical owner may suffice; additional workers need concrete expected value or requested independence, not merely a substantive or multi-step task.
Use [delegation](../delegation/SKILL.md) for shared responsibility, assignments, and worker lifecycles.
Preserve responsibilities already assigned without automatically staffing QA, a strategist, or a designer at startup or a new workstream.

## Use an outcome graph when needed

### For multi-outcome goals

For an authorized autonomous goal with multiple independently verifiable outcomes or dependent workstreams, reuse an existing issue graph or create the smallest useful one with [goal-to-issue-graph](../goal-to-issue-graph/SKILL.md) before sustained execution.
Check an existing graph against current authority, artifacts, and evidence before using it; do not blindly follow a stale task list.
Cover root acceptance, remaining outcomes, genuine dependencies, and integration checks appropriate to the permitted activity.

### For a single bounded task

A single bounded task may use its existing acceptance criteria without a graph.

### Shared graph rules

Use permitted existing goal, plan, tracker, or session state; this requirement neither mandates a new tracking system nor authorizes tracker mutation or project-file edits for read-only work.

Initial investigation may precede decomposition.
Keep downstream work provisional where discovery or an unresolved choice can change it; do not require an exhaustive audit before the first consumer path.
As evidence or the approach changes, update or supersede obsolete tasks and dependencies while preserving the governing outcomes.
Working from the graph means advancing an unmet root outcome and closing work on evidence, not obeying abandoned mechanisms or treating revisable agent assumptions as user requirements.
Graph work does not expand scope, change the authorized activity or effects, or resume an inactive goal.
The graph skill owns decomposition; work-selection supplies the overall-priority comparison through its assigned owner.

## Select work within the authorized run

Use [work-selection](../work-selection/SKILL.md) for next-work priority, dependency justification, and comparison of authorized approaches.
When a strategist owns overall priority, return that comparison to it; otherwise the assigned technical owner performs it.
The executive arranges that ownership rather than selecting technical priority itself.
Workers choose local actions within their responsibilities; executives question scheduling and dispatch the ratified work.
Reassess before extending repeated similar batches during an active run, even when they succeed.
Return changes to overall priority to its assigned owner; do not make a strategist direct every worker's next command.
Keep unmet acceptance conditions and scoped blockers visible while advancing independent authorized work.
Advance acceptance and integration only when governing prerequisites and required evidence permit.

Use [delegation](../delegation/SKILL.md) for shared responsibility, evidence handoffs, and ownership conflicts; organizers follow its executive route for assignments and worker lifecycles.

## For implementation work only

Builders and QA use these companion procedures for implementation when their conditions apply.
Executive acceptance bookkeeping does not transfer their checks or completion audits to the executive:

- Use [change guidelines](../references/change-with-evidence.md#design-choices) for unresolved modeling, interface, ownership, or invariant decisions, and [testing guidance](../references/testing.md) for test-strategy choices.
  For an established pattern, follow the surrounding code and tests without another design procedure.
- [Review evidence standards](../references/review-evidence.md) distinguish local/component checks, integration, and required real-input evidence.
  Consult them for milestone readiness; run the full audit only after substantial owned implementation is complete.
  A routine localized change needs a diff review and appropriate native checks, not a full audit.
- For a new independently invoked tool, use [new-tool-development](../new-tool-development/SKILL.md) to check readiness.
  This skill neither approves its artifacts nor selects its design.

The builder and QA identify, for an implementation acceptance case, the actual entrypoint, authoritative inputs, intervening interfaces, final consumer, and cheapest realistic check.
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
When assigning archivist source recovery, select the `archivist` template on Pi; on other harnesses, assign an equivalent bounded source-recovery role.

### When compaction risks losing track

Before compacting a complex run, check whether authority, acceptance, ownership, or evidence applicability is becoming hard to track.
When it is, use [delegation](../delegation/SKILL.md) to spawn a bounded archivist subagent while you can still name the uncertain points.
Give it those points, the current objective and permitted activity, existing task-state locations, and transcript, evidence and worker references.
Treat your account as claims to check, not the archivist's authority.
Ask it to reconcile duplicate or conflicting status claims against original records and identify superseded instructions with their replacement sources.
Require current dispositions, source references, and explicit unresolved contradictions, not another chronological summary or a whole-project audit.
The archivist reconciles records; it does not grant authority, certify technical acceptance, delete original evidence, or rerun acceptance checks.
Have the responsible owners resolve substantive contradictions in its result and incorporate supported corrections into the existing permitted task-state surface before preparing the checkpoint.
Do not create a parallel status ledger or treat the archivist's inference as a user decision.
If delegation is unavailable or compaction cannot wait, preserve the uncertain claims and recovery references explicitly rather than resolving them by assumption.
A coherent current record needs no archivist pass.

### Preserve state and resume

Before compaction, interruption, or handoff, preserve:

- the governing objective, permitted activity and effects, and protected boundaries;
- unmet acceptance conditions, next actions, and integration displaced by repairs;
- precisely scoped blockers and other independent obligations;
- completed evidence and artifact references, with their demonstrated scope;
- assumptions, pending judgments and worker effects, and checks needing rerun.

Persist only state expensive to reconstruct and use a permitted existing surface.
Reference existing acceptance records and results rather than copying their contents into another task database.
A recovery checkpoint preserves state; it does not create a human approval requirement or stop instruction.
On resume, read that state and reconcile it with later user instructions before choosing work.
Before recording a human stop or approval dependency carried by a summary, recover its source message or authoritative goal state and check its scope.
If that source is unavailable, state the uncertainty rather than attributing the restriction to the user.
Ask for clarification only when the unresolved authority affects the next action; continue independent authorized work.
Respect actual human stops and harness pause, block, budget, and resume controls; a missing citation is not permission to bypass them.
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

At completion, the responsible technical owner or workers compare the actual result with the original request and acceptance cases using the permitted activity's evidence standards.
The autonomous root ratifies reported coverage and returns gaps to their technical owners rather than performing verification itself.
Require concrete evidence for every explicit requirement and no required work remaining.
For completed implementation, apply the review threshold above and [completion review](../completion-audit/SKILL.md) when required.
For research, writing, planning, and review, the assigned technical owner verifies the requested answer or artifact without executing the proposed work or repairing findings unless separately authorized.

If only externally blocked obligations remain, report partial completion, exact blockers, and the next possible action.
If interrupted by time, budget, or tool failure, report paused work and preserve the next action.
Neither state is completion; do not spend the run on unrelated cleanup or change goal status outside its controls.
