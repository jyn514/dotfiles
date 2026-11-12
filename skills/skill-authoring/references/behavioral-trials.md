# Behavioral trials

Read this reference before arranging behavioral trials or using agent behavior as evidence.
This includes passive observation, paired comparisons, and summarization trials.
Edits and textual reviews do not require a behavioral trial by default.

## Choose the claim and scope

State the question being tested and what observations could change the answer.
Distinguish what is being evaluated from its surrounding setup.
Name what may vary and what must remain fixed; simplifying the fixture must not silently change that boundary.

For example, suppose a trial asks whether a compiler-reporting agent recommends against filing a crash already fixed on a newer toolchain.
A small standalone Rust input compiled with prebuilt toolchains can avoid a full Rust checkout and compiler build while preserving that decision.
Replacing it with a CSV-encoding bug in a Rust application changes the owner of the defect: correctly routing the application bug away from Rust does not exercise the intended compiler-reporting decision.
Keeping the skill text, implementation language, and expected recommendation unchanged does not preserve the experiment.

Do not turn an action being measured into a setup requirement.
For example, when testing whether an agent chooses an available tool, preserve availability but leave the choice to the agent.
When testing how it interprets a supplied tool result, that result belongs in the starting state.

Distinguish a useful answer, a changed research action, and reliable compliance; they require different evidence.
Use the trial criteria to construct and interpret it; do not add a separate scoring rubric unless requested.

For a failure-driven comparison, begin with the failure task and a nearby control before adding variants or domains.
For a fresh paired comparison, run the baseline first.
Treat the fixture as a hypothesis until it reaches the intended decision through the assembled path.
Establish one representative case and control before expanding the collection; passing setup and producing an answer are not enough.

If the baseline does not reproduce a failure, do not credit the revision with fixing it.
Choose one of these outcomes:

- Repeat a bounded comparison.
- Assess a different observed behavior explicitly.
- Stop and report an inconclusive result.

When the next decision depends on consistency, repeat the matched comparison before widening the task matrix.
When it depends on transfer, add a task outside the originating domain instead.
Repetition does not remove confounding from changing retrieval results, task state, or instruction exposure.

## No leading questions

When testing judgment under ambiguity, give a realistic task rather than a question that names the intended distinction.
Apply this to imperatives and fixture helpers too: “check this archive” supplies the inspection task, and a script that compares toolchains supplies the comparison decision.
Ask for the user's outcome without naming the procedure or artifact the agent should discover.
Explicit review and authoring requests can test permission boundaries, but do not establish spontaneous discovery of those tasks.
Follow the requested brevity and style; inspect existing trials before inventing a new prompt format.
Include the user's symptom or attempted command, but do not name checks, missing evidence, or permissible actions the agent is supposed to infer.
For example, a reported crash on a particular compiler can test whether the agent checks the latest nightly without mentioning nightly in the prompt.
Asking whether the channel checks are complete tests a prompted check instead.

Put discoverable facts in runnable inputs, project state, and raw evidence the agent must inspect.
Do not merely move the reference answer into a file of evaluator-authored conclusions.
Keep required facts available without telling the agent their significance; ambiguity should concern the judgment, not whether the fixture exists.

The whole agent-visible setup can prompt behavior, including workspace files and tool descriptions.
If lookup is under observation, copying verbatim upstream reporting forms beside a standalone reproducer supplies part of that lookup.
Make the forms retrievable through ordinary actions instead.
Preserve them when they already belong to the normal starting repository; do not remove normal context just to force discovery.

Do not add warnings that steer the measured decision when capability limits already protect the relevant real state.
For example, withholding tracker credentials may prevent live submissions without a “must not submit” instruction that coaches refusal.
Preserve actual governing permission rules; distinguish them from evaluator-added cautions.

Request an action explicitly when testing how it is carried out, not when testing whether the agent decides to take it.
Do not turn historical replay inputs into coaching; preserve the original request at the chosen cut.

## Check for legitimate ways around the intended decision

Before expanding a fixture, try the supplied command and inspect the state through the intended execution environment.
Ask whether an agent can correctly finish, refuse, or stop for a reason that never exercises the target judgment.
Check for unavailable toolchains, missing reproducers, known-bug markers and linked resolutions, ordinary expected errors, and explicitly unsupported configurations.
These conditions can be the subject of a trial, but cannot stand in for a different failure just because they produce a plausible response.

