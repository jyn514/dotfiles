---
name: behavioral-testing
description: Create and minimize behavioral tests of AI agents. Use when reproducing agent failures, building evaluations of agent decisions or actions, or reducing a behavioral reproducer while preserving its measured outcome. Covers repeatability and nearby controls. Not for ordinary application unit tests, software crash reduction, conversation summaries, or textual skill review without behavioral trials.
---

# Behavioral testing

Build tests with observable outcomes, then minimize demonstrated failures without losing the measured behavior.
Use the existing harness and disposable resources before building another runner.
Test creation does not authorize deploying instruction changes, repairing the underlying problem, or acting on real user state.

Before arranging a trial, read and follow [Behavioral trials](../skill-authoring/references/behavioral-trials.md).
That reference owns historical replay, paired comparisons, instruction exposure, passive observation, and summarization trials.
Use the procedure below for constructing the fixture and, when requested, minimizing a demonstrated failure.

## Select a behavioral trial

Start with the decision the evaluation should inform, then identify the requested kind of trial before designing its fixture:

- **Historical reproduction:** follow the historical replay procedure in the trial protocol to establish the original baseline before simplifying it.
- **New evaluation inspired by an incident:** a small synthetic fixture is valid, but it is a new condition, not the original baseline.
- **Minimization:** reduce an already demonstrated reproducer using §4.

Shortlist cases that exercise the decision.
Prefer a small useful test over a large one, but do not choose an easy case that measures a different behavior.
For historical candidates, use session searches to locate episodes, then read the governing request and the evidence around the decision.
Treat complaints, search snippets, quoted histories, and retrospective explanations as leads rather than proof of an independent failure.

For each promising candidate, establish:

- The requirement or constraint in force, including later permission or scope changes.
- The information available when the agent chose its action.
- The concrete action and its observed result, separated from the agent's account of them.
- The tempting inference the case tests and what evidence should have changed that inference.
- An observable outcome that distinguishes the failure from a legitimate alternative.

Check that the action was actually wrong under those requirements.
Literal test values can encode a fixed contract or synthetic inputs; copying a mutable configuration value into another consumer is a different case.
Updating obsolete specification text can be correct; deleting a requirement merely because implementation lacks it tests a different judgment.
A retry can be appropriate when a producer runs late; waiting for a representation that the producer never creates cannot repair the failure.
Use these distinctions to identify a nearby control, rather than grading every literal, documentation edit, or retry as a failure.

Match the starting state to the question.
If the question is whether the agent introduces a test pattern from scratch, choose a starting state without a suite that supplies it.
Updating inherited literal assertions does not establish that the agent would introduce those assertions from scratch.
Removing the old suite can create a useful derived trial; record that adaptation rather than claiming it was the historical starting state.

Rank candidates by relevance, strength of evidence, clarity of scoring, and the cost of reaching the decisive action now.
For a new evaluation, prefer local files, small callable interfaces, and controlled command results when they preserve the relevant choice.
For example, a repository-local dependency request can be tested with two configurations sharing an installer;
check that only the requested repository changes instead of requiring a real image build.
That synthetic scenario does not establish reproduction of the original incident.
Estimate setup cost without silently dropping the state, tools, or constraints needed to exercise the choice.
Label a proposed small fixture as a hypothesis until it reproduces through the assembled path.

Choose a more involved case when no simpler candidate preserves the judgment being tested.
For a new evaluation, do not require a large historical environment when a smaller setup preserves the relevant choice.
Select one representative candidate and its nearby control before expanding to a collection.
Carry its proposed outcome into the criterion below; establish the baseline before minimizing it.

## 1. Fix the observable criterion

Recover the request and decisive evidence before choosing the test.
Name the decision the result should change and the observation that would change it.
Define the failure in terms of inspectable actions or outputs.

Separate outcomes that can occur independently.
For example, editing without requirements and claiming completion are different failures.
If the criterion is actual edits, bad reasoning or a scope request without edits does not reproduce it.
An edit later reverted still counts as an edit; a clean final inventory alone cannot establish that no edits occurred.
Check successful tool results and intermediate actions as well as the final files.
Distinguish attempted edits, failed tool calls, identical-content writes, and actual changes.

Choose the repeatability check before selecting a reduced fixture.
For a small reproducibility check, default to two valid runs out of two unless the request requires another standard.
Stop after the agreed check rather than increasing the sample count after the selection decision is settled.
Report the observed count without treating it as a failure-rate estimate or a guarantee about future runs.
Rate comparisons require a sampling design appropriate to that claim.

## 2. Build a faithful baseline

Start with the closest available execution path that can expose the failure.
Reuse native model access, authentication, tools, and subagents where available.
Do not introduce guest credentials, a new broker, or a replacement harness before checking what the existing route supports.
Keep model calls and mutations within the authorized scope and use owned disposable state.

For a historical case, recover the actual model and reasoning setting from recorded metadata rather than current defaults.
Recover the governing instructions, relevant task state, attempted operation, and returned error from raw evidence.
Session readers can omit metadata or tool-result bodies; inspect the underlying record when those omissions affect fidelity.
An unavailable model is a blocker to that model's trial, not permission to substitute another silently.
Record an approved substitution as a different condition.

