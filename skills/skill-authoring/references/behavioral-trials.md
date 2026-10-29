# Behavioral trials

Read this reference before arranging behavioral evidence about a prompt or skill change, including passive observation, or preparing paired behavioral or summarization trials.
Skill edits and textual reviews do not require a trial by default.

## Choose the claim and scope

State which decision the trial should change and what observation would change it.
Distinguish a useful answer, a changed research action, and reliable compliance; they require different evidence.
For a failure-driven comparison, begin with the failure task and a nearby control before adding variants or domains.
For a fresh paired comparison, run the baseline first and verify that it reaches the decision being tested before expanding the comparison.
If the baseline does not reproduce a failure, do not credit the revision with fixing it.
Choose a bounded repeat, assess a different observed behavior explicitly, or stop with an inconclusive result.
When the next decision depends on consistency, repeat the matched comparison before widening the task matrix.
When it depends on transfer, add a task outside the originating domain instead.
Repetition does not remove confounding from changing retrieval results, task state, or instruction exposure.

## Match instruction exposure to the claim

Test instructions through the delivery path whose behavior matters: startup injection, an explicit file read, or a task message.
For claims about deployment in root sessions, use fresh or correctly reloaded root sessions with the normal startup path.
Do not require root sessions when worker, continuation, or handoff behavior is the subject of the trial.
Inspect the effective instructions in both conditions, including automatic context injection, before interpreting their outputs.
A complete read result establishes exposure to that text, not exposure at system-instruction priority or automatic startup loading.
Check that the baseline has not inherited the revised rule through another instruction source.
If the deployment path cannot be tested, a bounded explicit-load or worker comparison can still provide useful observations.
Label that substitution and limit the conclusion; do not describe it as a deployment test.

## Observe ongoing work

When observing ongoing work to judge whether guidance helped, inspect the existing transcript, artifacts, and ordinary completion events.
Do not announce the evaluation, disclose its criteria, or request evaluation-specific reports from the agent being observed.
When a result is not yet available, wait for normal completion evidence rather than asking the observed agent to produce monitoring callbacks.

Deliver the changed instructions and request that they be loaded when needed to establish exposure.
Keep that notice separate from evaluation instructions, and verify exposure from the resulting record before judging behavior.

If task needs justify further coaching or intervention, provide it within the existing authorization, but record it as an additional influence.
Do not attribute subsequent improvement to the prompt or skill change alone.
When passive observation cannot provide enough evidence, report that limit rather than changing the observed workflow merely to make evaluation easier.

## Replay and paired trials

For trials based on a past session, directly resume or fork the original session at the decision point by default.
Preserve its actual messages, tool calls, and tool results; do not replace them with a summary or a new user message quoting the history.
Protect the original session and real user state from replayed actions.
Use disposable resources for state those actions can modify.
A conversation fork preserves messages, not filesystem or runtime state.
Relevant inputs can include current source files, unsolicited messages, and automatic context injection.
Neither history preservation nor mutation isolation by itself requires reconstructing the historical filesystem.
Use current task state and report differences that could change the decision, or restore the relevant historical state.
Choose according to the comparison question; these are alternatives, not sequential steps.
Control relevant differences or disclose their limits on the comparison.
A bounded revised-only replay may use recorded earlier outputs for comparison; report it as a quality observation, not a controlled experiment.
Do not block that replay solely because a fresh baseline is unavailable.
Inspect actual actions and outputs; investigate a failed check before expanding the replay.

Verify that the updated instruction body successfully loaded before treating a continuation as evidence about its behavior.
A reload, a read attempt, or a completed answer alone does not establish exposure to the updated instructions.
Inspect the full relevant continuation, including earlier responses and actions at the tested decision.
An interface that shows only the latest final response may hide those earlier outputs.

Use a real handoff packet instead only when the handoff or receiver behavior is itself the subject of the trial.
A handoff trial does not establish how the original agent would continue or whether its decisions improve.
If the original session is unavailable or cannot be resumed, report that limitation and label reconstructed inputs as an approximation.

Preserve normal coordinator tools and native completion delivery when assessing delegation, coordination, or latency.
Removing tools can force extra delegation; manual result bridging can introduce pauses absent from the real workflow.
If isolation changes either, record the differences and do not attribute the resulting delegation or waiting to the guidance under test.

For paired behavioral trials, fix the comparison question, outcome criteria, historical cut, model, and task inputs before generation;
vary only the instruction change under test.
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

## Report scope and cost

For each variant, report task outcomes alongside token use and elapsed time where available.
Include tool and review overhead when they are part of the compared workflow; separate shared experiment setup from execution cost.
Assess the added skill against the existing workflow.
If costs are unmeasured, report quality observations without claiming efficiency or net benefit;
one task does not establish general reliability.

For summarization trials, distinguish incremental replay (previous checkpoint plus subsequent history)
from blind reconstruction (preceding raw history without reference summaries or later critique).
Blind reconstruction must restore the underlying raw history, not merely delete the previous checkpoint.
These are different tasks; do not treat their outputs as a same-input comparison.
