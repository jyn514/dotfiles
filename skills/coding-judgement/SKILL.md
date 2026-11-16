---
name: coding-judgement
description: "Design, implement, or review code, configuration, and tests with a short common core and conditional implementation references. Use before coding work, including routine edits, bug fixes, refactors, and code reviews; load only topics whose concrete triggers match. Not for prose-only writing, general research, or task coordination without coding. Architecture design owns unsettled subsystem boundaries; use-a-library owns finding existing solutions."
---

# Coding judgement

Apply the common obligations below, then read the topic references that match the change.

## Common obligations

Read surrounding context before edits, investigations, or audits.
For behavior changes, trace the affected producer-to-consumer path.
Do not draw broad conclusions from search snippets.
Establish the governing contract and required compatibility, then identify the smallest sufficient change before presenting a design.
Recommend it unless concrete evidence shows it is insufficient.
Prefer fewer interfaces, representations, and ownership boundaries, not weaker correctness checks or fewer tests.
Treat user-suggested mechanisms as candidates unless the user makes them explicit requirements.
When sufficiency is uncertain, use the cheapest decision-changing check rather than a larger architecture.
Routine edits with an established shape need no separate design workflow.
Write new and changed code so its names and structure explain the concepts, not just the sequence of operations.
Keep clarity improvements within the authorized change; deliberate refactoring of existing code for readability uses [Refactor for clarity](../refactor-for-clarity/SKILL.md).

### Change authoritative sources

Never edit generated files, installed package checkouts, caches, staged configuration, or build outputs directly.
Change the authoritative source and regenerate through its owning mechanism.
If the source is external or unavailable, propose an upstream change, fork, or intentional vendoring instead.
Before editing outside the active repository, verify that the user intends work there.

## Choose guidance at the decision

| When the change involves… | Read before acting |
| --- | --- |
| Parsing, regex or hand scanning, encoding, escaping, generated source, command arguments, or shell scripts | [Language boundaries](../references/language-boundaries.md): accepted input, parser/writer ownership, downstream interpretation, separate language files |
| Shared values or records, options, defaults, types/schemas, configuration, reuse, cache invalidation, state equality, trust or privilege crossings, environment access, collaborators, or validation before effects | [Data and effects](../references/data-and-effects.md): identity and authority, narrow dependencies versus forwarding records, absence, preflight, reuse and invalidation |
| Catching or suppressing errors, supplying fallback behavior, cleanup, retry, publication, CLI output, or interrupted multi-step work | [Failures and recovery](../references/failures-and-recovery.md): exact failure conditions, structured errors, equivalent substitutes, partial and unknown outcomes, readable CLI results |
| Writing or reshaping implementation logic, adding or moving helpers/modules, choosing macros or abstractions, changing API/compatibility/resource contracts, editing live-loaded source, writing comments or caller documentation, or diagnosing cross-component failures | [Code structure](../references/code-structure.md): concept-visible code, caller contracts, function/macro choice, editing locality, compatibility and live-loaded code, existing resource owners |
| Traversal, worklists, growing inputs, numerical calculations, threads, callbacks, queues, concurrency, cancellation, optimization, caching, or restricted execution | [Runtime behavior](../references/runtime-behavior.md): stack and deferred depth, context propagation, ordering, progress, resource and arithmetic bounds |
| Implementing nontrivial solved-problem logic such as parsing, file walking, date handling, diffing, graph traversal, or retry/backoff | [Use a library](../use-a-library/SKILL.md): find an existing solution before writing a new one |
| Choosing subsystem ownership, an unsettled contract, or whether a split earns its cost | [Architecture design](../architecture-design/SKILL.md): trace the gap and compare boundaries; settled local implementation uses the references above |

A local variable rename needs the common obligations and ordinary verification, not every topic.
A configuration fallback needs both failure handling and data absence semantics.

## Test strategy

When reviewing a system and its tests, adding or materially changing tests, or resolving an uncertain test strategy or oracle, consult [Testing with evidence](../references/testing.md).
For review-only work, begin with its [review obligations](../references/testing.md#review-a-system-and-its-tests); do not turn the review into test authoring or a completion audit.
When creating or modifying a test, run it and iterate until it passes.
