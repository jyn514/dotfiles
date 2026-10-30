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

Use the repositories, question, and permitted effects named in the request.
If it names no repository or case, start in the current repository unless broader discovery is authorized.

For pre-redesign analysis, define the target subsystem or design question before collecting history.
For open-ended research, start with a concrete case in the authorized repositories; let the case help identify the question.
Choose cases for the behavior they expose, not just because they are recent, familiar, or easy to find by commit title.
Follow relevant upstream history and discussions when access and scope permit.

Produce evidence and research conclusions, not a design recommendation or implementation.
Inspection does not authorize edits, experiments, publication, or skill changes.

Route adjacent work to its owner:

- Use `jj-workflow` for history operations and ordinary provenance questions.
- Use `architecture-design` for a separately requested design decision.
- Use `work-selection` to choose the next investigation or application target.
- Use `skill-authoring` before recording a lesson as guidance.

Researching whether agents followed instructions through session history is separate work.
Code history alone cannot establish compliance.

## Select evidence for the question

Choose records that answer the open question; do not require every source type in every case.

- **Rationale and alternatives:** Read review conversations and rejected proposals when they bear on the question.
  Follow corrections to the diagnosis and the reasons for keeping or rejecting alternatives, not just the accepted patch.
- **Assumptions about actual use:** Read integration attempts, support questions, and abandoned approaches when available.
  Look for consumer obligations or difficulties missing from the author's intended usage.
- **Maintainability over time:** When claiming a design accommodates change well, inspect relevant feature requests, migrations, and operational history.
  Identify which changes remained easy and which distinctions were still necessary.
  One protected behavior does not by itself establish successful evolution.
- **Comparative design:** When comparing implementations of the same operation, establish each implementation's requirements independently.
  Show where their contracts differ instead of requiring them to be identical.
  Before attributing a difference to language, paradigm, or representation, explain where the costs and obligations move.

Talks and papers can supply design arguments and leads to concrete cases; distinguish a speaker's explanation from inspected implementation evidence.
Neither a polished account nor a review's acceptance establishes that its claims about behavior are correct.

## Reconstruct the case

1. **Find useful leads.** Use bug-fix commits, reverts, repeated refactors, issues, and coupled changes when they bear on the question.
   Include successful optimizations and designs that preserve important distinctions, not only defects.
   Before accepting a stated diagnosis, read the relevant patches, surrounding code, tests, and available discussions.
2. **Establish the behavior and case.** Identify the governing behavior and a concrete input, action sequence, or interleaving that exposes the failure or protected guarantee.
   For a change or repair, establish the before-and-after revisions and lineage, including renamed files or earlier attempts when relevant.
   Separate the author's explanation from what the code and evidence establish.
3. **Trace the mechanism.** Follow the path through the consumer that experiences the failure or preserved behavior.
   Check later filtering, normalization, cleanup, and error handling wherever they could change the result.
   For an attempted repair, identify what it changes, what it must leave untouched, and whether it removes the cause or only a symptom.
4. **Check what happened afterward.** Inspect later changes when they could show whether the repair was adequate or reveal a different fault.
   Do not treat successive patches as proof of one root cause.
   A committed test shows an expectation; it does not prove the test ran, passed, or detected the historical defect.
   Distinguish recorded failures, predictions derived from source, and reproduced behavior.
   Preserve gaps in execution records.

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
For historical-design research, report the case, supported lesson and limits, and useful disposition:
a focused bug investigation, a worked example, a candidate skill change, further research, or no action.
For a change or repair, include prior attempts and repair adequacy where relevant.
Separate newly suspected defects from the recorded historical failures.

Stop the bounded investigation when the evidence answers its question or identifies a precise unresolved dependency.
Further research must serve an open question that can change the conclusion; an interesting case alone does not require a new process or rule.
Do not infer broad exhaustion from a few poor fits or absence of an immediate local bug.
