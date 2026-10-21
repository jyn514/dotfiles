---
name: implementation-plan
description: Create or review a concrete, repository-specific implementation plan for a selected change. Use for requests such as “create a plan,” “show me a plan; do not implement,” “what are the next steps?” after investigation, saving a plan, identifying affected files and tests, or breaking work into logical commits. Do not use to choose among materially different architectures, directly create the selected design's implementation artifact, or execute an existing plan.
---

# Implementation Plan

Turn a selected design into a repository-specific plan another engineer can implement and review without reconstructing hidden decisions.

For a staged new-tool workflow only, require a ready implementation specification before planning. It is the design authority; the plan remains optional and must not alter requirements or design or become another human gate.

## Procedure

1. **Observe first.** Inspect entry points, data flow, side effects, tests, docs, dependencies, and repository guidance.
   Separate observations from assumptions.
   Before treating preservation as required, cite its source and trace affected consumers, including whether they change and deploy together.
   Apply [Compatibility](../references/change-with-evidence.md#compatibility).
   Mark unknown preservation requirements as unresolved rather than conservative defaults.
2. **Confirm the design is selected.** If viable alternatives change public APIs, ownership, persistence, concurrency, or migration, use design deliberation instead.
3. **Record decisions.** Classify material choices as `decided`, `conservative default`, or `unresolved`; mark unresolved choices as blocking or non-blocking.
4. **Declare boundaries.** Name mutable-state ownership, permitted side effects, authoritative and derived representations, lifecycle rules, compatibility requirements, and non-goals.
5. **Trace and validate the lifecycle.** Cover setup, normal operation, errors, cancellation, cleanup, concurrency, and shutdown, including paths outside the apparent core function. Check proposed interfaces against every known caller, producer, transition, and bypass path; state capabilities and invariants instead of inventing unjustified method signatures.
6. **Choose the smallest coherent change.** Separate required outcomes from chosen mechanisms and reuse sufficient existing facilities.
   For each added interface, option, field, transition, or helper, identify the consumer or concrete failure that needs it.
   Remove adjacent extensions that the selected change does not require, such as widening existing operations to match a new operation.
   Require a concrete second consumer or hard constraint before adding general machinery.
   Specify high-risk behavior; leave low-risk mechanics to implementation.
7. **Specify verification.** Tie each test to a consumer-visible requirement or realistic regression.
   For a small finite behavior space, use an exhaustive table or transition matrix with focused regression cases.
   Require generated properties or action sequences only when they cover an identified invariant or combinations those cases cannot adequately cover.
   State the added coverage; do not introduce a generator or reference model merely because the system has state transitions.
   When justified, use [property-based-testing](../property-based-testing/SKILL.md) to choose properties and generators within scope.
   Use integration, pseudo-terminal, migration, or real-service tests only when the boundary requires them.
8. **Order independently valid commits.** For each commit, give an imperative subject, useful result, principal files or subsystem, and verification that passes at that point. Land tests with their behavior. Preparatory refactors must be independently justified and behavior-preserving; do not introduce architecture merely to replace it in the next commit.
9. **Review against the repository.** Check bypass paths, global state, unbounded resources, cancellation ownership, error precedence, compatibility, docs, generated files, dependencies, platform behavior, and whether detail exceeds evidence.
   In new and revised plans, group related failure cases under one governing invariant.
   Keep individual reproductions and expected outcomes in one acceptance section instead of repeating normative rules.
   Do not add a mechanism per finding unless a distinct contract requires it.
10. **Simplify every new or revised plan before presenting or saving it.** Check both the proposed work and the document, not just wording.
    Give each rule one canonical home; do not restate it across decisions, invariants, lifecycle, steps, and acceptance criteria.
    Let steps name the affected work and acceptance cases demonstrate the rule rather than define it again.
    Remove investigation chronology, unsupported safeguards, and speculative extensions from implementation instructions.
    Retain decision-changing rationale, required compatibility, and checks that protect observable behavior.
    Do not simplify by changing the selected design or weakening required verification.
    Perform this pass as part of drafting; it does not require another approval or delegated review stage.

## Output

Default to a compact plan containing:

- **Contract:** objective, scope, behavior, and material decisions, with source paths where they explain a constraint.
- **Implementation steps and logical commits:** affected files, useful intermediate results, and checks that pass at each step.
- **Verification:** concrete acceptance cases and required repository checks.
- **Material unresolved questions:** only those that can change implementation, marked blocking or non-blocking; omit if none remain.

Put storage, lifecycle, and compatibility details beside the contract or step they constrain.
Add separate sections only when they make the implementation easier to follow; the above is not a mandatory heading template.
Save plans in the requested format and location; otherwise follow repository conventions, defaulting to concise Markdown.
Separate docs from behavior only when repository practice or generated output warrants it.

## Constraints

- Do not edit implementation files unless implementation was also requested.
- A request to create the selected design's artifact or execute agreed work is implementation, not a request for another plan.
- Give effort ranges only with evidence and dominant assumptions.
- Make cancellation, cleanup, output ownership, compatibility, and error precedence explicit.
- Review existing facilities before proposing a dependency.
- Prefer a short complete plan over possibilities or premature implementation detail.
