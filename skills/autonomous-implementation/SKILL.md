---
name: autonomous-implementation
description: Execute an authorized implementation across multiple tasks or milestones without losing end-to-end acceptance. Use when asked to implement a specification autonomously, continue until completion, work unattended, or resume a long implementation run. Not for plan-only requests, product or design selection, ordinary bounded fixes, or completion audits alone.
---

# Autonomous implementation

Tie work to observable acceptance through the intended consumer path. A correct helper, passing fixture, or atomic commit is progress—not completion of that path.

## 1. Establish authority and the open acceptance condition

Read the request, governing requirements and specification, repository guidance, and current implementation. Confirm implementation authority and preservation constraints. For a new tool, use `new-tool-development` to check readiness; this skill does not approve artifacts or select a design.

Derive milestone scope from the governing request and specification, not worker assignments, TODOs, or progress summaries. Narrowing a task does not narrow the milestone; only an authorized change to governing scope can do that.

In the required milestone order, identify the next unmet acceptance condition—end-to-end unless the governing scope explicitly declares a feasibility or component milestone—and name:

- the required observable result and governing requirement;
- the actual entry point, authoritative inputs, intervening interfaces, and final consumer;
- the cheapest realistic check that demonstrates it;
- current evidence, missing work, and blockers.

Keep this condition open until its evidence passes. Break it into bounded tasks, but do not substitute their local criteria. Honor explicitly scoped feasibility or component milestones without treating them as product completion; keep downstream integration obligations visible.

Use existing goal, plan, or session state instead of creating another tracking system. Create a harness goal only when explicitly requested; unavailable goal tools do not prevent implementation.

## 2. Choose work that closes the path

Before each task, compare the implemented path with the open acceptance condition. While it remains open, select only work that advances it or resolves a demonstrated prerequisite blocking its check. An unrelated unmet specification item alone does not justify displacement. Preserve milestone order and prerequisites.

If prerequisite or hardening work displaces integration, show the failing check or concrete dependency and why the path cannot proceed without repair. Retain the displaced integration as the next action. An unrelated bug is not a prerequisite; do not repeatedly review an unchanged boundary or add defenses for hypothetical failures.

Switch acceptance conditions only when the current one passes or no authorized advancing work can proceed, with supporting blocker evidence. Retain blocked conditions as unmet and select the next permitted independent condition. Missing real inputs do not block integration using valid fixture inputs.

Record unspecified choices as assumptions or unresolved decisions, using only defaults permitted by the governing authority. If a choice changes the objective, ownership, preservation requirements, or selected design, ask for a decision and continue independent authorized work. Route a genuine design fork to `design-deliberation`, not to an improvised fixture restriction.

## 3. Use fixtures through the real path

Use fixture data through the intended interfaces and consumer path. For example, test a CLI with a small valid input snapshot rather than replacing its snapshot consumer with a separate fixture-JSON API.

Allow a temporary probe or fixture-specific adapter only to resolve a demonstrated uncertainty or prerequisite for the open acceptance condition; a future integration TODO is insufficient. Its tests establish only that scope.

For integration work, connect the result to the intended consumer or remove the temporary path before starting another fixture-only capability. If blocked, apply §2's scoped-blocker rule rather than silently deferring it. An explicitly scoped feasibility probe may stop at its declared acceptance, with downstream integration still unmet. Do not promote the temporary implementation into the production interface or claim broader completion.

Review both failure directions: can the implementation accept invalid results, and can it lose required valid results? Include representative non-special-cased inputs where general behavior is required. Preserve validation and publication constraints; do not relax them to obtain end-to-end success.

Use `design-for-change` for implementation and testing, and other specialized skills when their triggers apply. This skill owns task selection and continuity, not those procedures.

## 4. Delegate, but retain integration ownership

Delegate only tasks permitted by §2. Give each worker the governing requirement, intended input/output contracts, owned files, protected work, local acceptance checks, and remaining integration obligation. Do not let a worker substitute a simpler fixture representation for a required handoff. Assign one owner for shared interfaces and effects.

The parent owns the assembled path. Inspect returned changes and run the relevant consumer-path check; a worker report or test count is not verification. Review the requirement and handoffs, not only the worker's narrower task.

After each task, record what changed, what evidence now passes, and what still prevents acceptance. If the path remains open, choose its next permitted task instead of declaring the milestone done and starting another fixture family.

## 5. Scope blockers and preserve resumable state

For each blocker, record what it prevents, supporting evidence, the decision or input needed, and independent work that can proceed. Missing real credentials, reviewed roles, or production data may block a real-input run without blocking interface integration or error handling. Do not guess missing semantics or certify blocked outputs.

Before compaction, interruption, or handoff, preserve:

- the governing objective, authority, and protected boundaries;
- the open acceptance condition, next concrete action, and any integration task displaced by a repair;
- other unmet obligations and precisely scoped blockers;
- completed evidence, commands or artifact references, and scope;
- provisional decisions, pending worker effects, and checks needing rerun.

Distinguish component-tested, integrated through intended interfaces, and verified with required real inputs. Mark each milestone complete only when evidence satisfies its declared scope; fixture evidence cannot complete a milestone requiring integration or real inputs. Keep downstream obligations visible. Persist only state expensive to reconstruct, using the existing tracking surface.

On resume, inspect current files, working-copy state, pending workers, and evidence freshness. Do not blindly replay a possibly completed mutation or trust stale summaries over current artifacts.

## 6. Finish, block, or pause honestly

When implementation obligations appear satisfied, use `double-check` against the original request and governing artifacts. Verify consumer-visible results, not only intermediate representations. Claim completion or mark a goal complete only with concrete evidence for every required acceptance condition.

If only externally blocked obligations remain, report partial completion, the exact blockers, and the next possible action. If interrupted by time, budget, or tool failure, report paused work and preserve the next action. Neither state is completion; do not spend an autonomous run on unrelated cleanup.
