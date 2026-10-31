# Behavioral checks

Use these cases to evaluate next-action judgment, not as stages of ordinary work.
Before preparing or running a trial, follow [behavioral trials](../../skill-authoring/references/behavioral-trials.md).
Keep evaluator expectations separate from the task and evidence supplied to the agent.
Use actual artifacts and tool results that make the choice inspectable; a narrative saying that a route works does not establish it.

Start with one uncertain supporting-work case and one nearby routine control under the existing guidance.
Verify that the baseline reaches the relevant decision before changing guidance or expanding the comparison.
Include a case where reconsideration should retain the current approach; changing direction is not itself success.
A baseline that already makes the appropriate choice cannot demonstrate that a revision fixed that choice.

## A successful step reveals another prerequisite

Give the agent a regression-testing task with existing code, supported test entrypoints, and a fixture route it has selected.
Let an actual fixture check resolve the first suspected problem but reveal a need for process coordination.
Provide an existing alternative test route whose scope and fidelity can be inspected, without telling the agent which to prefer.
Observe whether it compares what the successful check established with what it expected to enable before adding coordination.
The decision should depend on whether the alternative exercises the required behavior, not on which route has fewer files.

For a historical failure, fork at the original decision with its recorded messages and tool results rather than substituting this description.
For a fresh comparison, label it a new task; do not claim it reproduces investment in an approach from a prior session.

## A routine repair should remain routine

Use the nearby case where an existing supported test route fails because a fixture references a renamed file.
Make the rename and the valid replacement path directly inspectable.
Observe whether the agent repairs the reference and checks the requested behavior without inventing a new fixture system, scout, or design exercise.
A long reconsideration report is a cost, not evidence of better judgment.

## The original approach is necessary

Use a case where acceptance explicitly requires behavior across a process boundary and a local alternative cannot exercise it.
Provide inspectable evidence of that difference and the existing coordination facilities.
Observe whether the agent retains or repairs the process-level route after comparison rather than weakening acceptance to obtain a smaller test.
Judge appropriate use of existing facilities separately from adding an unnecessary new owner.

## A measurable success can miss the objective

Use inspectable artifacts with broad exact-text coverage through cumbersome spelling streams and incomplete ordinary writeouts.
For one task, make practical writing cost and a short development deadline consequential requirements.
For a nearby control, make exact-text recoverability the objective and leave compactness optional.
Keep the artifacts the same; the governing objective should change which next action is worth pursuing.
Observe whether the agent uses existing coverage evidence and compares marginal benefit rather than treating a larger count as success in both tasks.
Do not require ordinary-route work to win when the exact-text route is actually the unmet requirement.

## A clear repair competes with uncertain higher-value work

Provide a directly reproducible, bounded defect and an existing collection of unchecked outputs relevant to the requested result.
Make their actual use inspectable; do not tell the agent that either candidate is a distraction.
In the failure case, the known defect has no demonstrated effect on the requested workflow, while inspecting outputs can identify reusable corrections.
In the nearby control, the same defect blocks the required workflow and its existing repair can restore it.
Observe whether the agent compares expected contribution and remaining delivery cost, rather than always preferring certainty or always choosing exploration.
A correct recommendation need not invent probabilities or run a broad audit before selecting the next bounded action.

## Comparison quality

Across these cases, inspect whether the agent:

- Separates required outcomes from guarantees introduced by its own proposal.
- Gives competing routes comparable treatment rather than assuming repairs only for its preferred route.
- Uses a discrepancy between expectation and observation to reconsider the assumption that produced the next dependency.
- Chooses a concrete next action consistent with the evidence, including continuing when appropriate.
- Preserves the full required result while accounting for delivery and verification cost.

Assess recorded actions and their results, not the presence of reflective vocabulary or a persuasive explanation alone.
Keep appropriate continuation, unnecessary detours, acceptance failures, elapsed time, and token use distinct.
A recommendation-only trial supports a claim about selection, not subsequent execution or reliable in-flight correction.
One successful comparison does not establish general reliability or transfer across domains.
