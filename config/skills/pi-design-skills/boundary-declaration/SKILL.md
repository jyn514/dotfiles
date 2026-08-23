---
name: boundary-declaration
description: Declare ownership, side-effect, representation, lifecycle, and API boundaries before implementation. Use after selecting a design or when unclear boundaries could permit invalid states, duplicated authority, or leaking assumptions.
---

# boundary-declaration

## Purpose

Before implementation, state the chosen design's important ownership, effect, and representation boundaries in a form that can constrain later work.

## Inputs

- selected design
- relevant repository context

## Procedure

1. Identify who owns mutable state.
2. Identify where side effects are permitted.
3. Identify authoritative versus derived representations.
4. Identify lifecycle boundaries and invalid states.
5. Identify APIs across which assumptions must not leak.
6. Keep the declaration short enough to review before coding.

## Output

A compact declaration containing:

- ownership boundaries
- effect boundaries
- authoritative state
- derived state
- lifecycle/invariant statements
- explicit non-goals

## Constraints

- This is not an implementation plan.
- Prefer falsifiable statements such as “X is the sole writer of Y” over vague principles.
- If a boundary cannot yet be stated clearly, stop and surface the ambiguity before implementation expands around it.
