---
name: work-estimation
description: Estimate or revise how long agent work will take, including task ETAs, remaining-time forecasts, and effort comparisons between approaches. Use when asked “how long,” when volunteering a work-duration estimate, or when checking past estimates against session history. Distinguish agent execution from human engineering effort and calendar waiting. Not for measuring program runtime alone, monetary estimates, or implementation planning without a duration question.
---

# Work estimation

Give a useful planning prediction for the requested result, not a proven duration bound.
Lead with a rounded central estimate when the task is understood well enough to make one.
Ground its scale in the actual route and comparable agent work where available, then use judgment for the differences.
Breaking a task into steps does not calibrate the durations, but lack of a measurement for every step is not a reason to withhold an estimate.

An estimate request alone authorizes read-only investigation, not implementation, prototypes, benchmarks, or starting workers to try the work.
Use existing evidence and the smallest inspection that could change the estimate.
[Implementation planning](../implementation-plan/SKILL.md) owns an explicitly requested implementation plan, not every ETA.

## 1. Define what finishes and whose time counts

Recover the requested outcome and current state from the conversation and owning artifacts.
State material inclusions and exclusions: first working result, required verification, review and repair, integration, or deployment.
Do not silently substitute a prototype for delivery or expand a patch into a production rollout.
Ask only when an unresolved scope choice would materially change the estimate.

Default to elapsed time for the agent doing the work with its available tools.
Do not substitute human developer-days or multiply them by an invented agent speedup.
If human effort is requested, estimate it separately and identify whose effort it represents.
Distinguish active execution, unattended command time, and waiting for people or external services.
A calendar delivery date requires assumptions about when work can actually run.

## 2. Inspect the actual route

Identify the nearest existing implementation, reusable mechanisms, and required verification path.
For a small task, a short trace is enough: inspect, edit, run focused checks, package or integrate if required.
For a larger task, identify the dependent stages and work that can genuinely overlap.
Do not add up parallel durations as though they were sequential or assume parallelism without available capacity.

Name the uncertainty that could change the route: an unreproduced failure, unsettled semantics, unknown data quality, or an unmeasured expensive check.
Separate that uncertainty from known work rather than treating every possible complication as inevitable.
Do not infer duration from file count, lines changed, architectural importance, or a list of frightening edge cases.
Those facts matter only when they change the actual work or feedback time.

## 3. Anchor the scale to comparable work

Find a basis for the scale before choosing the number.
Reuse relevant comparisons, known command costs, and direct knowledge of the current execution path already in context.
When the scale is uncertain, use available history tools for a focused search and inspect one or two promising comparisons.
Read promising matches rather than treating search snippets as evidence.
Stop when the evidence supports a useful planning judgment or another search is unlikely to improve it.
Do not turn estimation into a research project.
If useful history is unavailable, estimate from the inspected route and say the scale is less certain; no separate permission to make a judgment is needed.
A known command duration grounds that command, not automatically the whole task.

For each useful comparison, establish:
- What was already known when work started, and what result was actually delivered.
- The start and end events, including review findings, repair, and validation limits.
- Whether the interval includes human pauses, unrelated work, changed scope, or command waits.
- Material differences in tools, model, repository familiarity, workload, and test cost.

Treat transcript intervals as elapsed envelopes, not measured active effort, unless the record separates them.
Check whether timestamps represent the original events or copied, imported, or resumed history before subtracting them.
Recover original timing when available; otherwise retain the timing uncertainty rather than manufacturing a duration.
Do not call the first success report completion when later review found required work unfinished.
Deduplicate copied conversations.
Keep enough provenance to recover the events: session or artifact identifier and timestamps or entry IDs.

Decide how well the comparison transfers before using its duration.
Map the current route to the recorded work, including review and verification, and identify material differences.
Inspect claimed reuse rather than assuming either a large surcharge or zero extra cost.
Use the comparison to establish the rough scale, then judge the adjustment from the additional work and expected feedback cycles.
Explain the important adjustment in concrete terms; it does not need its own historical measurement or a numerical derivation for every minute.
A label such as “security-sensitive” alone does not justify multiplying the duration.
When a comparison misses the dominant work, use a closer one if readily available or base the estimate on that work's inspected route instead.
Distinguish observed durations from your prediction rather than describing the whole estimate as measured.
Do not present a retrospective fit or the working correction below as a universally validated forecast.

## 4. Account for review and uncertainty without arbitrary padding

