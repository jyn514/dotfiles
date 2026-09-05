---
name: council-review
description: Judge a fixed set of software-design candidates against shared criteria and evidence, returning a selection, equivalence, or abstention. Use after independent plans and cross-critique are complete; not for inventing or revising candidates.
---

# council-review

## Purpose

Evaluate a fixed candidate set in fresh contexts and decide whether available evidence justifies selecting one.

## Inputs

- original task and constraints
- fixed candidates {A, B, C, D?}
- `cross-critic` report
- optional factual evidence

## Procedure

1. Review every candidate adversarially against the same criteria.
2. Do not invent candidate E or rewrite the design space.
3. Treat unsupported assumptions as liabilities.
4. Do not reward verbosity, familiarity, confidence, or synthesis merely for including more ideas.
5. If multiple candidates remain materially indistinguishable, return `EQUIVALENT`.
6. If missing evidence is decision-changing, return `ABSTAIN` and name the cheapest useful next inquiry.
7. Otherwise return `SELECT <candidate>`.

## Output

Exactly one:

- `SELECT`: candidate, reasons, important rejected alternatives, remaining uncertainty
- `EQUIVALENT`: candidate set, reasons, optional deterministic tiebreak criterion
- `ABSTAIN`: reasons, missing evidence, cheapest useful next inquiry

## Constraints

- Candidate IDs must come from the supplied fixed set.
- Selecting D is ordinary `SELECT D`; fusion is not a separate decision kind.
- No new design may be synthesized during judging.
