---
name: implementation-plan
description: Create or review a concrete, repository-specific implementation plan for a selected change. Use for requests such as “create a plan,” “show me a plan; do not implement,” “what are the next steps?” after investigation, saving a plan, identifying affected files and tests, or breaking work into logical commits. Do not use to choose among materially different architectures, directly create the selected design's implementation artifact, or execute an existing plan.
---

# Implementation Plan

Turn a selected design into the smallest complete repository-specific plan another engineer can implement and review without reconstructing hidden decisions.
Keep a working caller-to-result path throughout planning; inspection, verification, and commit structure must earn any additions to it.
Simplicity concerns the proposed work, not just the length of the document, and must not change the selected design or weaken required behavior or verification.

For a staged new-tool workflow only, require a ready implementation specification before planning. It is the design authority; the plan remains optional and must not alter requirements or design or become another human gate.

## Procedure

1. **Establish the outcome and constraints.** Consume the selected design and repository guidance; reuse settled decisions, contracts, and non-goals.
   Identify required observable results and known preservation requirements before choosing implementation machinery.
   Classify material choices as `decided`, `conservative default`, or `unresolved`; mark unresolved choices as blocking or non-blocking.
   Return to architecture design only for a concrete unresolved choice or contradictory evidence that changes implementation.
2. **Start with a complete working path.** Sketch how the caller reaches the required result using existing facilities and the selected design.
   Carry forward known error, lifecycle, and compatibility requirements, not just the successful request.
   Name uncertainties that could change this candidate; do not fill them with speculative components or interfaces.
   This candidate is the basis for inspection and revision, not an extra document or approval stage.
3. **Inspect to resolve those uncertainties.** Trace the candidate's entry points, data flow, side effects, deployed consumers, and affected bypass paths.
   Inspect relevant tests, docs, and dependencies to establish which existing facilities suffice.
   Each further investigation must resolve an unknown that could change the candidate or its verification; stop when the evidence settles it.
   Separate observations from assumptions.
   Before treating preservation as required, cite its source and trace whether affected consumers change and deploy together.
   Apply [Compatibility](../references/change-with-evidence.md#compatibility); mark unknown preservation requirements as unresolved rather than conservative defaults.
   Reference existing ownership, effects, representations, lifecycle, and compatibility contracts.
   Fill only decision-changing gaps using the applicable [boundary-contract questions](../architecture-design/references/boundary-contracts.md).
   Trace relevant setup, error, cancellation, cleanup, concurrency, shutdown, and consumer-specific transitions without reopening unchanged lifecycle categories.
4. **Revise the candidate as evidence changes.** First try to accommodate each finding through the current path and its existing owners.
   Before adding a control, component, interface, test fixture, or phase, identify a required case the smaller candidate cannot handle.
   A useful purpose does not establish that a separate mechanism is necessary.
   If another complete approach is smaller, replace the candidate rather than retaining its machinery and adding workarounds.
   When controls always vary together for current consumers, represent them as one concept; preserve independent choices that a current caller actually needs.
   Require a concrete second consumer or governing constraint before adding reusable infrastructure or supporting additional scopes.
   A current caller's need to choose a value can justify a narrowly scoped option without a second consumer.
   Do not widen adjacent operations merely to match a new operation, or defer unnecessary work into a supposedly required later phase.
   Keep useful optional work out of the required path.
   Check interfaces against affected callers, producers, and transitions; specify high-risk behavior and invariants, leaving low-risk mechanics to implementation.
5. **Choose verification for that path.** Identify the consumer-visible claim or realistic regression each check must establish.
   Separate the required evidence from the machinery that produces it; compare existing test facilities before proposing a new maintained runner or fixture.
   A required real-system check does not by itself justify new test infrastructure; apply the same candidate comparison to its setup.
   For a small finite behavior space, use an exhaustive table or transition matrix with focused regression cases.
   Require generated properties or action sequences only for identified invariants or combinations those cases cannot adequately cover.
   When justified, use [property-based-testing](../property-based-testing/SKILL.md) to choose properties and generators within scope.
   Use integration, pseudo-terminal, migration, or real-service tests when the observable boundary requires them, not merely because those tools exist.
6. **Organize the required work into independently valid commits.** For each commit, give an imperative subject, useful result, principal files or subsystem, and verification that passes at that point.
   Land tests with their behavior; keep preparatory refactors independently justified and behavior-preserving.
   Commit boundaries organize the candidate; they do not justify extra architecture, fixtures, or deliverables to make a commit look self-contained.
7. **Write the compact plan.** Give each rule one canonical home beside the contract or work it constrains.
   Group related failures under their governing invariant; keep reproductions and expected outcomes in one acceptance section.
   Let steps identify the work and reference its checks rather than restating the rules.
   Retain decision-changing rationale; omit investigation chronology, speculative extensions, and unsupported safeguards.
8. **Check completeness against the repository.** Confirm that the current candidate still covers the governing requirements and required verification.
   Within affected paths, check bypass paths, global state, unbounded resources, cancellation ownership, error precedence, compatibility, docs, generated files, dependencies, and platform behavior.
   Check that every addition still has its distinguishing required case and that detail does not exceed evidence.

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
- Make affected cancellation, cleanup, output ownership, compatibility, and error precedence explicit; reference settled contracts for unchanged behavior.
- Review existing facilities before proposing a dependency.
- Prefer a short complete plan over possibilities or premature implementation detail.