For example, a crash-reporting trial using an unavailable stage1 compiler and a test marked with an existing issue number can end at setup failure or duplicate handling.
That run does not test compiler provenance or fresh version comparisons.
Use a runnable reproducer without that shortcut, or label the trial as testing the decision it actually reaches.
Do not fabricate a compiler defect from an ordinary type error or an unstable feature rejected on stable.
If the required reproducer is unavailable, obtain it or leave that trial unready rather than substituting an easier fault.

Inspect which decision the agent actually reaches, including legitimate early exits; a zero process exit or a reasonable final answer does not establish coverage of the intended judgment.
When feedback exposes a fixture shortcut, inspect related cases for the same construction error rather than repairing only the named example.

## Match instruction exposure to the claim

When instructions are part of the trial, test them through the delivery path whose behavior matters: startup injection, file reads, or task messages.
Decide whether receiving those instructions is a prerequisite or the behavior under test.
For claims about behavior after loading, verify that the actual instruction body reached the agent through startup context or a successful read.
For discovery or loading trials, failure to load is a valid outcome, not by itself an invalid run.
Do not preload the body or remind the agent to read it when that would supply the decision being tested.
For claims about deployment in root sessions, use fresh or correctly reloaded root sessions with the normal startup path.
Do not require root sessions when worker, continuation, or handoff behavior is the subject of the trial.
Inspect the effective instructions in both conditions, including automatic context injection, before interpreting their outputs.
A complete read result establishes exposure to that text, not exposure at system-instruction priority or automatic startup loading.
Check that the baseline has not inherited the revised rule through another instruction source.
If the deployment path cannot be tested, a bounded explicit-load or worker comparison can still test behavior after delivery.
Label that substitution and limit the conclusion; it does not test deployment or independent discovery.

## Observe ongoing work

When observing ongoing work, inspect the existing transcript, artifacts, and ordinary completion events.

Do not announce the evaluation or disclose its criteria to the observed agent.
Do not request evaluation-specific reports from that agent.
When a result is not yet available, wait for normal completion evidence rather than asking the observed agent to produce monitoring callbacks.

When the comparison assumes loaded instructions, deliver the change and request loading if needed to establish that condition.
Keep that notice separate from evaluation instructions, and verify exposure from the resulting record.
When discovery or loading is under observation, do not supply that reminder; observe whether loading occurs.

If task needs justify further coaching or intervention, provide it within the existing authorization, but record it as an additional influence.
Do not attribute subsequent improvement to the change under test alone.
When passive observation cannot provide enough evidence, report that limit rather than changing the observed workflow merely to make evaluation easier.

## Replay and paired trials

### Preserve history and isolate state

For trials based on a past session, directly resume or fork the original session at the decision point by default.

Preserve its actual messages, tool calls, and tool results.
Do not replace them with a summary or a new user message quoting the history.
Protect the original session and real user state from replayed actions.
Use disposable resources for state those actions can modify.

A conversation fork preserves messages, not filesystem or runtime state.
Relevant inputs can include current source files, unsolicited messages, and automatic context injection.

### Choose the historical cut

Trace the failure backward to the earliest unsupported inference or commitment the test asks a fresh continuation to make.
Cut before that choice while retaining the feedback needed to reach it; the last user message is not automatically the right cut.
Include preceding diagnostic results, user corrections, and recorded compaction when they occur before the chosen judgment.
Do not include the original faulty plan or action when testing whether the continuation independently chooses it.
A later-stage trial of carrying out an existing plan measures follow-through, not independent choice; label it separately.

### Choose the state and handoff method for the tested behavior

Use a real handoff packet instead only when the handoff or receiver behavior is itself the subject of the trial.
A handoff trial does not establish how the original agent would continue or whether its decisions improve.
If the original session is unavailable or cannot be resumed, report that limitation and label reconstructed inputs as an approximation.

Neither history preservation nor mutation isolation by itself requires reconstructing the historical filesystem.
Start with the closest available runnable state that preserves governing requirements and the evidence available at the chosen judgment.
Restore relevant historical state when the comparison question requires it; otherwise disclose differences and their possible effects.
For failure reproduction, try this condition before recovering unrelated environmental details.
If a condition fails its reproduction check, use the trace to identify a concrete missing input or execution difference.
Restore fidelity there if another reproduction attempt is warranted.
Freeze each changed condition and report its counts separately.
Once the failure meets the chosen repeatability check, stop fidelity recovery.
Proceed to the requested comparison or minimization.
If no supported, recoverable fidelity increment remains, report the reproduction limit rather than repeat unchanged trials just to obtain a failure.
A bounded revised-only replay may use recorded earlier outputs for comparison; report it as a quality observation, not a controlled experiment.
Do not block that replay solely because a fresh baseline is unavailable.

