---
name: autonomous-implementation
description: Execute implementation only when the user explicitly requests autonomous or unattended work, continuation until completion, or resumption of an established autonomous run. Do not use for an ordinary "implement this plan" request, multi-file or multi-step work, a long specification, plan-only requests, design selection, bounded fixes, or completion audits.
---

# Autonomous implementation

Confirm the explicit autonomous-run request before starting. Reassess activation when the user changes tasks; having this skill in context does not activate it for the next task.

This skill owns run authority, milestone order, dependency readiness, commits, resumable state, and stopping. Use these companion skills for their procedures:

- Before implementation, load [design-for-change](../design-for-change/SKILL.md#design-for-testing) for test and fixture construction.
- Before deciding whether a milestone can advance, read [double-check's evidence standards](../double-check/SKILL.md#evidence-and-integration-status). Run its full audit only after the owned edits are complete, at final completion or a completed milestone checkpoint in the governing scope.

## 1. Establish authority and the open acceptance condition

Read the request, governing requirements and specification, repository guidance, and current implementation. Confirm implementation authority and preservation constraints. For a new tool, use `new-tool-development` to check readiness; this skill does not approve artifacts or select a design.

Derive milestone scope from the governing request and specification, not worker assignments, TODOs, or progress summaries. Narrowing a task does not narrow the milestone; only an authorized change to governing scope can do that.

Before editing, record acceptance cases and required checks in the existing plan or task state. Derive them from governing requirements and preservation constraints, not possible edge cases. Keep scope fixed; a reproduced failure may refine a case required by those same requirements, but new obligations need user approval.

In the required milestone order, identify the next unmet acceptance condition—end-to-end unless the governing scope explicitly declares a feasibility or component milestone. Keep the governing requirement in the condition, and name:

- the required observable result;
- the actual entry point, authoritative inputs, intervening interfaces, and final consumer;
- the cheapest realistic check that demonstrates it;
- current evidence, missing work, and blockers.

Keep this condition open until its evidence passes. Break it into bounded tasks, but do not substitute their local criteria. Honor explicitly scoped feasibility or component milestones without treating them as product completion; keep downstream integration obligations visible.

Use existing goal, plan, or session state instead of creating another tracking system. Create a harness goal only when explicitly requested; unavailable goal tools do not prevent implementation.

## 2. Choose work that closes the path

Before each task, name the acceptance case it closes and the missing evidence, reproduced failure, or demonstrated prerequisite it addresses. While the acceptance condition remains open, select only work that advances it or resolves a demonstrated prerequisite blocking its check. An unrelated unmet specification item alone does not justify displacement. Preserve milestone order and prerequisites.

If prerequisite or hardening work displaces integration, show the failing check or concrete dependency and why the path cannot proceed without repair. Retain the displaced integration as the next action. An unrelated bug is not a prerequisite; do not repeatedly review an unchanged boundary or add defenses for hypothetical failures.

Switch acceptance conditions only when the current one passes or no authorized advancing work can proceed, with supporting blocker evidence. Retain blocked conditions as unmet and select the next permitted independent condition. Missing real inputs do not block integration using valid fixture inputs.

Record unspecified choices as assumptions or unresolved decisions, using only defaults permitted by the governing authority. If a choice changes the objective, ownership, preservation requirements, or selected design, ask for a decision and continue independent authorized work. Route a genuine design fork to [design-deliberation](../design-deliberation/SKILL.md), not to an improvised fixture restriction.

## 3. Integrate handoffs before advancing

Use [design-for-change's testing procedure](../design-for-change/SKILL.md#design-for-testing). Connect each handoff to the intended consumer or remove the temporary path before starting another fixture-only capability. If blocked, apply §2's scoped-blocker rule rather than silently deferring it. An explicitly scoped feasibility probe may stop at its declared acceptance, with downstream integration still unmet.

## 4. Delegate, but retain integration ownership

Delegate only tasks permitted by §2. Include the open acceptance condition, remaining integration obligation, declared ownership/contracts, owned files, protected work, and local checks in each worker packet; repository delegation rules still apply.

Record progress in existing task state as **integrated**, **local-only**, or **blocked**, with the exact acceptance check and evidence. Apply [double-check's evidence standards](../double-check/SKILL.md#evidence-and-integration-status) to determine which scope the result establishes.

Worker completion alone does not enable dependent capability work; an integrated result enables only the scope its evidence proves. Local-only or blocked results permit work to integrate them or resolve their blockers, and independent work permitted by §2—not expansion based on assumed acceptance. Keep the open condition and next permitted action visible.

If producer and consumer disagree about required behavior, stop work across that boundary. Resolve the contract from governing authority or ask for a decision under §2; neither worker may silently choose the interpretation. Continue only independent authorized tasks while the contract remains unresolved.

When a task is marked as **integrated**, commit it using [commit-quality](../commit-quality/SKILL.md).
Do not wait until the end of the session to commit your work.

## 5. Scope blockers and preserve resumable state

For each blocker, record what it prevents, supporting evidence, the decision or input needed, and independent work that can proceed. Missing real credentials, reviewed roles, or production data may block a real-input run without blocking interface integration or error handling. Do not guess missing semantics or certify blocked outputs.

Before compaction, interruption, or handoff, preserve:

- the governing objective, authority, and protected boundaries;
- the open acceptance condition, next concrete action, and any integration task displaced by a repair;
- other unmet obligations and precisely scoped blockers;
- completed evidence, commands or artifact references, and scope;
- provisional decisions, pending worker effects, and checks needing rerun.

Preserve the evidence scope established under [double-check](../double-check/SKILL.md#evidence-and-integration-status) and keep downstream obligations visible. Persist only state expensive to reconstruct, using the existing tracking surface.

On resume, inspect current files, working-copy state, pending workers, and evidence freshness. Do not blindly replay a possibly completed mutation or trust stale summaries over current artifacts.

## 6. Finish, block, or pause honestly

When implementation obligations appear satisfied, run [double-check](../double-check/SKILL.md#procedure) against the original request and governing artifacts. Its audit determines whether completion can be claimed or a goal marked complete.

If only externally blocked obligations remain, report partial completion, the exact blockers, and the next possible action. If interrupted by time, budget, or tool failure, report paused work and preserve the next action. Neither state is completion; do not spend an autonomous run on unrelated cleanup.
