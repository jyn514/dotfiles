---
name: behavioral-testing
description: Create and minimize behavioral tests of AI agents. Use when reproducing agent failures, building evaluations of agent decisions or actions, or reducing a behavioral reproducer while preserving its measured outcome. Covers repeatability and nearby controls. Not for ordinary application unit tests, software crash reduction, conversation summaries, or textual skill review without behavioral trials.
---

# Behavioral testing

Build a test around an observable decision, then reduce a demonstrated failure without changing what makes it wrong.
Test creation does not authorize deploying instructions, repairing the underlying problem, or acting on real user state.

Before arranging a trial, read and follow [Behavioral trials](../skill-authoring/references/behavioral-trials.md).
It owns historical replay, paired comparisons, instruction exposure, passive observation, and summarization trials.
This skill develops fixtures and minimizes failures when requested.

## Choose the case and claim

Name the decision the evaluation should inform and the observation that would change it.
Choose the requested trial before designing its fixture:

- **Historical reproduction:** establish the original baseline through the trial protocol before simplifying it.
- **New evaluation:** a synthetic case inspired by an incident tests a new condition, not the original baseline.
- **Minimization:** start from a demonstrated reproducer; use **Reduce the surroundings, retain the failure** below.

For historical candidates, search sessions, then read the governing request and decisive evidence.
Complaints, snippets, quoted histories, and retrospective accounts are leads, not proof of independent failure.
Establish the requirements, permission changes, and information available at the choice.
Check the actual action and result against those requirements, not the agent's account.
What evidence should have changed its inference?
Choose an observable outcome distinguishing the violation from a legitimate alternative, and pair it with a nearby control.

Literal test values can express a fixed contract or synthetic input; copying mutable configuration into another consumer tests a different choice.
Updating obsolete specification text can be correct; deleting a requirement because implementation lacks it is different.
Retrying a late producer can help; waiting for a representation it never creates cannot.
These distinctions produce controls, not blanket judgments about literals, documentation edits, or retries.

Match the starting state to the claim.
Testing whether an agent introduces literal assertions from scratch requires a starting state without a suite supplying them.
Updating inherited assertions does not establish that behavior; removing a historical suite creates a derived trial.
Record the adaptation.

Rank candidates by relevance, evidence, scoring clarity, and cost of reaching the decisive action, including needed state, tools, and constraints.
Prefer a small case that preserves the choice; use a more involved one when necessary.
For new evaluations, prefer local files, small interfaces, and controlled command results.
Two configurations sharing an installer can test whether a repository-local dependency request changes only that repository, without a real image build.
That does not reproduce the historical incident.
Treat the fixture as a hypothesis until it reproduces through the assembled path.
Establish one representative case and control before expanding the collection.

## Define what counts

Define failure through inspectable actions or outputs and set the observation endpoint at the tested judgment.
Capture enough evidence to score it, then stop; require downstream implementation only when the criterion tests it.
Stopping too early is inconclusive; a later timeout does not erase an already valid observation.

Separate independently occurring outcomes.
Editing without requirements and claiming completion are different failures.
If actual edits define failure, poor reasoning or a scope request without edits does not reproduce it.
An edit later reverted still counts.
Inspect intermediate actions and successful tool results, distinguishing attempts, failed calls, identical-content writes, and actual changes.

Choose repeatability before selecting a reduced fixture.
For a small reproducibility check, default to two valid runs out of two unless the request requires another standard.
Stop at the agreed check; report counts without treating them as failure-rate estimates or guarantees.
Rate comparisons need a sampling design suited to that claim.

## Build and verify the baseline

Use the closest available execution path that can expose the failure, with owned disposable state and authorized model calls and mutations.
Check existing harnesses, native model access, authentication, tools, and subagents before building a runner or introducing credentials or a broker.

### Reconstruct the choice

For historical trials, use the protocol to choose the cut and decide how much state to restore.
Recover the actual model and reasoning setting, governing instructions, relevant state, attempted operation, and returned error from raw records.
Inspect underlying records when session readers omit consequential metadata or tool results.
An unavailable model blocks that model's trial; record any approved substitution as a different condition.

