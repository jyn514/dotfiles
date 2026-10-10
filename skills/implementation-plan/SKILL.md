---
name: implementation-plan
description: Create or review a concrete, repository-specific implementation plan for a selected change. Use for requests such as “create a plan,” “show me a plan; do not implement,” “what are the next steps?” after investigation, saving a plan, identifying affected files and tests, or breaking work into logical commits. Do not use to choose among materially different architectures, directly create the selected design's implementation artifact, or execute an existing plan.
---

# Implementation Plan

Turn a selected design into a repository-specific plan another engineer can implement and review without reconstructing hidden decisions.

For a staged new-tool workflow only, require a ready implementation specification before planning. It is the design authority; the plan remains optional and must not alter requirements or design or become another human gate.

## Procedure

1. **Observe first.** Inspect entry points, data flow, side effects, tests, docs, dependencies, and repository guidance. Separate observations from assumptions.
2. **Confirm the design is selected.** If viable alternatives change public APIs, ownership, persistence, concurrency, or migration, use design deliberation instead.
3. **Record decisions.** Classify material choices as `decided`, `conservative default`, or `unresolved`; mark unresolved choices as blocking or non-blocking.
4. **Declare boundaries.** Name mutable-state ownership, permitted side effects, authoritative and derived representations, lifecycle rules, compatibility requirements, and non-goals.
5. **Trace and validate the lifecycle.** Cover setup, normal operation, errors, cancellation, cleanup, concurrency, and shutdown, including paths outside the apparent core function. Check proposed interfaces against every known caller, producer, transition, and bypass path; state capabilities and invariants instead of inventing unjustified method signatures.
6. **Choose the smallest coherent change.** Reuse sufficient seams. Require a concrete second consumer or hard constraint before adding general machinery. Specify high-risk behavior; leave low-risk mechanics to implementation.
7. **Specify verification.** Tie each test to a consumer-visible requirement or realistic regression. Consider generated properties when input combinations or action sequences are better expressed by generators than hand-picked examples; use [property-based-testing](../property-based-testing/SKILL.md) to choose properties and generators within the plan's scope. Use integration, pseudo-terminal, migration, or real-service tests only when the boundary requires them.
8. **Order independently valid commits.** For each commit, give an imperative subject, useful result, principal files or subsystem, and verification that passes at that point. Land tests with their behavior. Preparatory refactors must be independently justified and behavior-preserving; do not introduce architecture merely to replace it in the next commit.
9. **Review against the repository.** Check bypass paths, global state, unbounded resources, cancellation ownership, error precedence, compatibility, docs, generated files, dependencies, platform behavior, and whether detail exceeds evidence.

## Output

Include only useful sections:

- `Objective`
- `Current behavior` with file paths
- `Scope` and `Non-goals`
- `Decision ledger`
- `Boundaries and invariants`
- `Design`
- `Execution and failure lifecycle`
- `Implementation steps` with affected files
- `Verification`
- `Logical commits`
- `Risks and unresolved questions`

Save plans in the requested format and location. Otherwise follow repository conventions, defaulting to concise Markdown. Separate docs from behavior only when repository practice or generated output warrants it.

## Constraints

- Do not edit implementation files unless implementation was also requested.
- A request to create the selected design's artifact or execute agreed work is implementation, not a request for another plan.
- Give effort ranges only with evidence and dominant assumptions.
- Make cancellation, cleanup, output ownership, compatibility, and error precedence explicit.
- Review existing facilities before proposing a dependency.
- Prefer a short complete plan over possibilities or premature implementation detail.