Include required verification and likely repair, not only the first implementation.
Use comparable review cycles where available and judge the remaining allowance from the specific behavior and tests involved.
Explain allowances that materially change the estimate; do not add a blanket multiplier for unspecified complications.
Do not remove required tests or review to make the estimate shorter.
Known command costs set a minimum: a two-hour acceptance run cannot fit into a twenty-minute delivery estimate.
Count reuse and overlap only where the workflow permits them.

Estimate the expected route, not the sum of every worst case.

### Halve judgment-based work estimates

For this agent's observed tendency to overestimate, use divide-by-two as the working correction.
First make your best raw estimate of active agent work, including judgment-based editing, reasoning, review, and repair time.
Divide that portion by two once, then add measured command runtimes and external waits unchanged.
For example, 30 minutes of estimated active work plus a known 10-minute test run becomes about 25 minutes, not 20.
Do not halve recorded actual durations or reapply the correction to an already-corrected forecast.
Treat this as a practical bias correction, not a universal law; revise it when prospective results show a different pattern.

Give a rounded central prediction and name the concrete condition most likely to change it.
A narrow range can help when it changes the scheduling decision; do not widen it merely to make being wrong less likely.
Do not claim a confidence percentage without a calibrated basis.
Unknown duration is normal; withhold a full-task number only when the route, feasibility, or scope is too unresolved for a useful prediction.
In that case, explain the missing premise and give a conditional total or clearly labeled known-portion estimate where useful.

## 5. Answer briefly and revise against evidence

Lead with a usable prediction such as “about 5 minutes, including focused tests,” whose time it measures, and the completion boundary.
Use sensible rounding rather than false precision.
“Minutes-scale” is not an adequate substitute when the inspected task supports a central estimate useful for planning.
Briefly state the basis, the judgment involved in the adjustment, and the main reason to revise.
An approximate number is a prediction, not a guarantee; do not bury it under repeated qualifications.
Use a breakdown only when it explains the estimate; a small patch does not need a planning document.

Revise when observed throughput, review findings, scope, or command costs invalidate an assumption.
When challenged, reconsider the reasoning and identify what changes the estimate.
Evidence already inspected can justify a correction; another tool call is not required.
Do not change the number merely to accommodate pressure, but do not defend a poor estimate just because no new measurement arrived.
If the route remains understood, make a better planning judgment and explain it; retract the total only when that route cannot support a useful prediction.
Estimate remaining work from the current state rather than repeating the original duration.
When comparing a past forecast with its result, preserve the original scope and report incomplete verification instead of choosing whichever endpoint makes the estimate look best.
A revised method is not calibrated merely because it explains past errors.

### Check forecasts prospectively

When implementation is subsequently authorized, preserve the raw work estimate, corrected forecast, assumptions, and completion boundary before work begins.
The existing conversation or task record is sufficient; do not create a tracking system just to estimate a task.
Keep revisions separate so the original forecast remains recoverable.
At the relevant delivery boundary, compare the result with that forecast, distinguishing execution, waiting, scope changes, and incomplete verification.
Compare both raw and corrected predictions with actual results, including overruns and underruns, to judge whether halving improves accuracy.
Do not select only conspicuous overestimates.
Do not present retrospective examples or textual skill review as evidence of prospective accuracy.

## Worked examples

The forecasts below illustrate planning judgments with the divide-by-two correction, not measured outcomes or default budgets.

### Small change with existing tests

- **Observations:** A notifier and its test harness already exist.
  Adding the original notifier and smoke-checking it took 34 seconds.
  The requested change distinguishes link-only activity from human-requested work and needs regression tests for both cases, including a link arriving during human-requested work.
- **Judgment:** The old duration establishes a small editing cost, not the new delivery time.
  A raw allowance of about 10 minutes covers the event distinction, regressions, and focused checks; no measurement for each added minute is necessary.
- **Estimate:** Halve the judgment-based allowance: “About 5 minutes of agent time, including focused regression tests.”
- **Revision condition:** “I'll revise that if distinguishing the events requires changes outside the notifier.”

### Review-heavy change

- **Observations:** A comparable pause/resume change reached its first passing implementation in 17 minutes.
  Review then found lifecycle races; redesign and testing extended the same-day elapsed interval to roughly 3½ hours, including pauses, with later repairs and a full-suite blocker still outstanding.
- **Judgment:** Seventeen minutes measures the wrong endpoint for reviewed delivery.
  For a similar change, use the review-and-repair history to judge the work, not as a precise active-time measurement or proof of full acceptance.
- **Estimate:** A raw judgment of about 4 hours of active work becomes “About 2 hours through review, repair, and focused tests; full-suite acceptance remains dependent on clearing the existing blocker.”
- **Revision condition:** “I'll revise the remaining estimate if review exposes another lifecycle boundary requiring redesign.”
