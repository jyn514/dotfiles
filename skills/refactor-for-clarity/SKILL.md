---
name: refactor-for-clarity
description: Refactor existing code for readability and understanding while preserving behavior and supported contracts. Use for requested or authorized clarity passes, making code easier to follow, exposing domain concepts or invariants, or implementation edits for a walkthrough, literate example, or teaching. Not for explanation-only requests, ordinary bug fixes, formatting-only changes, general cleanup discovery, current-patch review, or selecting new architecture; architecture-design owns unsettled boundaries and whether a structural split earns its cost.
---

# Refactor for clarity

Make the existing code easier to understand without changing what its consumers observe.
The requested or authorized outcome sets the scope; this skill does not authorize a broader cleanup.
Use [Coding judgement](../coding-judgement/SKILL.md) and its applicable references for implementation and verification procedures.
Its [code-structure guidance](../references/code-structure.md#make-concepts-visible) supplies the readability standard.
An ordinary bounded clarity refactor needs no separate plan, issue, or architecture workflow.

## Establish what the reader needs to understand

Identify the code to improve and the activity it should support: following an operation, modifying a rule, checking an invariant, or learning from a walkthrough.
Use any named audience and explanatory goal; do not impose a tutorial on an ordinary readability request.
If the target is missing and cannot be inferred from the task, ask for it before editing.
Distinguish permission to change implementation from a request only to explain or assess it.

Read the actual entrypoint, affected callers, implementation, and same-path tests.
Trace the inputs, transformations, effects, failures, and results through to a consumer.
Identify the supported interfaces and observations that must stay unchanged, including ordering, diagnostics, persisted data, and resource lifetime where relevant.
Use repository instructions and existing contracts rather than assuming the tests describe every supported behavior.

## Find and remove conceptual friction

Locate where the reader must infer a concept, remember an unexplained distinction, or mentally execute code to discover its purpose.
Name the concrete difficulty before choosing an edit.
Compare a direct local improvement with a larger reshaping; choose the smallest coherent change that makes the intended understanding possible.

Apply the [canonical code-structure standard](../references/code-structure.md#make-concepts-visible) to the identified friction.

For example, a retry loop may compute both a deadline and a delay before the next attempt.
If both are called `time`, rename them for those roles and make the deadline check visible before sleeping.
Keep the existing clock reads, comparison, and sleep order: moving them to make the loop look tidier can change which attempts occur.
A comment can explain why a final attempt is allowed at the deadline if that rule is not evident from the names and condition.
The improvement exposes the rule without inventing a new retry policy or framework.

Stay within settled ownership and contracts.
If the clarity problem requires choosing a new subsystem boundary or changing a guarantee, use [Architecture design](../architecture-design/SKILL.md) for that decision within the task's authority.
Do not silently fold bug fixes, performance changes, new dependencies, or incompatible behavior into the refactor.
Separate any such finding from the behavior-preserving work and resolve its authorization before making the dependent change.
Continue useful clarity improvements that do not depend on it.

## Verify the refactor and its explanation

Use the repository's native checks and [testing guidance](../references/testing.md) to exercise affected consumers and supported interface modes.
Compare the diff against the preserved observations, including effects and failure paths; passing existing tests alone does not establish equivalence.
Add focused characterization coverage when a relevant observation lacks protection, keeping intended behavior distinct from an incidental implementation detail.
Do not rewrite expected results to accommodate a behavior change presented as simplification.

Read the revised path in the order a caller or future editor encounters it.
Can the reader now identify the concept or invariant that motivated the change without tracing unrelated machinery?
Stop when the requested understanding is supported, not when every nearby imperfection is removed.
For an explicitly requested walkthrough, explain the operation through concrete inputs and stages and point to the code that carries each concept.
Otherwise report the main clarity improvement, preserved contracts, checks, and any unresolved verification limit without producing an unsolicited tutorial.