Preserve uncertainty and information order when they define the choice being tested.
Do not make ambiguous requirements explicit merely to simplify scoring; keep evaluator precision separate from the agent-visible task.
Do not expose later requirements, diagnoses, or repair interfaces before their historical appearance.
For example, a callback introduced during a later repair is not part of the original pre-failure interface.

Preserve the inputs the agent could inspect and the failure it actually encounters.
A source export is not a working repository when the task uses history or repository status.
A direct file permission error is not automatically equivalent to an issue command failing on a repository lock.
If an input is deliberately inaccessible, synthetic hidden contents can suffice; verify the access boundary and label the contents synthetic.
Do not make recovery of invisible historical contents a prerequisite without a reason tied to the test.

Record known differences and their possible effects.
Call reconstructed inputs a reconstruction; do not claim exact replay when runtime, tools, instructions, or workspace identity differ.

## 3. Verify the assembled path

Check that the model receives the intended instructions and uses the intended tool execution target.
Use effective request captures and representative operations through the native bindings.
Tool names and declarations alone do not prove which implementation runs.
For a file-editing test, verify the actual workspace and permission boundary through the tools the model will invoke.
An isolated helper test or container preflight does not establish model behavior through the assembled harness.

Keep expected worker errors separate from authentication, transport, initialization, and evidence-capture failures.
Validate each run against its declared fixture before scoring behavior.
For example, an unexpectedly missing repository invalidates a repository baseline; deliberately removing it can be a valid minimization condition.
An invalid run is neither a reproduction nor evidence that the agent behaves correctly.
Retain its failure evidence and fix the infrastructure before drawing behavioral conclusions.

Score the baseline against the chosen criterion.
Use the nearby control required by the trial protocol to distinguish the failure from an unsuitable fixture.
Keep evaluator expectations, reference answers, and later diagnoses out of the worker's inputs.
For a fresh evaluation, no observed failure is a valid result; report it and finish the requested evaluation.
Begin minimization only when a failure meets the chosen criterion and repeatability check.
If the request is reproduction and that check fails, report the failure as unreproduced rather than weakening the criterion.

## 4. Minimize while preserving the failure

Keep an immutable passing fixture and an explicit record of rejected candidates.
Hold the model, reasoning setting, and scoring criterion fixed while reducing setup.
Keep the execution path fixed unless it is the dimension deliberately being reduced; verify changed bindings before interpreting that reduction.
Use fresh disposable state and session context for each run.

1. Remove a substantial group of inputs: instruction blocks, unrelated files, repository history, dependencies, or auxiliary context.
   Prefer cuts that substantially reduce setup or expose which context drives the action.
   Preserve the task requirement or constraint whose violation defines the failure.
2. Capture the candidate's effective inputs and verify the intended cut.
   Remove alternate copies too: shortening stdin while leaving a longer reread packet is a different reduction.
   Check discovered instructions, file aliases, and inherited context when they can restore supposedly removed inputs.
3. Run the candidate against the unchanged criterion.
   A smaller setup that retains only poor reasoning while losing the required action is a failed reduction.
4. Retain the candidate only when it meets the agreed repeatability check.
   Under a two-out-of-two requirement, an observed miss disqualifies that configuration.
   Do not discard a failure and restart the count to manufacture two successes.
   Additional runs of a rejected candidate need a separate diagnostic purpose.
5. If a cut fails, return to the last passing setup and try a smaller cut or another group.
   If separate cuts pass, test their combination; independent successes do not establish that the combination reproduces.

Preserve the behavior being tested while reducing its surroundings.
Removing a prohibition that made an action wrong changes the task; do not score that action against the original prohibition.
Do not add an obvious new defect, tell the agent to skip the missing requirement, or change the oracle to rescue a candidate.
For code reductions, retain the relevant original behavior instead of substituting a different bug that is easier to trigger.

Stop when the requested reduction and repeatability check are satisfied, a meaningful next cut fails, or an agreed limit is reached.
Keep the smallest tested passing fixture and any smaller rejected case that demonstrates an observed boundary.
Say which dimensions remain untested; do not imply a global minimum from a bounded search.

## 5. Leave a reproducible result

Provide a runnable entry point and fixture, with model/settings, effective instructions, tool behavior, and state identity recorded.
Preserve the baseline, controls, reduction lineage, valid/invalid status, raw action evidence, and observed counts.
Record final retained changes separately from transient edits and completion claims.
Keep failures in the results rather than retaining only successful samples.
Distinguish historical observations, fresh trials of the original baseline, and derived-fixture trials.
A non-reproduction in a reconstruction establishes only that condition's observed outcome, not whether the original baseline reproduces.
Do not report an untested original baseline as a failed reproduction.

For minimization, report the smallest setup that meets the chosen criterion and the cut that stops reproducing or becomes intermittent.
For evaluation without a reproduced failure, report the measured outcomes and the scope actually exercised.
State relevant validation limits in either case.
Include token use and elapsed time when available; avoid efficiency claims when those costs are unmeasured.
