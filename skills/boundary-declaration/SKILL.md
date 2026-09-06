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

1. Identify the sole owner and writers of each mutable state.
2. Identify where side effects are permitted and which effects form one publication.
3. Identify authoritative raw representations and every derived, normalized, serialized, or displayed projection. Validate before a projection can discard distinctions needed by later checks.
4. Identify object identity independently of names and ambient state: filesystem identity, selected revision, provider, platform, and configuration scope where applicable.
5. Identify lifecycle states, invalid transitions, deadlines, cancellation owners, and whether failure can leave a committed or outcome-unknown effect.
6. For destructive or multi-step work, identify recovery authority and durable state that remain available if primary paths move or disappear.
7. Identify APIs across which ownership, identity, representation, or lifecycle assumptions must not leak.
8. Keep the declaration short enough to review before coding.

## Output

A compact declaration containing:

- ownership and effect boundaries
- publication boundary
- authoritative and derived representations
- object and ambient-state identities
- lifecycle, timeout, and invariant statements
- recovery authority for destructive work
- explicit non-goals

## Constraints

- This is not an implementation plan.
- Prefer falsifiable statements such as “X is the sole writer of Y” over vague principles.
- Distinguish containment from ownership, successful mutation from successful presentation, and failure from unknown outcome.
- If a boundary cannot yet be stated clearly, stop and surface the ambiguity before implementation expands around it.
