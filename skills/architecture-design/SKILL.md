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
- Selected design entering implementation: use `boundary-declaration`, then `implementation-plan` when requested
- Proposed framework or reusable layer: use `second-user`
- Current patch: use the repository's current-change review process

This skill may invoke those skills;
it does not duplicate their procedures.

## Inputs

Establish the target subsystem, current problem, constraints, non-goals, compatibility posture, and requested artifact: analysis, design document, issues, or some combination.
Stop and route elsewhere if the subsystem is unselected or the real task is comparing competing architectures.

## Procedure

### 1. Map the current subsystem

Inspect its specification, implementation, same-path tests, callers, API inventories, generated contracts, and open or closed issues.
Use history as evidence when useful, but do not equate churn with pain.

Classify responsibilities by reason to change: parsing, normalization, validation, domain policy, lifecycle, effects, projection, compatibility, and orchestration.
Record data shapes, effect owners, dynamic state, and dependency direction before naming destination modules or components.

### 2. Find credible seams

A useful seam has a one-sentence job, a named boundary value, mostly one-way dependencies, independent callers or tests, and a concrete payoff such as removing a cycle, dependency, broad fixture, or recurring coupled edit.
Consumer behavior should remain stable during extraction.

Reject seams supported only by line count, aesthetics, symmetrical names, or hypothetical reuse.
Invoke `second-user` before proposing generalized machinery without two concrete consumers.

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

Count affected callers, tests, dynamically scoped state, generated artifacts, inventories, and compatibility surfaces.
Then name what becomes cheaper or safer: fewer co-edits, removed dependencies, lower-boundary tests, mechanically rejected invalid states, or a stable phase result.
Function movement alone is not a benefit.

Classify the result:

- `RECOMMEND`: concrete gain exceeds bounded migration cost
- `CONDITIONAL`: one named measurement, consumer, or prerequisite is still required
- `REJECT`: abstraction or churn exceeds demonstrated benefit

Do not turn every responsibility into a namespace.
A partial extraction is complete when it removes the motivating pain.

### 5. Slice the work

Order small, behavior-preserving slices with one owner, focused verification, stable intermediate states, and explicit stopping points.
Keep extraction separate from behavior changes, schema redesign, message rewrites, new frameworks, and public API expansion.
Route selected work through `boundary-declaration` before implementation and `implementation-plan` when a repository plan is requested.

### 6. Write and challenge the design

Follow the repository's design-document convention. If none exists and a durable design document is requested, use Typst when available.
Include only what applies: status and scope, evidence, selected and rejected seams, ownership, data/dependency flow, compatibility, slices, tests, risks, acceptance evidence, and open questions.
Compile the document before reporting completion.

Challenge the result:

- Does it improve ownership or only shorten a file?
- Does a facade preserve the old coupling?
- Did a leaf acquire orchestration, filesystem, or domain-policy dependencies?
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
