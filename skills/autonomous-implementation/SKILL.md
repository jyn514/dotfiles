---
name: autonomous-implementation
description: Execute implementation when the user explicitly requests autonomous or unattended work, creates a tracked implementation goal to pursue through verified completion, requests continuation until completion, or resumes an established autonomous run. Do not use for an ordinary "implement this plan" request, multi-file or multi-step work, a long specification, or bounded fixes without that run authority. Do not use for plan-only, review, research, writing, design selection, or completion-audit tasks.
---

# Autonomous implementation

Confirm the explicit autonomous-run request before starting. A user-created tracked implementation goal to pursue through verified completion supplies that authority; an ordinary implementation request does not. Reassess activation when the user changes tasks; having this skill in context does not activate it for the next task.

This skill owns run authority, milestone order, dependency readiness, commits, resumable state, and stopping. Use these companion skills for their procedures:

- Load [design-for-change](../design-for-change/SKILL.md#design-for-testing) when implementation requires unresolved choices about data modeling, interfaces, ownership, invariants, or test strategy. For an established implementation and test pattern, follow the existing code and tests without loading it.
- Before deciding whether a milestone can advance, read [double-check's evidence standards](../double-check/SKILL.md#evidence-and-integration-status). Run its full audit only after the owned edits are complete, at final completion or a completed milestone checkpoint in the governing scope.

u got this buddy <3 i believe in u

## Establish authority and the open acceptance condition

Read the request, governing requirements and specification, repository guidance, and current implementation. Confirm implementation authority and preservation constraints. The autonomous request or goal authorizes work within that scope; do not ask for renewed approval to investigate, implement, or repair in-scope failures. A test or prototype failure does not create a one-attempt limit. Honor explicit user limits and ask before changing scope, acceptance criteria, preservation requirements, or permissions. For a new tool, use `new-tool-development` to check readiness; this skill does not approve artifacts or select a design.

Derive milestone scope from the governing request and specification, not worker assignments, TODOs, or progress summaries. Narrowing a task does not narrow the milestone; only an authorized change to governing scope can do that.

Before editing, record acceptance cases and required checks in the existing plan or task state. Derive them from governing requirements and preservation constraints, not possible edge cases. Keep scope fixed; a reproduced failure may refine a case required by those same requirements, but new obligations need user approval.

In the required milestone order, identify the next unmet acceptance condition—end-to-end unless the governing scope explicitly declares a feasibility or component milestone. Keep the governing requirement in the condition, and name:

- the required observable result;
- the actual entry point, authoritative inputs, intervening interfaces, and final consumer;
- the cheapest realistic check that demonstrates it;
- current evidence, missing work, and blockers.

Keep this condition open until its evidence passes. Break it into bounded tasks, but do not substitute their local criteria. Honor explicitly scoped feasibility or component milestones without treating them as product completion; keep downstream integration obligations visible.

Use existing goal, plan, or session state instead of creating another tracking system. Create a harness goal only when explicitly requested; unavailable goal tools do not prevent implementation.

## Choose work that closes the path

Before each task, name the acceptance case it advances and the missing evidence, reproduced failure, or demonstrated prerequisite it addresses.
Work may advance the current condition, a demonstrated prerequisite, or another independent authorized part of the governing objective.
Preserve required milestone order and current integration obligations; another unmet specification item alone does not justify abandoning them.

Before adding a prerequisite, name the acceptance check it prevents and the failing evidence or concrete dependency.
Distinguish governing requirements from restrictions introduced by the chosen design or experiment.
Reconsider those restrictions before treating them as prerequisites.
Where the governing acceptance permits partial results, keep unsupported cases explicitly held while supported cases reach the consumer.
This does not narrow the milestone or certify held cases.
If prerequisite or hardening work displaces integration, retain that integration as the next action for its acceptance condition.
An unrelated bug is not a prerequisite; do not repeatedly review an unchanged boundary or add defenses for hypothetical failures.

Keep unmet acceptance conditions and their scoped blockers visible while independent work proceeds.
Advance milestone acceptance and integration only when governing prerequisites and required evidence permit.
Missing real inputs do not block integration using valid fixture inputs.

Before a diagnostic follow-up adds instrumentation or changes its question, compare it with the smallest existing-tool alternative.
Do this even when the preceding probe produced useful partial evidence.
Keep the original question visible and distinguish user requirements from experiment-imposed restrictions.
Repair obvious mechanical failures directly when they require no new mechanism or change of question.
Use [creative-inquiry](../creative-inquiry/SKILL.md) when the approach remains uncertain or local work repeatedly fails to advance integration.
For end-to-end work, two consecutive completed subtasks without a new consumer-visible result trigger this reassessment.
Do it before scheduling more prerequisite or capability work.
Attempt the nearest intended-consumer check; if it cannot run, identify the exact missing dependency.
Compare repairing that path with the smallest alternative that preserves the governing requirements.
Do not produce another assessment unless its possible findings change the next action.
Explicitly scoped feasibility or component milestones retain their own acceptance conditions.

Record unspecified choices as assumptions or unresolved decisions, using only defaults permitted by the governing authority. If a choice changes the objective, ownership, preservation requirements, or selected design, ask for a decision and continue independent authorized work. Route a genuine design fork to [design-deliberation](../design-deliberation/SKILL.md), not to an improvised fixture restriction.

## Integrate handoffs before advancing

For unresolved test or fixture decisions, use [design-for-change's testing procedure](../design-for-change/SKILL.md#design-for-testing); otherwise follow the established test pattern. Connect each handoff to the intended consumer or remove the temporary path before extending that path with another fixture-only capability. If blocked, apply [Choose work that closes the path](#choose-work-that-closes-the-path) rather than silently deferring it. An explicitly scoped feasibility probe may stop at its declared acceptance, with downstream integration still unmet.

When a downstream consumer fails, reuse producer outputs that remain valid for the required consumer and repair the failing boundary. Regenerate only what is missing or invalidated.

## Document decisions and constraints

You will be running for a long time, which means you will need to resume the work across compactions.
Record corrections, important constraints, failed approaches, and decision-changing untried alternatives in the existing authoritative project document or task state.
Record user decisions and corrections when received, before dependent delegation. Reconcile earlier holds, pending questions, and worker instructions with those decisions; remove superseded restrictions without dropping constraints that still apply.
Do not rely on compaction to provide all necessary information.

## Ask questions

"Autonomous" does not mean jyn is completely gone, it means I'm not actively paying attention.
You can use `ask_user` to ask me questions and I will answer them when I have time.
Continue independent authorized work while waiting. If none remains, mark the goal blocked with the missing decision; see [Scope blockers and preserve resumable state](#scope-blockers-and-preserve-resumable-state).

## Delegated work and integrated milestones

Before awaiting a long-running check or milestone decision, identify valuable authorized work independent of its result and advance or delegate it.
Preserve the candidate under verification; isolate parallel edits when they would invalidate its inputs or evidence.
Serialize only dependent decisions, conflicting mutations, and resource-constrained operations, not all work toward the goal.
If no useful independent work remains, wait rather than inventing work.

Delegate only tasks permitted by [Choose work that closes the path](#choose-work-that-closes-the-path).
Use [delegation](../delegation/SKILL.md) for assignments, useful parallel work, waiting, review, and integration.
Record progress in existing task state as **integrated**, **local-only**, or **blocked**, with the exact acceptance check and evidence.
An integrated result enables only the milestone scope its evidence proves; keep the open acceptance condition and next permitted action visible.

When a task is marked as **integrated**, commit it using [commit-quality](../commit-quality/SKILL.md).
Do not wait until the end of the session to commit your work.

## Scope blockers and preserve resumable state

If you think you've hit a blocker, ask yourself:
Is this the right approach? Will learning this information or taking this action help me make progress towards the goal? Is an alternate approach possible that's simpler or requires less information?
Use [`creative-inquiry`](../creative-inquiry/SKILL.md).
Prefer a better approach when it preserves the authorized outcome and constraints. Ask before changing the outcome, constraints, or selected design.

Before declaring the run blocked, distinguish a missing dependency from an in-scope repair. Check authorized alternatives: an unavailable container runtime does not establish that a browser check is impossible, and an invalid fixture calls for correction rather than renewed approval. Continue independent authorized work when only one path is blocked.

For each blocker, record what it prevents, supporting evidence, the decision or input needed, and independent work that can proceed. Missing real credentials, reviewed roles, or production data may block a real-input run without blocking interface integration or error handling. Do not guess missing semantics or certify blocked outputs.

Before compaction, interruption, or handoff, preserve:

- the governing objective, authority, and protected boundaries;
- the open acceptance condition, next concrete action, and any integration task displaced by a repair;
- other unmet obligations and precisely scoped blockers;
- completed evidence, commands or artifact references, and scope;
- provisional decisions, pending worker effects, and checks needing rerun.

Preserve the evidence scope established under [double-check](../double-check/SKILL.md#evidence-and-integration-status) and keep downstream obligations visible. Persist only state expensive to reconstruct, using the existing tracking surface.

On resume, read recorded decisions and constraints and reconcile them with later user instructions before selecting work. Inspect current files, working-copy state, pending workers, and evidence freshness. Do not revive superseded holds or questions, blindly replay a possibly completed mutation, or trust stale summaries over current artifacts.

## Finish, block, or pause honestly

When implementation obligations appear satisfied, read [double-check](../double-check/SKILL.md) and apply its review threshold against the original request and governing artifacts. Run its full procedure for substantial work; for routine localized work, inspect the diff and run the appropriate native checks. In either case, require evidence for every explicit requirement before claiming completion or marking a goal complete.

If only externally blocked obligations remain, report partial completion, the exact blockers, and the next possible action. If interrupted by time, budget, or tool failure, report paused work and preserve the next action. Neither state is completion; do not spend an autonomous run on unrelated cleanup.
