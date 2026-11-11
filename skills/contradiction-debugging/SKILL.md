---
name: contradiction-debugging
description: Investigate failures that seem impossible under the current model of a system. Use when observed behavior contradicts an invariant, source inspection says a reported failure cannot happen, or repeated successful probes leave a historical failure unexplained. Covers software, distributed systems, and agent tooling. Not a required procedure for ordinary reproducible bugs; use performance-investigation or process-debugging for their specialized diagnostics.
---

# Debug apparent contradictions

Find which premise fails before choosing a repair.
Start with the disputed event; include related events only when they distinguish explanations.
Investigation alone does not authorize fixes, live reloads, messages to agents, or external replays.

## State the contradiction precisely

Write the observation and the rule that appears to exclude it, using the original event or artifact when available.
Identify the evidence and observation point for each of three claims:

- The implementation excludes this result under stated conditions.
- Those conditions held during the failing event.
- The observation accurately represents the result.

Retain the full scope of a multi-session or multi-process failure; explaining its easiest instance is not enough.
The unsupported claim determines what to inspect next.
An unlikely timing, fallback, or model choice remains possible; improbability does not establish an invariant.
In a nondeterministic system, different outputs alone do not establish different inputs.

Suppose a process logs an old configuration value while the file contains the new value.
The file contradicts the log only if this process loaded those bytes and activated them before the operation.
Track when the bytes reached disk, when the process loaded them, and when they became active after reload, restart, or reboot.
Inspect the loaded value and activation boundary to distinguish stale process state from a bad file or log.
Before ranking changes that share an activation boundary, list each input, the boundary that made it effective, and the symptom it could directly explain.
A shared reboot does not make them one cause.

## Locate the first unsupported connection

Trace the disputed value from its source to the consumer that acted on it, including transformations, cached or persisted copies, fallbacks, and failure paths.
Locate each decisive observation in its process or session, machine or namespace, resource, and time.
Check the failing process's executable and configuration where retained evidence permits; today's installation cannot establish what it ran.
Likewise, a guest installation or limit cannot rule out a failure elsewhere.

Start at the visible symptom and work back to the earliest failed prerequisite on which later symptoms depend.
When cases differ, find their first divergent branch or boundary.
A failed load or bind can distinguish causes that the final user-visible breakage cannot.
Read the producer and consumer around that boundary.

Choose evidence by what its observer can see:

- A stored transcript may precede runtime transformations.
- A debug hook may precede later hooks or serialization.
- A rendered tool call may abbreviate an argument that differs in the raw record.
- An agent's quotation of its instructions is a report, not a capture of its received request.

Keep reports as evidence with those limits, rather than treating them as direct captures or fabrication.
When observations disagree, prefer a capture at the last observable boundary before consumption.
Verify coverage of the relevant event, field, and ordering before interpreting an empty or successful capture.
Pair input and action from the same operation where possible.
A correct request in one operation and a bad action in another do not establish a correct-input/bad-action pair.

## Choose a check that separates explanations

Keep a small set of mechanisms that fit the event, including a mistaken premise or measurement when plausible.
Keep related defects separate until evidence connects them to the event.
For each serious candidate, identify the cheapest observation that would contradict it.
Choose an available check that separates the leading explanations instead of extending the candidate list.
Use work-selection before adding another substantive diagnostic round.

When two plausible changes precede failure, test an off-diagonal case before blaming either.
For example, run the old binary with the new configuration rather than comparing only the old and new pairs.
If it produces the same failure, the upgrade is not a necessary trigger; if it succeeds, the upgrade or an interaction remains plausible.
The reverse pairing or another cheap split may separate the candidates better.
Choose the smallest case whose outcomes would change which explanation survives.

When tests pass but the failure persists, inspect what they replace, omit, or assume at the disputed boundary.
Component success need not survive composition, and a test of a proposed fix need not explain the incident.
Trace the failing operation before extending the fix; reproduce it on the unchanged implementation when feasible.

Before a live probe or replay, check authorization for the actor, target, mutation, and external destination.
Historical approval and another agent's permission do not grant new authority.
Use disposable state; copied credentials can still rotate or invalidate a shared server-side grant.
Bound instrumentation by target, fields, count or duration, and cleanup condition.
Collect distinguishing data rather than entire transcripts or credentials by default.

## Interpret replays without rewriting history

Distinguish an exact captured request from a reconstruction using historical messages and current machinery.
Identify differences that could affect the disputed behavior, such as instructions, versions, state, truncation, model, or serialization.
Use the actual consumer interface when practical: a substitute may test a different contract.
For agent requests, inspect final instructions and proposed action together; quoting a path and trying to read it test different behavior.

Current success establishes that the tested path works now; a successful reconstruction establishes that its reconstructed conditions can succeed.
Neither establishes the historical cause, disproves the report, or demonstrates a fix without evidence of a relevant change.
A synthetic failure establishes a possible mechanism; check whether its triggering conditions existed in the incident.
Retain failed experiments and inspect their failures before replacing the setup.

## Finish at the strongest supported conclusion

Report the observed failure, explanations eliminated within their tested scope, and remaining discriminating evidence.
Distinguish a reproduced cause, a supported but unconfirmed mechanism, current success with historical cause unresolved, and insufficient evidence.
Separate observations, textual reasoning, and untested hypotheses.
Withdraw claims contradicted by new evidence and reassess the next action.
After an authorized fix or workaround, re-check the original symptom before carrying the diagnosis forward.
If it survives, demote that cause and reopen the explanation; partial improvement may identify a contributor without explaining the incident.

When the original request, state, or timing is irrecoverable, stop trying to prove it from later success.
Preserve useful findings in the project's established tracker and identify the smallest capture needed on recurrence.
Remove temporary instrumentation and verify cleanup; leaving a future capture armed requires authorization.
