---
name: contradiction-debugging
description: Investigate failures that seem impossible under the current model of a system. Use when observed behavior contradicts an invariant, source inspection says a reported failure cannot happen, or repeated successful probes leave a historical failure unexplained. Covers software, distributed systems, and agent tooling. Not a required procedure for ordinary reproducible bugs; use performance-investigation or process-debugging for their specialized diagnostics.
---

# Debug apparent contradictions

Find which premise fails before choosing a repair.
Start with the specific disputed event; expand to related events only when they distinguish explanations.
Investigation alone does not authorize fixes, live reloads, messages to agents, or external replays.

## State the contradiction precisely

Write the observation and the rule that appears to exclude it.
Identify the evidence for each, including its time, process or session, and observation point.
Use the original event or artifact when available; a summary can omit the distinction that matters.

Separate these claims:

- The implementation cannot produce this result under stated conditions.
- Those conditions held during the failing event.
- The observation accurately represents that result.

Each needs evidence.
An impossibility argument is conditional on its premises; an unlikely timing, fallback, or model choice remains possible.
For nondeterministic systems, identical captured inputs need not produce identical outputs.
Do not infer a hidden input change solely from different outputs.

For example, a process logs an old configuration value although the file contains the new value.
That contradicts current-file loading only if this process loaded these bytes before that operation.
Inspect the process's loaded value and reload boundary before treating either the file or the log as wrong.

## Locate the first unsupported connection

Trace the disputed value from its source to the consumer that acted on it.
Mark transformations, persisted copies, caches, fallbacks, and exception handling along that path.
Check the executable and configuration actually used by the failing process when retained evidence permits it.
Current source and an installed version do not establish what a past process ran.
Attribute each decisive fact to the process, machine or namespace, resource, and time it describes, as relevant.
Do not use a guest installation, guest limit, or current file to rule out a failure in a different context.
When two cases behave differently, locate the first branch or boundary where their execution differs.

For every observation, ask what it can actually see:

- A stored transcript may precede runtime transformations.
- A debug hook may run before later hooks or serialization change the value.
- A rendered tool call may abbreviate an argument that differs in the raw record.
- An agent's quotation of its instructions is a report, not a capture of the request it received.

Preserve those reports as evidence without promoting them to direct observations or dismissing them as fabrication.
Read the producer and consumer around the suspected boundary, including failure paths.
Prefer a capture at the last observable boundary before consumption when intermediate observations disagree.
Verify that the observer covers the relevant event, field, and ordering before interpreting an empty or successful capture.

## Choose a check that separates explanations

Keep a small set of competing mechanisms that fit the observed event.
Include an incorrect premise or measurement, as well as a system defect, when each is plausible here.
For each serious candidate, identify the cheapest observation that would contradict it.
Do not keep adding speculative candidates when one available check separates the leading explanations.
Use work-selection when another substantive diagnostic round needs justification.

Pair the input observation and resulting action from the same operation where possible.
A correct request in one operation and a bad action in another do not establish a correct-input/bad-action pair.
When the problem occurs in multiple sessions or processes, retain that scope instead of explaining only the easiest instance.
Classify related defects separately unless evidence connects them to the disputed event.

When tests pass while the reported failure persists, identify what the tests replace, omit, or assume at the disputed boundary.
Passing component tests do not establish that their composition works, and a test written around a proposed fix does not by itself explain the incident.
Trace the failing operation before extending the fix; reproduce the failure on the unchanged implementation when feasible.

Bound instrumentation by target, fields, event count or duration, and cleanup condition.
Collect the distinguishing data rather than entire transcripts or credentials by default.
Use disposable state for experiments; copied credentials can still rotate or invalidate a shared server-side grant.
Check authorization for the actor, target, mutation, and external destination before a live probe or replay.
Historical approval and another agent's permission do not grant new authority.

## Interpret replays without rewriting history

Distinguish an exact captured request from a reconstruction using historical messages and current machinery.
List differences that could change the disputed behavior: instructions, versions, state, branch, context truncation, model, or serialization.
Use the actual consumer interface when practical; a substitute can test a different contract while appearing equivalent.
For agent requests, inspect the final instructions and proposed action together; quoting a path and trying to read it test different behavior.

A successful current probe establishes that the tested path works now.
A successful reconstruction shows that the reconstructed conditions can succeed.
Neither establishes the original cause, proves the report false, or demonstrates a fix without evidence of a relevant change.
A synthetic failure establishes a possible mechanism; check whether its triggering conditions existed in the incident.
Retain failed experiments and inspect their failures before replacing them with another setup.

## Finish at the strongest supported conclusion

Report the observed failure, eliminated explanations with their scope, and the remaining discriminating evidence.
Use explicit outcomes: reproduced cause, supported but unconfirmed mechanism, current success with historical cause unresolved, or insufficient evidence.
When evidence contradicts an earlier diagnosis, withdraw the dependent claim and reassess the next action.
Do not replace it with another confident story merely because that story also fits.

If the original request, state, or timing is irrecoverable, stop trying to prove its contents from later success.
Preserve useful findings in the project's established tracker and identify the smallest capture needed on recurrence.
Remove temporary instrumentation and verify cleanup; do not leave a future capture armed without authorization.
Distinguish textual reasoning, observed behavior, and untested hypotheses in the handoff.
