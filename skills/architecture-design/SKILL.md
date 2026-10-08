---
name: architecture-design
description: "Design or assess a bounded software architecture: subsystem decomposition, module ownership, dependency direction, data/effect boundaries, facade/API shape, maintainability gain, and churn. Use for architecture documents, extraction candidates, how a subsystem should be factored, or whether a split/refactor is worth doing. Not for broad opportunity discovery, choosing among competing architectures, implementation planning, or current-change review."
---

# Architecture Design

Design one selected subsystem and decide whether implementation is worth the churn.
Produce a falsifiable boundary proposal, not a diagram justified by file size.

## Read First

Discover and follow the target repository's guidance for architecture, ownership, data and effects, testing, and design documents. Read the nearest instructions for every subsystem in scope; do not assume conventional paths exist.

## Routing

- No selected subsystem: use `opportunity-scan`
- Recurring historical pain may matter: use `pain-axis`
- Several materially different architectures: use `design-deliberation`
- Selected design entering implementation: use `boundary-declaration` for unresolved or changed boundaries; reuse an existing declaration otherwise. Use `implementation-plan` when requested.
- Proposed framework, reusable layer, plugin hook, or configurable dimension: use `second-user`
- Current patch: use the repository's current-change review process

This skill may invoke those skills;
it does not duplicate their procedures.

## Inputs

For a staged new-tool workflow, consume approved requirements and repository integration constraints as the scope evidence. Do not invent product scope or observable behavior; record only design decisions needed to satisfy that evidence. The resulting design contributes to the implementation specification and does not replace it. For a greenfield tool, do not require a current implementation or extraction history.

Establish the target subsystem, current problem, constraints, non-goals, compatibility posture, and requested artifact: analysis, design document, issues, or some combination.
Before designing interfaces or configuration, list every dimension required to vary and the policy that remains fixed. For each configurable dimension, name its explicit requirement and authoritative source; prefer stable references to existing authorities over restating their contents. Record deliberately fixed behavior in the output.
Stop and route elsewhere if the subsystem is unselected or the real task is comparing competing architectures.

## Principles

Avoid unnecessary coupling.
Interfaces should expose the caller’s intent without requiring knowledge of the callee’s implementation.
Keep policy separate from effects as declarative data, not runtime checks. Declarative policy may remain fixed and local: it implies no external assets, registry, extension interface, or runtime configurability unless an explicit requirement demands variation.
Before introducing coordination between systems, ask whether one owner can make the decision and pass a completed result across the boundary.
Do not mix concerns between two different systems just because it simplifies the current implementation.

Prefer simplicity over exhaustiveness.
Tools should be reliable, but complexity itself can cause reliability issues.
Favor designs that "passively" do the right thing rather than needing ongoing interventions.
Before adding coordination, retries, monitoring, or lifecycle state, test whether changing ownership or batching operations removes the need for that mechanism.
Before extending a tool to handle edge cases, ask if you can narrow the requirements instead.

Minimize features: add no feature or configurable dimension without an explicit requirement. Keep unspecified and adjacent policy fixed; do what was asked, no more.

Require explicit input when omission could select the wrong identity, target, scope, or high-consequence action.
Otherwise prefer safe defaults rather than forcing the runtime user to make every decision.

## Procedure

### 1. Map the current subsystem

For an existing subsystem, inspect its specification, implementation, same-path tests, callers, API inventories, generated contracts, open or closed issues, and prepared issue drafts or campaign ledgers. For a staged greenfield new tool, inspect adjacent systems, existing primitives, runtime and deployment boundaries, and integration callers instead; do not require a current implementation or extraction history.
Search by exact proposed title and boundary before recording work; do not duplicate a finding merely because publication is pending.
Use history as evidence when useful, but do not equate churn with pain. Check whether the proposed arrangement existed before and why it changed; a prior separation may encode a correctness constraint.

Classify responsibilities by reason to change: parsing, normalization, validation, domain policy, lifecycle, effects, projection, compatibility, and orchestration.
Record data shapes, effect owners, dynamic state, and dependency direction before naming destination modules or components.

### 2. Find credible seams

