---
name: work-selection
description: Reassess the next action before adding another substantive prerequisite, workaround, or diagnostic round—even when earlier steps succeeded—or when decision-changing feedback is slow and supporting activity displaces the requested outcome. Compare faster, smaller approaches without weakening requirements. Expected runtime can still be an unacceptable feedback loop. Not for obvious mechanical repairs or straightforward execution of a settled change.
---

# Work selection

Reassess the next action within the user's authorized task.
Use [autonomous-work](../autonomous-work/SKILL.md) for unattended-run authority, acceptance order, persistence, and stopping.
Use [opportunity-scan](../opportunity-scan/SKILL.md) only for project-wide discovery when no task is selected.

## Compare with the existing path

### Establish the need and evidence

Before treating a new mechanism or diagnostic as necessary, inspect an existing example of the requested activity.
If no example is available, report the evidence gap rather than inventing an example or a failure.

Identify the unmet requirement, the dependency the proposed work addresses, and the evidence for each.
For a diagnostic follow-up, name which possible findings would change the next action.

Repair obvious mechanical failures directly.
Unrelated bugs and hypothetical failures do not establish prerequisites.

### Compare the alternatives

Compare the proposed supporting work with continuing through the smallest existing-tool alternative, even when earlier steps produced useful results.
A chain of successful supporting tasks can still fail to advance the requested outcome.

Apply the shared [decision-authority rule](~/.agents/shared.md#before-selecting-a-substantial-approach).
Cite the source of consequential constraints before comparing actions.
Do not retain an abandoned approach as a prerequisite or claim its unmet criteria passed.

When a dependency follows from a chosen approach, name the choice that creates it.
“Keeping X requires Y” is not the same as “the user’s goal requires Y.”
If changing the choice removes the dependency, include that alternative in the comparison.

## Keep feedback fast

Optimize for time to the next result that changes which action comes next, not activity or completed checks.
Before a costly check, identify which results would change the next action and how soon they should arrive.
Aim for actionable development feedback within about two minutes unless the user or task establishes another budget.
This is a threshold for reconsidering the approach, not a universal command timeout or permission to weaken acceptance.

### Test an uncertain approach before expanding

When an uncertain approach will be repeated across many items, identify the assumption that could make repeating it wasteful or wrong.
Choose the smallest representative case whose result can challenge that assumption.
Before starting, state which results would justify expanding, revising, or stopping the approach.
Check the result against the intended outcome, not merely whether the prescribed steps completed.
Use existing applicable evidence instead of repeating an established check.

For example, before migrating many callers, try one that exercises the uncertain compatibility behavior and check it through its intended consumer.
For a prose rewrite, have a fresh reader follow one complete workflow; easier scanning alone does not establish that the explanation works.

### Reassess choices in flight

Apply this reassessment to work already underway, not only proposed work.
On loading this skill during a slow loop or receiving a feedback-latency correction, identify the current delay.
Revisit the choices keeping that delay on the critical path before assigning more work around it.
Prior authorization establishes permission, not continued usefulness; preserve user requirements while reconsidering agent-selected constraints.

Compare these options:

- Continue unchanged.
- Stop with evidence preserved.
- Isolate further development from the running check.

Judge the remaining cost and expected useful results, not time already spent.
Do not automatically stop a required acceptance run or merely route new assignments around an unexamined existing constraint.

If feedback will take longer, compare the smallest representative workload, a targeted intended-consumer check, and a different approach before proceeding.
Use small checks to choose the next change; they do not replace required full-population or end-to-end acceptance.
A progressing computation can still be an unacceptable feedback loop, even when its duration was expected.

### Isolate slow acceptance when useful

Separate slow acceptance runs from the development loop.
Preserve the candidate under verification without freezing further implementation where the work can be isolated.
Compare isolation and later integration costs against the expected wait and the useful work it prevents; do not reject isolation merely because it has overhead.
Hold only conflicting mutations, and do not introduce copies, automation or new workflow obligations when existing facilities suffice.

### Reassess when progress stalls

Reassess when the feedback budget passes without a decision-changing result.
Also reassess when several minutes yield only supporting reports, receipts or preparation rather than the requested outcome.
Use available evidence to choose the nearest useful outcome check or change the approach, rather than adding another supporting round.
Keep this comparison lightweight; do not turn it into another reporting or review stage.
A long check remains appropriate when smaller checks cannot settle the decision and its cost is justified.
Use [performance-investigation](../performance-investigation/SKILL.md) to diagnose execution cost or resource behavior.
Healthy execution alone does not settle work selection.

## Get an independent recommendation

When a substantive choice remains after this comparison, use an available compatible fresh-context scout template and follow its advertised caller contract.
Use [delegation](../delegation/SKILL.md#frame-independent-scouting-and-review) for caller framing, assignment, and integration.
Supply the literal task, current acceptance condition, governing references, and evidence entrypoints for the main user activity as well as current work.
Include the latest relevant user correction with its provenance; quote it only when the exact text is available.
Keep any parent hypothesis, proposed next action, or rationale provisional under that framing procedure, not a requirement or substitute for independent evidence inspection.
Without a compatible template, inspect an existing activity example and outcome evidence yourself, read-only.
Report unavailable evidence and do not claim independence for that fallback.
Do not scout after every tool call, repeat an unchanged search without new evidence, or turn scouting into an exhaustive project audit.

## Choose the next action

Compare the recommendation with continuing current work and the strongest credible competing action.
Consider user benefit and its evidenced or estimated scale, plus delivery, verification, and coordination costs.
A correct finding, novelty, or completed batch does not alone justify priority; a scout report is not the requested outcome.
Keep missing evidence distinct from demonstrated failure, and do not assume an investigation will justify follow-up work.
If uncertain benefit or cost determines the choice, use the smallest check that distinguishes the alternatives.
Stop deliberating when evidence supports a bounded authorized action or identifies a concrete blocker; impose no fixed lookup limit.
The parent retains selection authority and explains the decisive comparison without narrating a routine checklist.
Finding no better alternative is a successful result: continue when the existing approach wins.

Use [creative-inquiry](../creative-inquiry/SKILL.md) if framing remains uncertain, or consult [design alternatives](../architecture-design/references/alternatives.md) for a genuine software-design fork.
Neither is a default next phase of reassessment.

## Example: expected execution, slow learning

A full acceptance run is expected to take 45 minutes and requires its candidate's source bytes to remain unchanged.
The agent rejects an isolated candidate because copying and later integration have costs, then spends the wait producing receipts instead of implementing.
Compare those costs against 45 minutes of blocked development, and find the smallest check that can guide the next edit.
Keep the full acceptance run when required, but preserve its candidate independently if that permits useful authorized work.
Do not call the feedback loop adequate merely because the run is progressing normally.

## Example: an agent-selected single-file constraint

A user permits an introductory README with linked supporting documents.
The writer nevertheless chooses a single-file output and keeps migration records and every configuration option after a stronger introduction.
Further prose passes improve individual passages without making the whole satisfying to follow.
Before adding another writing rule, compare that approach with an introduction linked to a migration record and an option reference.
The single-file contract was an agent choice, not a user preservation requirement.

Use [reorganize-docs](../reorganize-docs/SKILL.md) for authorized extraction and navigation changes rather than inventing a new document workflow.
Keep prerequisites, hazards, and limitations needed for the introductory action beside that action.
Create or verify the supporting pages; an invented link does not preserve access to the detail.
Read the introduction alone, then follow its routes to check that later tasks remain understandable.
The improvement sought is a better reader experience, not merely fewer words in the README or more files in the tree.
