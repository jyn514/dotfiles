---
name: boundary-declaration
description: Declare ownership, side-effect, representation, lifecycle, and API boundaries. Use before delegating coupled implementation with unsettled shared contracts, and at the transition from a selected design to specification finalization, delegation, planning, or implementation when unclear boundaries could permit invalid states, duplicated authority, or leaking assumptions. Not for independent investigation or review unless it requires defining or changing a boundary. Reuse settled contracts; do not repeat a full boundary declaration during routine continuation unless a boundary changes.
---

# boundary-declaration

## Purpose

Before delegating coupled implementation, apply the delegation readiness check. Independent investigation or review does not require this skill unless it requires defining or changing a boundary.

At the first transition from a chosen design into specification finalization, delegation, planning, or implementation, state its important ownership, effect, and representation boundaries in a form that can constrain later work. Reuse that declaration during routine continuation; revise it only when a later decision changes a boundary.

For a staged new-tool workflow only, the declaration becomes or revises the boundary section of the implementation specification. Consume approved requirements and the architecture/design contribution without adding product scope or observable behavior.

## Inputs

- selected design
- relevant repository context

## Delegation readiness

1. Identify decisions one worker could make that would change another worker's inputs, outputs, or invariants. Separate file ownership does not establish independence.
2. For coupled implementation, state the shared representation, producer and consumer responsibilities, and failure behavior. Confirm both assignments use that contract. Reuse existing code or a short declaration; do not require a new document or exhaustive API specification.

Resolve shared contract choices before dependent implementation. If unresolved, delegate investigation or contract design instead of dependent implementation; continue independent work. Recheck affected assignments when the contract changes.

For example, workers preparing pronunciation analyses and executable rule data may own separate files but both depend on sound-unit identity and matching semantics. Settle those representations before implementing their producers and consumers in parallel. Collecting pronunciation provenance and specification examples can proceed independently while that contract remains unresolved.

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
