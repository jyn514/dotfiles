---
name: pain-axis
description: Analyze code history to learn from failures, repair sequences, and successful designs. Use before redesigning a legacy or failure-prone subsystem to identify recurring architectural pain and candidate invariants, or for open-ended research into historical defects, regressions, reverts, and preserved guarantees across codebases. Not ordinary line provenance, current-change review, design selection, or agent-compliance research.
---

# Pain axis

Learn from what a design allowed, what its repairs changed, and which guarantees survived.
Use one of two modes:

- **Pre-redesign analysis:** identify recurring architectural pain in a selected subsystem and candidate mechanically enforceable invariants.
- **Historical-design research:** investigate a failure, repair sequence, or successful design to discover transferable lessons and useful counterexamples.
  One case can be worthwhile; recurrence, a preselected subsystem, and an enforceable invariant are not prerequisites.

## Scope and authority

Start from the request's repositories, question, and permitted effects.
If no repository or case is named, start in the current repository unless the request authorizes broader discovery.
For pre-redesign analysis, establish the target subsystem or design question before collecting history.
For open-ended research, begin with a concrete case in the authorized repositories; the case may reveal the question to pursue.
Choose cases for the behavior they expose, not merely recent activity, familiar projects, or convenient commit titles.
Follow relevant upstream history and discussions when access and scope permit.

This skill produces evidence and research conclusions, not a design recommendation or implementation.
Inspection does not authorize edits, experiments, publication, or changes to skills.
Use `jj-workflow` for history operations and ordinary provenance questions, `architecture-design` for a separately requested design decision,
`work-selection` when choosing the next investigation or application target, and `skill-authoring` before recording a lesson as guidance.
Session-history research into whether agents followed instructions is a separate activity; code history alone does not establish compliance.

## Select evidence for the question

Choose available records for the open question, not a mandatory set of sources for every case.

- **Rationale and alternatives:** inspect review conversations and rejected proposals.
  Follow corrections to the diagnosis and reasons for keeping or rejecting an alternative, not only the accepted patch.
- **Actual-use assumptions:** inspect integration attempts, support questions, and abandoned approaches.
  Look for consumer obligations or difficulties missing from the author's intended usage.
- **Maintainability over time:** inspect feature requests, migrations, and operational history when claiming a design accommodates change well.
  Identify which changes stayed easy and which distinctions remained necessary.
  One protected behavior alone does not establish successful evolution.
- **Comparative design:** compare implementations of the same operation while establishing each one's requirements independently.
  Expose differing contracts rather than requiring identical ones.
  Explain where costs and obligations move before attributing a difference to a language, paradigm, or representation.

Talks and papers can supply design arguments and leads to concrete cases; distinguish a speaker's explanation from inspected implementation evidence.
Neither a polished account nor a review's acceptance establishes that its claims about behavior are correct.

## Reconstruct the case

1. Use bug-fix commits, reverts, repeated refactors, issues, and coupled changes as leads where relevant to the question.
   Include successful optimizations and designs that preserve important distinctions, not only defects.
   Read the relevant patches, surrounding code, tests, and available discussions before accepting the stated diagnosis.
2. Establish the actual before-and-after revisions and lineage, including renamed files or earlier repair attempts when relevant.
   Identify the governing behavior and a concrete input, action sequence, or interleaving that exposes the failure or protected guarantee.
   Separate the author's explanation from what the code and evidence establish.
3. Trace the mechanism through the consumer that experiences the failure or preserved behavior.
   Check the complete path, including later filtering, normalization, cleanup, and error handling where they can change the result.
   For an attempted repair, identify what it changes, what it must leave untouched, and whether it removes the cause or only a symptom.
4. Inspect subsequent changes when they can establish whether the repair was adequate or expose a different fault.
   Do not treat successive patches as proof of one root cause.
   A committed test is evidence of an expectation, not evidence that it ran, passed, or detected the historical defect.
   Distinguish recorded failures, source-derived predictions, and reproduced behavior; retain gaps in execution records.

## Analyze in the selected mode

### Pre-redesign analysis

Look for recurring failure dimensions such as ownership confusion, invalid states, duplicated authorities, lifecycle mistakes, and synchronization errors.
Inspect repeated coupled edits, distinguishing cosmetic co-change from architectural coupling.
Do not treat raw co-change frequency as causation.
Identify candidate invariants that would have prevented the supported historical failures and how they might be enforced.
Produce evidence for the design decision without selecting the replacement architecture.
Novel requirements may lack historical evidence; report that limitation rather than treating the prior design as sufficient.

### Historical-design research

State the lesson, its supporting mechanism, and the conditions under which it applies.
A useful result may be a counterexample, an effective test shape, a protected design, or a reason not to change anything.
Do not force every case into a recurring pain category, universal rule, or mechanically enforceable invariant.

When repairs accumulate, ask whether they compensate for the same mistaken assumption or address independent requirements and faults.
Name the shared assumption before calling the sequence compensating complexity.
Check whether changing it would actually remove the repairs while preserving the required behavior.
Historical awkwardness can protect a real constraint; simplification is not sufficient justification for removing it.

For transfer, identify another consumer whose operations exercise the relevant distinction and inspect its contract and safeguards independently.
A resemblance suggests a question, not a defect or a new preservation requirement.
When applicability is weak, compare changing the application target with changing the idea using `work-selection`.
Do not require each source to yield a bug or scan every repository before drawing a bounded conclusion.

## Report and stop

Keep the result proportional to the question and link conclusions to concrete revisions, files, tests, or discussions.
For pre-redesign analysis, report the supported `pain_axes`, `historical_examples`, `cochange_signals`, `candidate_invariants`, and `uncertainties`.
For historical-design research, report the case, prior attempts and repair adequacy, supported lesson and limits, and useful disposition:
a focused bug investigation, a worked example, a candidate skill change, further research, or no action.
Separate newly suspected defects from the recorded historical failures.

Stop the bounded investigation when the evidence answers its question or identifies a precise unresolved dependency.
Further research must serve an open question that can change the conclusion; an interesting case alone does not require a new process or rule.
Do not infer broad exhaustion from a few poor fits or absence of an immediate local bug.