### Verify the tested conditions

Verify the conditions required by the trial through the path the agent actually uses.
Inspect actual actions and outputs; investigate a failed setup check before expanding the replay.
A setup declaration or successful helper test does not establish that the intended condition reached the agent.
A separately rendered debug request is not necessarily the request actually submitted to the model.
Inspect the full relevant continuation, including earlier responses and actions at the tested decision.
An interface that shows only the latest final response may hide those earlier outputs.

Preserve normal coordinator tools and native completion delivery when assessing delegation, coordination, or latency.
Removing tools can force extra delegation; manual result bridging can introduce pauses absent from the real workflow.
If isolation changes either, record the differences and do not attribute the resulting delegation or waiting to the guidance under test.

Before paired trials, fix the comparison question, outcome criteria, and conditions that will be held constant.
Vary only what the comparison is intended to test.
For a prompt-only comparison, replace the original prompt at the same point in otherwise unchanged context.
Appending a corrective message, removing prior investigation, or moving evidence earlier tests a different intervention.
Disclosing those differences does not restore comparability.
If the available harness cannot perform the replacement, report that limitation before substituting a different trial.
Inspect the exact worker inputs and keep reference outputs and later diagnoses out of them.
Judge actual decisions and actions afterward, not just formatting or workflow compliance.
For compound outcomes, distinguish evidence for individual causal links from evidence that the links occur together.
Do not require one example to demonstrate every link when separate evidence could already change the assessment.
Separate examples do not establish the combined outcome.
Separate recorded actions from verified source support.
Search queries and page-open records show research targeting, not everything retrieved or read.
An independent post-run source check can support an answer's factual claims, but cannot establish that the worker performed the same investigation.

For a failure-driven revision, use the inputs available at the recorded failure decision point.
Include a nearby control that should retain its existing path.
For example, pair a decision about replacing custom profiling instrumentation with an obvious mechanical repair that needs no redesign.
Test whether the new guidance changes the failure decision without adding unnecessary steps to the control.

## Example: revising an artifact-writing skill

Suppose an introductory README task requires a whole-document reading-quality score of at least 3.
Choose a difficult README and a nearby case that the previous skill handled well before generating a large batch.
The new draft may explain one mechanism through a satisfying example while the remaining configuration inventory still makes the complete reading experience a 2.
That is a useful passage-level improvement, not acceptance of the complete artifact.
Generate and judge the control again under the revised skill; its saved earlier 3 does not establish what the revised skill produces.
If the new control is a 2, withhold a broad success claim and inspect the actual prose before expanding the batch.
One generation does not establish that the skill caused the difference rather than sampling variation.

Keep three comparisons distinct:

- The original document establishes whether the revision improves on what the user already had.
- An earlier skill's generated output preserves a usable partial result and evidence about that earlier condition.
- A freshly generated control tests the revised skill on a previously successful task.

Without the original-document comparison, report acceptable candidate quality rather than demonstrated improvement over the original.
A skill change does not erase an earlier useful artifact, but its score cannot stand in for newly required evidence about the changed skill.
Use the governing task to determine which acceptance checks need rerunning; this example does not require every skill edit to regenerate every historical output.

A first pass may fix obvious problems while leaving subtler ones untouched.
When revision is part of the intended workflow, inspect successive drafts and judge what each pass improves or damages.
A fresh reader can provide another perspective; neither fresh agents nor a fixed number of passes are required.
Record feedback supplied between passes so you do not attribute improvement to repetition or the skill alone.

## Report scope and cost

Retain available raw events and tool results, including exit statuses, rather than keeping only a rendered summary.
For CLI trials, retain the stdout event stream and stderr separately, including partial output from failed runs.
State what the backend does not expose; missing evidence does not establish that an action did not occur.

For each variant, report task outcomes alongside token use and elapsed time where available.
Include tool and review overhead when they are part of the compared workflow; separate shared experiment setup from execution cost.
Assess the change under test against the existing workflow.
If costs are unmeasured, report quality observations without claiming efficiency or net benefit;
one task does not establish general reliability.

For summarization trials, distinguish incremental replay (previous checkpoint plus subsequent history)
from blind reconstruction (preceding raw history without reference summaries or later critique).
Blind reconstruction must restore the underlying raw history, not merely delete the previous checkpoint.
These are different tasks; do not treat their outputs as a same-input comparison.
