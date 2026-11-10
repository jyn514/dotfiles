---
name: implementation-plan
description: Work out or review how to implement a given ticket in the current repository. Use when explicitly asked to plan a ticket's implementation or review its implementation plan. Identify the existing code path, required changes, verification, and material unresolved choices. A concrete requested change can supply the task when no ticket exists; do not require ticket creation. Not for decomposing a broad goal, selecting product scope or architecture, ordinary ticket refinement, executing agreed work, or adding a mandatory planning stage to an already-actionable ticket.
---

# Implementation plan

Supply the execution detail another engineer needs to implement a ticket without reconstructing hidden decisions.
Use the repository's code and test facilities; preserve the ticket's outcome, acceptance conditions, and settled design.
A concrete requested change can stand in for a ticket; do not create tracker work just to plan it.
An already-actionable ticket needs no separate plan.
Creating the selected design's artifact or executing agreed work is implementation, not another planning stage.
Planning alone does not authorize implementation edits.

For a plan review, check the proposed work against the repository using the sections below.
Report missing detail and unsupported work; do not rewrite the plan unless asked.

For a staged new-tool workflow, require a ready implementation specification as the design authority.
The plan remains optional; it must not change the requirements or design or require another human approval.

## Establish the task

Read the acceptance conditions, linked design, existing implementation detail, and repository guidance.
Reuse settled decisions, contracts, and non-goals rather than reconstructing the wider goal's decomposition.
Identify the required observable results and known preservation requirements before choosing machinery.

For material choices, distinguish what the plan inherits from what it proposes:

- **Decided:** cite the requirement, selected design, or existing contract that settles the choice.
- **Conservative default:** identify a proposed choice within settled constraints, such as placing a regression in the existing test suite.
- **Unresolved:** state what remains unknown and which work depends on the answer.
  Mark it blocking when that implementation must wait for the answer, otherwise non-blocking.

If inspection reveals unsettled architecture, a missing prerequisite, or a necessary scope change, report it and stop dependent planning.
Continue independent planning within the settled scope; do not select a replacement architecture or revise the issue graph.

## Trace a complete path

Sketch how the caller reaches the required result through existing facilities and the selected design.
Include known error, lifecycle, and compatibility requirements, not just the successful request.
Use this candidate to direct inspection, not as an extra document or approval stage.
Investigate unknowns that could change the path or its verification; do not fill them with speculative components or interfaces.
Keep observations separate from assumptions, and stop investigating an unknown when the evidence settles it.

Follow the entry points, data flow, side effects, and deployed consumers, including affected paths that bypass the main entry point.
Inspect relevant tests, docs, and dependencies to establish which facilities suffice.
Reference existing ownership, effects, representations, lifecycle, and compatibility contracts.
Use the [boundary-contract questions](../architecture-design/references/boundary-contracts.md) for decision-changing gaps.

Before treating preservation as required, cite its source and check whether affected consumers change and deploy together.
Apply [Compatibility](../references/change-with-evidence.md#compatibility); unknown preservation requirements remain unresolved, not conservative defaults.

Trace affected setup, error, cancellation, cleanup, concurrency, shutdown, and consumer-specific transitions without reopening unchanged behavior.
For example, suppose an export must not publish a file after cancellation.
A worker can finish computing before cancellation but publish afterward; checking cancellation only when the command starts misses that case.
Find who owns publication at that point and what the change must do to uphold the cancellation contract.
The plan needs that answer, not an inventory of every worker method.

## Keep the proposed work small

First try to handle findings through the current path and its existing owners.
Before adding a control, component, interface, fixture, or phase, identify a required case the smaller candidate cannot handle.
A useful purpose alone does not justify a separate mechanism.
If another complete approach is smaller, replace the candidate rather than adding workarounds to preserve it.
Simplify the work, not the required behavior, selected design, or verification.

When controls always vary together for current consumers, represent them as one concept.
Preserve independent choices a current caller needs: a narrowly scoped option does not require a second consumer.
Reusable infrastructure or additional scopes do require a concrete second consumer or governing constraint.
Do not widen adjacent operations merely to match a new one.
Keep optional work out of the required path, including later phases.

Check proposed interfaces against affected callers, producers, and transitions.
Specify high-risk behavior and invariants; leave low-risk mechanics to implementation.
Make affected cancellation, cleanup, output ownership, compatibility, and error precedence explicit, referencing settled contracts for unchanged behavior.

## Choose verification

Name the consumer-visible claim or realistic regression each check must establish.
In the export example, observe whether the destination changes when cancellation arrives between computation and publication.
A check that only observes a cancellation flag cannot establish that the file stays unpublished.

Compare existing test facilities before proposing a maintained runner or fixture; a required real-system check does not itself justify new infrastructure.
Review existing facilities before proposing a dependency.
For a small finite behavior space, use an exhaustive table or transition matrix with focused regression cases.
Require generated properties or action sequences only for identified invariants or combinations those cases cannot adequately cover.
When justified, use [property-based-testing](../property-based-testing/SKILL.md) to choose properties and generators.
Use integration, pseudo-terminal, migration, or real-service tests when the observable boundary requires them.

## Order the edits and write the plan

Identify affected files or subsystems and useful intermediate results.
Include commit boundaries only when requested or when they materially help implementation or review.
For proposed commits, use `commit-quality` for boundaries and imperative subjects, and identify verification that passes at each commit.
Land tests with their behavior; keep preparatory refactors independently justified and behavior-preserving.
Do not add architecture, fixtures, or deliverables just to make a commit look self-contained.
Separate docs from behavior only when repository practice or generated output warrants it.

Default to a compact plan containing:

- **Task and constraints:** reference the outcome, acceptance conditions, and settled design; identify material implementation decisions.
- **Implementation steps:** affected files, useful intermediate results, and checks that pass at each step.
- **Verification:** concrete acceptance cases and required repository checks.
- **Unresolved questions:** choices that can change implementation, marked blocking or non-blocking; omit if none remain.

These are contents, not mandatory headings.
Put storage, lifecycle, and compatibility details beside the contract or step they constrain.
Give each rule one home; group related failures under their governing invariant and keep reproductions and expected outcomes in one acceptance section.
Steps should reference those checks, not restate their rules.
Retain decision-changing rationale; omit investigation chronology, speculative extensions, and unsupported safeguards.
Give effort ranges only with evidence and dominant assumptions.

Use the existing ticket as the canonical home when updates are authorized.
For a read-only or proposal-only request, return the proposed detail in the requested format and location without editing the ticket.
Create a separate artifact only when requested or needed by a concrete reader; link it from the ticket when authorized rather than maintaining parallel plans.
Without a ticket, follow repository conventions and do not create tracker work or a maintained artifact unless authorized.

## Check completeness

Compare the finished plan with the governing requirements and required verification.
Within affected paths, check:

- **Alternate routes and shared state:** can a bypass path or another user of global state escape the proposed behavior?
- **Resources and failure:** what bounds resource use, who owns cancellation and cleanup, and which error wins when more than one operation fails?
- **Consumers and delivery:** have you preserved required compatibility and platform behavior, and covered affected dependencies, docs, and generated files?

Does every addition still have a required case the smaller path cannot handle?
Does the detail stay within the evidence?
