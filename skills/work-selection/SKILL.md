---
name: work-selection
description: Reassess the next action before adding another substantive prerequisite, workaround, or diagnostic round—even when earlier steps succeeded—or when a supposedly settled approach gains dependencies, results challenge its assumptions, or slow feedback lets supporting activity displace the requested outcome. Compare faster, smaller approaches without weakening requirements. Expected runtime can still be an unacceptable feedback loop. Not for obvious mechanical repairs or straightforward execution of a settled change.
---

# Work selection

Reassess the next action within the user's authorized task.
In a delegated team, the strategist owns overall next-work priority; builders and QA retain their local methods.
An executive routes substantive priority questions and new evidence to the strategist instead of performing this comparison itself.
Use [delegation](../delegation/SKILL.md) for dispatch and ratification; neither a recommendation nor ratification grants new effects.
Use [autonomous-work](../autonomous-work/SKILL.md) for unattended-run authority, acceptance order, persistence, and stopping.
Use [opportunity-scan](../opportunity-scan/SKILL.md) only for project-wide discovery when no task is selected.

## Compare with the existing path

Start with the requested outcome, the nearest existing route to it, and the proposed supporting action.
Inspect an existing example of the requested activity and trace that route from the current state through its intended consumer.
Compare continuing that route with the supporting action before elaborating a new mechanism or diagnostic, even when earlier steps were useful.
If no example is available, report the evidence gap rather than inventing an example or a failure.

