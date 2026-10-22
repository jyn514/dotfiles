# Independent design deliberation

Use only when a demonstrated architectural fork needs independent elaboration and critique to resolve it.
A local change, a single design to assess, or a choice settled by repository evidence does not need this workflow.
Compare simpler alternatives directly using [Map design alternatives](alternatives.md).
This procedure selects a design; it does not authorize implementation or expand the task.

## Inputs

Use the original design question, user constraints and non-goals, repository evidence, and existing candidates.
Name the user-visible outcome, current baseline, and difference that would justify changing it.
Work through one complete affected case before expanding comparison; keep the baseline among the candidates.
Internal completeness or consistency supports the decision but does not replace the governing outcome.
A worked case need not be a finished implementation or benchmark.

Use historical evidence when it could change the decision; do not require a history investigation for every comparison.
If existing candidates cover the material choices, skip scouting.
For one supplied design, do not manufacture alternatives unless an unresolved fork remains.

## Compare a genuine fork

Read each phase reference only when entering its phase.
For a delegated phase, supply its full text or resolved absolute path, shared inputs, and only that phase's candidate material.
These references are not registered skills or names for subagent preloading.
Use [delegation](../../delegation/SKILL.md) for assignments and permitted effects.

1. **Map missing options:** use [alternatives](alternatives.md) only when material choices remain uncovered.
2. **Elaborate independently:** assign one [independent-plan](independent-plan.md) per viable brief, in parallel when practical.
   Each receives only its own brief plus shared task, constraints, and evidence.
   Give candidates stable opaque IDs outside the plans.
   If fewer than two viable plans survive, stop and report why.
3. **Critique:** use [cross-critic](cross-critic.md) to compare the fixed plans without selecting or rewriting them.
   Supply rejected scout forks only after its initial comparison.
4. **Consider fusion:** use [fusion-candidate](fusion-candidate.md) only if critique identifies components that may compose cleanly.
   No fusion is a normal result; any synthesis remains an ordinary candidate with stated provenance and risks.
5. **Review a fixed set:** use [council-review](council-review.md) on the candidates and critique.
   Do not add or rewrite candidates once review starts; hide candidate provider/identity where practical and ignore ordering.
   Accept selection, equivalence, or abstention; abstention identifies missing evidence and the cheapest useful inquiry.

## Stop and hand off

Use at most three initial plans and at most one fusion candidate.
Do not add revision rounds, recursive debate, or forced agreement after equivalence or abstention.
Add a heavier step only after observing a concrete failure it would prevent, not for a speculative omission.
Prefer tests, type checks, static analysis, benchmarks, and repository evidence to additional model votes.
A selected design is a hypothesis, not verification.
Carry its existing boundary contract forward; revise only unresolved or changed contracts, without a new declaration phase.
Use [implementation-plan](../../implementation-plan/SKILL.md) only when a plan is requested.

Report the selected candidate, equivalent set, or abstention; decisive reasons; important uncertainty; whether fusion was considered; and the next useful action.
Keep intermediate transcripts out unless requested.