A useful seam has a one-sentence job, a named boundary value, mostly one-way dependencies, and independent callers or tests. For existing subsystems, seek a concrete payoff such as removing a cycle, dependency, broad fixture, or recurring coupled edit. For a staged greenfield new tool, justify responsibility, data, and effect seams by approved requirements and lifecycle ownership instead of extraction payoff.
Consumer behavior should remain stable during extraction.

Reject seams supported only by line count, aesthetics, symmetrical names, or hypothetical reuse.
Prefer deleting obsolete, lossy, or misleading APIs over extracting new owners around them; a facade that drops diagnostics, provenance, lifecycle state, or other operation results is not a harmless convenience.
Before detailed design, run the cheapest check that could disprove the seam: a dependency trace, classpath-load check, differential fixture, effect inventory, or focused caller/test probe.
Invoke `second-user` before proposing reusable machinery, plugin hooks, or configurable dimensions.

### 3. Define the target boundary

For each viable seam, state:

- Moving and remaining responsibilities
- Owner module or subsystem
- Authoritative and derived representations
- Allowed dependencies and forbidden reverse edges
- Effect and mutable-state ownership
- Public, internal, and private API treatment, plus host/guest boundaries when the repository defines them
- Facade justification and removal condition

Prefer an existing domain owner for single-consumer policy.
Create a module or component for a coherent lifecycle or shared contract, not a bag of helpers.
A proposed cycle is a failed boundary unless an existing public adapter owns the composition.

### 4. Compare maintenance gain with churn

Count affected callers, tests, dynamically scoped state, generated artifacts, inventories, and compatibility surfaces. For a staged greenfield new tool, use implementation and integration cost in place of migration churn.
Then name what becomes cheaper or safer: fewer co-edits, removed dependencies, lower-boundary tests, mechanically rejected invalid states, or a stable phase result.
Function movement alone is not a benefit.

Classify the result:

- `RECOMMEND`: concrete gain exceeds bounded implementation and migration cost
- `CONDITIONAL`: one named measurement, consumer, or prerequisite is still required
- `REJECT`: abstraction complexity, implementation cost, or churn exceeds demonstrated benefit

Do not turn every responsibility into a namespace.
For an existing subsystem, a partial extraction is complete when it removes the motivating pain.
For a greenfield tool, stop once the architecture satisfies approved requirements without unsupported machinery.

### 5. Slice the work

Order small slices with one owner, focused verification, stable intermediate states, and explicit stopping points. For a staged new-tool workflow, trace each slice to approved requirements and record it in the implementation specification: preserve approved behavior where behavior exists; for a greenfield tool, establish requirements incrementally rather than preserve nonexistent behavior.
Keep extraction separate from behavior changes, schema redesign, message rewrites, new frameworks, and public API expansion.
Before implementation, use `boundary-declaration` for unresolved or changed boundaries; reuse an existing declaration otherwise. Use `implementation-plan` when a repository plan is requested.

### 6. Write and challenge the design

Follow the repository's design-document convention. If none exists and a durable design document is requested, use Typst when available.
Include only what applies: status and scope, evidence, selected and rejected seams, ownership, data/dependency flow, compatibility, slices, tests, risks, acceptance evidence, and open questions.
Compile the document before reporting completion.

Challenge the result:

- Does it improve ownership or only shorten a file?
- Does a facade preserve the old coupling?
- Did a leaf acquire orchestration, filesystem, or domain-policy dependencies?
- Does the proposed owner need callbacks for most lifecycle or policy decisions? If so, it is probably orchestration indirection rather than a coherent boundary.
- Did history previously combine these responsibilities, and why were they separated?
- Can a dependency or fixture demonstrably disappear through a classpath, caller, or focused-test check?
- Are tests merely renamed around private vars?
- Can the work stop after the first useful extraction?

When uncertainty remains, delegate one review asking which seam is weakest and whether its gain exceeds the churn.
Revise the recommendation rather than defending the original diagram.

## Issue Handoff

Open issues only when requested. Follow the repository's tracker guidance, search for duplicates, and separate independent extractions.
A ready issue names the current coupling, selected owner, dependency direction, preserved behavior, compatibility treatment, tests, mechanical boundary checks, exclusions, and stopping point. Keep conditional work out of an implementation-ready state until its named prerequisite exists.

## Output

Report the classification, selected boundary, decisive evidence, maintenance gain, churn and risks, rejected broader decomposition, and next action.
For a document task, report its path and validation instead of repeating it.
