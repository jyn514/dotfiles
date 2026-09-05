---
name: pain-axis
description: Analyze repository history, issues, tests, and coupled changes for recurring architectural pain and mechanically enforceable invariants. Use before redesigning a legacy or failure-prone subsystem when historical evidence can inform the design space without dictating a solution.
---

# pain-axis

## Purpose

Use repository history to identify where the current architecture has actually caused maintenance pain, bugs, reversals, or repeated coupled edits.

## Inputs

- repository
- target subsystem or design question
- available Git history, issues, tests, and bug-fix context

## Procedure

1. Inspect bug-fix commits, reverts, repeated refactors, and files that frequently change together.
2. Look for recurring categories of failure: ownership confusion, invalid states, duplicated sources of truth, lifecycle mistakes, synchronization bugs, leaky abstractions, etc.
3. Distinguish high-frequency cosmetic co-change from architectural coupling.
4. Identify invariants that, if mechanically enforced, would have prevented historical failures.
5. Produce evidence, not a design recommendation.

## Output

- `pain_axes`: recurring architectural failure dimensions
- `historical_examples`: concrete commits/issues/files when available
- `cochange_signals`: suspiciously coupled areas
- `candidate_invariants`: properties that might be enforceable mechanically
- `uncertainties`: where history is too sparse or ambiguous

## Constraints

- Do not assume the historical architecture is optimal merely because it exists.
- Do not treat raw co-change frequency as causation.
- Novel requirements may not have historical evidence; say when the prior is weak.
