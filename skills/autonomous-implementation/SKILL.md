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

Before each task, name the acceptance case it closes and the missing evidence, reproduced failure, or demonstrated prerequisite it addresses. While the acceptance condition remains open, select only work that advances it or resolves a demonstrated prerequisite blocking its check. An unrelated unmet specification item alone does not justify displacement. Preserve milestone order and prerequisites.

If prerequisite or hardening work displaces integration, show the failing check or concrete dependency and why the path cannot proceed without repair. Retain the displaced integration as the next action. An unrelated bug is not a prerequisite; do not repeatedly review an unchanged boundary or add defenses for hypothetical failures.

Switch acceptance conditions only when the current one passes or no authorized advancing work can proceed, with supporting blocker evidence. Retain blocked conditions as unmet and select the next permitted independent condition. Missing real inputs do not block integration using valid fixture inputs.

Revisit the approach when repeated research or local artifacts do not increase integrated progress, not only when work stops.

Record unspecified choices as assumptions or unresolved decisions, using only defaults permitted by the governing authority. If a choice changes the objective, ownership, preservation requirements, or selected design, ask for a decision and continue independent authorized work. Route a genuine design fork to [design-deliberation](../design-deliberation/SKILL.md), not to an improvised fixture restriction.

## Integrate handoffs before advancing

For unresolved test or fixture decisions, use [design-for-change's testing procedure](../design-for-change/SKILL.md#design-for-testing); otherwise follow the established test pattern. Connect each handoff to the intended consumer or remove the temporary path before starting another fixture-only capability. If blocked, apply [Choose work that closes the path](#choose-work-that-closes-the-path) rather than silently deferring it. An explicitly scoped feasibility probe may stop at its declared acceptance, with downstream integration still unmet.

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

## Delegate, but retain integration ownership

Default to delegating tasks.
You are a coordinator and integrator, not a worker:
your responsibility is to make sure that integrated work makes progress towards the goal, not to do the work yourself.

Before delegating coupled implementation, apply [boundary-declaration's delegation readiness check](../boundary-declaration/SKILL.md#delegation-readiness) to settle shared contracts. Reuse an existing contract when it settles the shared choices.

Delegate only tasks permitted by [Choose work that closes the path](#choose-work-that-closes-the-path), with clear inputs and expected outputs whose integration can be checked without repeating the worker's task. Use independent review for consequential judgment. Perform small inspections directly.

Include the open acceptance condition, remaining integration obligation, declared ownership/contracts, owned files, protected work, and local checks in each worker packet; repository delegation rules still apply.

Record progress in existing task state as **integrated**, **local-only**, or **blocked**, with the exact acceptance check and evidence. Apply [double-check's evidence standards](../double-check/SKILL.md#evidence-and-integration-status) to determine which scope the result establishes.

Worker completion alone does not enable dependent capability work; an integrated result enables only the scope its evidence proves. Local-only or blocked results permit work to integrate them or resolve their blockers, and independent work permitted by [Choose work that closes the path](#choose-work-that-closes-the-path)—not expansion based on assumed acceptance. Keep the open condition and next permitted action visible.

If producer and consumer disagree about required behavior, stop work across that boundary. Resolve the contract from governing authority or ask for a decision under [Choose work that closes the path](#choose-work-that-closes-the-path); neither worker may silently choose the interpretation. Continue only independent authorized tasks while the contract remains unresolved.

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
