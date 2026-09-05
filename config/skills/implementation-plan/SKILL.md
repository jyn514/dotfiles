---
name: implementation-plan
description: Create or review a concrete, repository-specific implementation plan for a selected change. Use when asked to plan coding work, save a plan, break work into logical commits, identify affected files and tests, or make an existing plan implementation-ready. Do not use to choose among materially different architectures; use design deliberation first when the design itself remains uncertain.
---

# Implementation Plan

Turn a selected design into a plan another engineer can implement, review, and land without reconstructing hidden decisions.

## Procedure

1. **Observe first.** Inspect entry points, data flow, side effects, tests, docs, dependencies, and repository guidance. Separate observations from assumptions.
2. **Confirm the design is selected.** If viable alternatives change public APIs, ownership, persistence, concurrency, or migration, use design deliberation instead.
3. **Declare boundaries.** Name mutable-state ownership, permitted side effects, authoritative and derived representations, lifecycle rules, compatibility requirements, and non-goals.
4. **Trace the full lifecycle.** Cover setup, normal operation, errors, cancellation, cleanup, concurrency, and shutdown, including paths outside the apparent core function.
5. **Choose the smallest coherent change.** Reuse existing seams that satisfy the design. Require a concrete second consumer or hard constraint before introducing general machinery.
6. **Specify verification.** Tie each test to a consumer-visible requirement or failure mode and ensure it fails under a realistic regression. Use integration, pseudo-terminal, migration, or real-service tests only when the boundary requires them.
7. **Order independently valid commits.** Give each an imperative subject, independently useful result, principal files or subsystem, and verification that passes at that point. Land tests with the behavior they protect. Do not introduce temporary architecture merely to replace it in the next commit; preparatory refactors must be independently justified and behavior-preserving.
8. **Review against the repository.** Check bypass paths, global state, unbounded resources, cancellation ownership, error precedence, compatibility, docs, generated files, dependencies, and platform behavior.

## Output

Include only sections the plan needs:

- `Objective`
- `Current behavior` with file paths
- `Scope` and `Non-goals`
- `Boundaries and invariants`
- `Design`
- `Execution and failure lifecycle`
- `Implementation steps` with affected files
- `Verification`
- `Logical commits`
- `Risks and unresolved questions`

Save plans in the requested format and location. Otherwise follow repository conventions, defaulting to concise Markdown. Separate docs from their behavior only when repository practice or generated output warrants it.

## Constraints

- Do not edit implementation files unless implementation was also requested.
- Give effort ranges only with evidence and dominant assumptions.
- Make cancellation, cleanup, output ownership, compatibility, and error precedence explicit.
- Review existing facilities before proposing a new dependency.
- Prefer a short complete plan over an inventory of possibilities.
