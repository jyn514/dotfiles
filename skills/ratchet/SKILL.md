---
name: ratchet
description: Turn verified invariants and known failure modes into monotonic mechanical checks such as types, lint rules, tests, assertions, or benchmarks. Use during implementation or autonomous work to prevent recurrence of demonstrated bad states.
---

# ratchet

## Purpose

Convert discovered invariants and known failure modes into mechanical checks so later autonomous work cannot silently regress them.

## Inputs

- boundary declaration
- current tests/checks
- newly discovered bugs or invariants
- implementation environment

## Procedure

1. For each important invariant, ask whether it can be checked mechanically.
2. Prefer the strongest cheap mechanism available:
   - type/system invariant
   - compiler/linter rule
   - unit/property/regression test
   - static query/grep assertion
   - runtime assertion
   - benchmark threshold when performance is the invariant
3. Require a demonstrated failure before accepting a new check when practical: show that the check would fail on the bad state and pass on the intended state.
4. Add checks monotonically during a long run; do not remove or weaken an existing check merely to make progress.
5. If an invariant has no reliable oracle, record it explicitly rather than pretending the ratchet covers it.

## Output

- invariant
- proposed check
- evidence the check detects the bad state
- command used to run it
- limitations / false-negative risk

## Constraints

- Do not equate “tests pass” with “design is correct.”
- Checks must target a stated invariant or observed failure mode, not arbitrary coverage growth.
- Weakening a ratchet requires explicit human approval or stronger replacement evidence.