Ask what the agent could know at that cut.
Preserve ambiguity when resolving it would change the choice, even if explicit requirements would simplify scoring.
Keep evaluator expectations and reference answers out of the inputs.
Preserve the historical timing of requirements, diagnoses, and repair interfaces: a callback introduced during repair is not part of the pre-failure interface.

Then ask what the agent needs to inspect or encounter.
For a failed issue command, does the choice depend on repository history or status?
If so, use a working repository rather than a source export.
Does it depend on the command's lock error?
A file permission error is not automatically equivalent.
By contrast, deliberately inaccessible files can have synthetic contents if you verify the access boundary and label them synthetic.
Recover invisible historical contents only for a reason tied to the test.
Record reconstruction differences and possible effects rather than claiming exact replay.

### Does the assembled path deliver that condition?

Before scoring, inspect effective request captures for intended instructions.
Verify the tools' execution target with representative operations through native bindings.
For file edits, verify workspace and permissions through the model's tools.
Declarations, helper tests, and container preflights do not establish what runs through the assembled harness.

Validate each run against its fixture through the observation endpoint.
An unexpectedly missing repository invalidates a repository baseline; deliberately removing it may be a valid reduction.
Separate expected worker errors from authentication, transport, initialization, and capture failures.
Retain invalid-run evidence and fix infrastructure before drawing behavioral conclusions.
Invalidity establishes neither reproduction nor correct behavior.

Score the baseline and nearby control against the criterion.
For a fresh evaluation, no observed failure is a valid result: report it and finish.
For reproduction, report an unmet repeatability check as unreproduced rather than weakening the criterion.
Minimize only after failure meets both criterion and repeatability check.

## Reduce the surroundings, retain the failure

Choose the reduction objective for the requested use: clarity, less setup, fewer input tokens, or lower execution cost.
Compare candidates on that objective and note material regressions.
A shorter history can reopen resolved work and increase tool calls; fewer messages need not be better.

Keep an immutable passing fixture and a record of rejected candidates.
Hold model, reasoning setting, and criterion fixed.
Keep the execution path fixed unless deliberately reducing it; verify changed bindings before interpreting that reduction.
Use fresh disposable state and session context for every run.

1. Remove a substantial input group, such as instruction blocks, unrelated files, history, or dependencies.
   Favor cuts that reduce setup or reveal which context drives the action.
   Retain the requirement whose violation defines failure and, for code reductions, the relevant original behavior.
2. Capture effective inputs and verify the cut, including alternate copies.
   Shorter stdin with a longer reread packet is a different reduction; discovered instructions, aliases, and inherited context can restore removed inputs.
3. Apply the unchanged criterion.
   Poor reasoning without the required action fails the reduction.
   Adding an easier defect or telling the agent to skip the requirement changes the task.
4. Retain only candidates meeting the agreed repeatability check.
   With two-out-of-two, a miss disqualifies that configuration: restarting the count cannot manufacture success.
   Further runs of rejected candidates need a separate diagnostic purpose.
5. After a failed cut, return to the last passing fixture and try a smaller cut or different group.
   Test combined cuts even when each passes separately; separate successes do not establish the combination.

Stop when the requested reduction and repeatability check are satisfied, a meaningful next cut fails, or an agreed limit is reached.
Keep the passing fixture that best serves the objective, smaller tested conditions, and rejected cases showing an observed boundary.
Name untested dimensions; a bounded search establishes no global minimum.

## Leave a reproducible result

Provide a runnable entry point and fixture with model/settings, effective instructions, tool behavior, and state identity.
Preserve baseline, controls, reduction lineage, valid/invalid status, raw action evidence, and counts—including unsuccessful samples.
Record retained changes separately from transient edits and completion claims.

Distinguish historical observations, fresh original-baseline trials, and derived-fixture trials.
A reconstruction's non-reproduction establishes only that condition's outcome; an untested original baseline has not failed reproduction.

For minimization, explain the retained setup's improvement, material cost regressions, and tested cuts that stop reproducing or become intermittent.
Identify the smallest tested passing setup if different from the retained choice.
For evaluations without reproduced failure, report outcomes and scope exercised.
State validation limits and include token use and elapsed time when available; unmeasured costs support no efficiency claim.