Apply the shared [decision-authority rule](~/.agents/shared.md#before-selecting-a-substantial-approach).
Cite the source of consequential constraints before comparing actions.
Repair obvious mechanical failures directly.
Unrelated bugs and hypothetical failures do not establish prerequisites.

### Judge comparative value before selecting work

Ask what successful completion would leave unsolved.
Could the proposed step succeed completely while leaving the obstacle the user cares about unchanged?
Text can render correctly while writing remains cumbersome.
Documentation links can resolve while readers still cannot follow the instructions.
Identify how the step addresses that obstacle before prioritizing it over work that does.
A necessary partial step can still be worthwhile; compare the remaining route to the requested result, not only the intermediate success.

Judge the marginal benefit from the current state, not the general importance of the category.
Identify what already works, what the step adds, and what integration or unresolved decisions remain before that addition becomes useful.
Research can earn priority by changing a consequential decision; resolving an uncertainty is not inherently progress.
Use existing evidence and rough comparisons when sufficient rather than creating another measurement project.

Separate confidence in finishing a task from the value of finishing it.
A well-defined defect with a certain repair can matter less than uncertain work addressing the main obstacle.
“Bounded,” “concrete,” “measurable,” and “known defect” do not independently justify priority.
Explain how the property changes total remaining cost, time to a useful result, or expected contribution under the actual objective.
Apply comparable scope limits to the competing action where possible; do not compare a small repair with an unnecessarily broad audit.
Prefer the strongest expected contribution within the available time, preserving required quality rather than optimizing a convenient proxy.
Do not invent probabilities or numeric scores to make that judgment look precise.

### Examine what makes the approach settled

Distinguish a settled outcome, an approach supported by applicable evidence, and an approach you have merely selected.
User approval establishes permission; a plan or work already invested does not establish that its route works.
Use existing implementation, established patterns, or representative results as evidence; do not add a trial merely to call routine work settled.
When the route gains a substantive dependency or a result challenges an assumption that justified it, reopen the affected choice even if the overall plan is approved.
An obvious mechanical repair restores an understood path without introducing a new mechanism or assumption; do not use that label to exempt a growing workaround.

### Construct alternatives that change the action

Do not limit the comparison to several implementations of an assumed mechanism.
Use the actual state and governing requirements to construct alternatives across action types where relevant:

- Repair installed state once versus add persistent source behavior.
  Establish whether the problem needs a one-off correction or can recur under supported use.
- Invoke or extend an existing operation versus create a new protocol or workflow.
  Trace what the existing operation already does before designing coordination around it.
- Remove an agent-selected constraint versus satisfy the dependencies it creates.
  Name the choice that creates the dependency: “keeping X requires Y” is not the same as “the user’s goal requires Y.”

For example, a leftover installed artifact may need one authorized cleanup rather than cleanup on every startup.
If supported installation can recreate it, a one-off cleanup does not meet a requirement to prevent recurrence.
Compare fixes to the responsible source behavior.
The deciding fact is how the artifact returns, not which cleanup implementation is shortest.

Compare complete routes to the requested outcome, not just the nearest primitive or a successful intermediate step.
Check what the intended consumer needs, including required compatibility and acceptance evidence.
The smallest alternative qualifies only if it meets the full governing outcome.
When an existing route cannot do that, identify the concrete missing behavior before adding supporting work.

Challenge how you constructed the comparison, not just which candidate wins:

- Did you require an alternative to provide a guarantee introduced only by your preferred design?
- Did you compare your approach after its proposed repairs with an alternative before equivalent repairs?
- Which observed fact or governing requirement rules the strongest competitor out?
- If you had not started this approach, would the remaining costs and evidence still favor choosing it?

Identify the premise on which the ranking turns, and check it against the available evidence.
Do not describe a possible benefit as an established useful outcome, or discard a competitor's supported advantage.
A discrepancy does not yet establish which component is wrong or what correcting it will improve.
For example, a fixed-sample review with a stopping condition does not become open-ended because a competing repair has a clear test.
If correcting an unsupported description removes the reason for preferring an action, reopen the ranking rather than retain it with a caveat.

A credible comparison can favor continuing; do not invent a competitor or switch merely to demonstrate reconsideration.

### Establish which supporting work is needed

Identify the unmet requirement, the dependency the proposed work addresses, and the evidence for each.
For an uncertain supporting step, identify what you expect it to resolve and which possible results would change the next action.
Afterward, compare the observation with that expectation before extending the approach.
If the step reveals another dependency instead, inspect whether the assumption that justified the first step also creates the next one.
For example, a fixture repair expected to enable a regression test instead requires a new process manager.
Reconsider the fixture route before building that manager; do not treat the new dependency as proof that the manager is necessary.
A successful diagnostic may explain a failure without advancing the requested result; check both what it established and what remains.
Keep this comparison in working reasoning by default, not a separate report or prediction ledger.
A chain of successful supporting tasks can still fail to advance the requested outcome.
Do not retain an abandoned approach as a prerequisite or claim its unmet criteria passed.

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

If you are the strategist assigned to this choice, complete the comparison yourself rather than request another worker.
Other technical workers can reassess local methods within their responsibilities; return a change to overall priority to the strategist.
For a substantive overall-priority choice, use the responsible strategist or an available compatible strategist template and follow its advertised caller contract.
An executive supplies the question and evidence without first conducting its own competing comparison.
Use [delegation](../delegation/SKILL.md#frame-independent-investigation-and-review) for motivation-led assignment and integration.
Supply the literal task, current acceptance condition, governing references, current situation, and evidence entrypoints for the main user activity as well as current work.
Include the latest relevant user correction with its provenance; quote it only when the exact text is available.
Explain why the investigation matters without prescribing the next action or preferred conclusion.
Provide known observations, failures, and prior attempts; distinguish provisional explanations from governing requirements.
The strategist questions the framing, traces causal claims, and compares possible actions as one investigation rather than a separate fact-finding handoff.
Reuse an investigator when accumulated evidence matters; use a fresh context when independent judgment matters more than continuity.
Without a compatible template, a technical worker may inspect an existing activity example and outcome evidence within its own responsibility, read-only.
Report unavailable evidence and do not claim independence for that fallback.
An executive instead arranges a compatible owner or reports the specific staffing dependency; absence is not permission to take over inquiry.
Do not request independent investigation after every tool call, repeat an unchanged search without new evidence, or turn it into an exhaustive project audit.

## Choose the next action

The strategist compares possible next work with continuing current work and the strongest credible competing action.
For a local method choice, the responsible worker performs the same comparison within its assignment.
Consider user benefit and its evidenced or estimated scale, plus delivery, verification, and coordination costs.
A correct finding, novelty, or completed batch does not alone justify priority; a strategist report is not the requested outcome.
Keep missing evidence distinct from demonstrated failure, and do not assume an investigation will justify follow-up work.
For a substantive recommendation, state why the chosen action beats the strongest available alternative.
Name the deciding difference in expected contribution or total remaining cost, and the evidence or assumption supporting it.
General relevance to the goal does not establish priority.
Keep this explanation within the recommendation, not a separate reflection report or a checklist for routine actions.
If the deciding difference remains uncertain, use the smallest useful check or make a provisional choice with the uncertainty stated.
Use existing evidence and reasonable estimates; do not commission another investigation merely to make every ranking conclusive.
Stop deliberating when evidence supports an authorized action or identifies a concrete blocker; impose no fixed lookup limit.
Send the supported overall-priority decision to the executive for ratification against jyn's outcome, authorization, and explicit trade-offs.
If returned as inadequate, the strategist retains the comparison and resolves its deficiencies with the relevant workers.
The executive does not select a technical winner or supply missing investigation.
Finding no better alternative is a successful result: continue when the existing approach wins.

Use [creative-inquiry](../creative-inquiry/SKILL.md) if framing remains uncertain, or consult [design alternatives](../architecture-design/references/alternatives.md) for a genuine software-design fork.
Neither is a default next phase of reassessment.

For evaluating these judgments, use [behavioral checks](references/behavioral-checks.md).
These checks are for skill evaluation, not another stage of ordinary work.

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
