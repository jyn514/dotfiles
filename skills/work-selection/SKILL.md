---
name: work-selection
description: Reassess the next action before adding another substantive prerequisite, workaround, or diagnostic round—even when earlier steps succeeded—or when a supposedly settled approach gains dependencies, results challenge its assumptions, or slow feedback lets supporting activity displace the requested outcome. Compare faster, smaller approaches without weakening requirements. Expected runtime can still be an unacceptable feedback loop. Not for obvious mechanical repairs or straightforward execution of a settled change.
---

# Work selection

Choose work by what it contributes to the requested outcome from the current state.
A supporting step can succeed while leaving the main obstacle unchanged: text renders correctly but remains cumbersome to write; links resolve but readers still cannot follow the instructions.
Compare complete routes to the useful result, including delivery and verification.

Work within the user's authorization and the shared [decision-authority rule](~/.agents/shared.md#before-selecting-a-substantial-approach).
The direct task owner compares actions unless priority is assigned elsewhere; in a team, read [Responsibilities](#responsibilities) before taking up the comparison.

## Start with the activity that needs to improve

Trace an example of the requested activity through the nearest existing route to its intended consumer.
What already works, what obstacle remains, and how would the proposed step help overcome it?
If an example is unavailable, name the evidence gap rather than inventing a failure.

Cite sources for consequential constraints and distinguish required outcomes from mechanisms you selected.
Existing implementation, established patterns, or representative results can support a route without a new trial.
Approval establishes permission, not usefulness; prior investment does not show that a route works.
Repair obvious mechanical failures directly: they restore an understood path without adding a mechanism or assumption.
A growing workaround needs comparison even when earlier steps succeeded.

## Compare routes to the result

Compare continuing with the strongest credible alternative before elaborating more supporting work.
Look beyond variations of the chosen mechanism:

- **Correct installed state once or change recurring behavior.** A leftover artifact may need one authorized cleanup, not cleanup on every startup.
  If supported installation recreates it, compare fixes to that source behavior instead.
  How the artifact returns decides the choice.
- **Invoke or extend an existing operation or build a workflow.** Trace what the operation already does before designing coordination around it.
- **Remove a chosen constraint or satisfy its dependencies.** “Keeping X requires Y” does not establish that the user's goal requires Y.
  See the [CSV importer example](../references/common-misconceptions.md#when-a-tools-limitation-becomes-the-users-obligation).

Each route must meet the full outcome, required compatibility, and acceptance evidence.
When a smaller route falls short, identify the missing behavior; unrelated bugs and hypothetical failures do not establish prerequisites.

### Example: a chosen single-file constraint

A user permits an introductory README with supporting documents.
The writer chooses one file, keeping migration records and every configuration option after a stronger introduction.
More prose passes improve passages without making the whole satisfying to follow.
Compare that route with an introduction linked to a migration record and option reference: the single-file constraint belongs to the writer, not the user.

For authorized extraction and navigation changes, use [reorganize-docs](../reorganize-docs/SKILL.md).
Keep prerequisites, hazards, and limitations needed for the introductory action beside it.
Create or verify the supporting pages; invented links do not preserve access.
Read the introduction alone, then follow its routes to check later tasks.
The desired result is a better reader experience, not fewer README words or more files.

### Find the deciding difference

Judge expected contribution and total remaining cost, including integration, verification, and coordination.
A bounded sample of unchecked outputs may reveal reusable corrections; a certain repair may have no demonstrated effect on their use.
If the defect blocks the required workflow, the repair can win instead.
Compare expected contribution, not certainty against uncertainty.
Scope limits and measurements matter through contribution or cost; research earns priority when it can change a consequential decision.
Use existing evidence and rough estimates, not invented scores or probabilities.

Give competitors comparable treatment: retain scope limits, supported advantages, and equivalent opportunities for repair.
A fixed-sample review with a stopping condition does not become open-ended because a competing repair has a clear test.
A source/table/test disagreement establishes a discrepancy, not which component is wrong or what a generator repair will improve.

Check the premise deciding the ranking.
Does a governing requirement demand the guarantee, or only your design?
What observed fact rules out the strongest competitor?
Would the remaining costs and evidence favor this route if you had not started it?
If correcting a premise removes the reason for a preference, reconsider the ranking rather than preserve it with a caveat.
Continuing can win; do not invent a competitor to force a change.

## Make the next check useful

Connect the proposed supporting step to an unmet requirement and the dependency it addresses.
For uncertain work, say what it should resolve and which results would change the next action.
Compare the result with that expectation before extending the approach.

For example, a fixture repair expected to enable a regression test instead requires a new process manager.
Revisit the fixture route before building the manager: the assumption behind the first dependency may also have created the second.
Check what the diagnostic established and what remains, not just whether it succeeded.

Missing historical artifacts need not block measuring a current change.
A fresh baseline and candidate built from the same explicit inputs may answer that question.
If so, recover the source selection and provenance needed for the comparison, not exact historical build identity.
Leave unsupported historical claims unverified.
Retain historical reproduction when required or when a fresh comparison cannot isolate the change; identify the missing evidence.

### Keep feedback fast

Before a costly check, identify the decision its possible results can change and when they should arrive.
Aim for actionable development feedback within about two minutes unless the user or task sets another budget.
This is a reconsideration threshold, not a command timeout or permission to weaken acceptance.

Before repeating uncertain work, try a small representative case that can challenge the assumption behind it.
State what would justify expanding, revising, or stopping, and check the intended outcome rather than completion of steps.
For a caller migration, exercise the uncertain compatibility behavior through its intended consumer.
For a prose rewrite, have a fresh reader follow a complete workflow; easier scanning alone does not establish a useful explanation.
Reuse applicable evidence for established work.

On loading this skill during a slow loop or receiving a feedback-latency correction, identify the delay and choices keeping it on the critical path.
Compare continuing, stopping with evidence preserved, and isolating development from the running check.
Judge remaining cost and useful results, not sunk time.

For example, a required acceptance run takes 45 minutes and needs unchanged source bytes.
Copying its candidate and later integrating changes costs something, but so does blocking development for 45 minutes while producing receipts.
Compare those costs and find a smaller intended-consumer check to guide the next edit.
Keep required full acceptance; preserve its candidate independently when that permits useful authorized work.
Expected, progressing execution can still give feedback too slowly.

Small checks guide development; they do not replace required full-population or end-to-end acceptance.
When feedback will take longer, compare a representative workload, targeted consumer check, and different approach.
Isolate slow acceptance when the useful work it permits outweighs isolation and integration costs.
Hold only conflicting mutations and reuse existing facilities rather than adding workflow obligations unnecessarily.
Do not automatically stop acceptance or route work around an unexamined constraint.

Reassess when the feedback budget passes without a decision-changing result, or several minutes produce only preparation, reports, or receipts.
Choose the nearest useful outcome check or change the approach instead of adding another supporting round.
Long checks remain appropriate when smaller checks cannot settle the decision and the cost is justified.
Use [performance-investigation](../performance-investigation/SKILL.md) to diagnose execution cost or resource behavior; healthy execution does not settle priority.

## Choose and act

For a substantive recommendation, explain why it wins against the strongest available alternative, including continuing current work.
Name the deciding difference in contribution or remaining cost and its evidence or explicit assumption.
A finding, completed batch, or investigator's report does not itself establish priority.
Missing evidence is not demonstrated failure, and investigation need not justify follow-up work.

If the deciding difference remains uncertain, make the smallest useful check or choose provisionally with the uncertainty stated.
Do not commission another investigation merely to make every ranking conclusive.
Stop deliberating when evidence supports an authorized action or identifies a concrete blocker; there is no fixed lookup limit.
Continue when the existing approach wins.
Keep comparisons in working reasoning by default and explanations within recommendations, not routine checklists, prediction ledgers, or separate reports.
When abandoning a route, remove its prerequisites without claiming its unmet criteria passed.

Use [creative-inquiry](../creative-inquiry/SKILL.md) when framing remains uncertain, or [design alternatives](../architecture-design/references/alternatives.md) for a genuine software-design fork, not as default phases.

## Responsibilities

An assigned strategist owns overall priority and completes its comparison; builders and QA retain local method choices and return overall-priority changes to that owner.
A bounded helper does not displace the direct owner's responsibility.
An executive supplies evidence, not a competing comparison.
Send it the supported overall-priority decision for ratification against jyn's outcome, authorization, and explicit trade-offs.
An inadequate comparison stays with its priority owner to resolve with relevant workers; the executive does not supply missing inquiry or select a technical winner.
[Delegation](../delegation/SKILL.md) owns dispatch and ratification; neither grants new effects.
Use [autonomous-work](../autonomous-work/SKILL.md) for unattended-run authority and lifecycle, or [opportunity-scan](../opportunity-scan/SKILL.md) for project-wide discovery when no task is selected.

### When an independent recommendation earns its cost

Seek independence when jyn requires it or expected evidence or useful parallelism justifies the handoff; otherwise compare directly within your responsibility.
For an independent assignment, use the responsible strategist or a compatible template and read delegation's [investigation framing](../delegation/references/executive.md#frame-independent-investigation-and-review).
Supply the literal task, acceptance condition, governing references, current situation, and evidence entrypoints for both the main activity and current work.
Include relevant corrections with provenance; quote only available exact text.
Separate observations, failures, and prior attempts from provisional explanations.
Explain motivation without prescribing the action or conclusion.
The investigator questions framing, traces causal claims, and compares actions together, not through a separate fact-finding handoff.
Reuse accumulated context when it matters more than fresh independent judgment.

Without a compatible template, a technical worker may inspect an activity example and outcome evidence within its responsibility, read-only.
Name unavailable evidence and do not claim independence for this fallback.
An executive instead arranges a compatible owner or reports the staffing dependency; absence does not transfer inquiry to it.
Keep investigation bounded to the decision; new calls, unchanged evidence, or completeness alone do not justify repetition or a project-wide audit.

For skill evaluation, read [behavioral checks](references/behavioral-checks.md), not as another stage of ordinary work.
