---
name: architecture-design
description: "Design, assess, or choose a bounded software architecture: subsystem ownership, dependency direction, data/effect and lifecycle contracts, API shape, maintainability gain, and churn. Use for architecture documents, extraction candidates, unresolved architecture choices, or whether a split/refactor is worth doing. Trace the existing path first; optional references support genuine alternatives and independent deliberation. Reuse settled contracts. Not for broad project discovery, implementation planning, routine local edits with settled boundaries, or current-change review."
---

# Architecture Design

Design or assess one selected subsystem and decide whether changing it is worth the churn.
Produce a falsifiable boundary proposal, not a diagram justified by file size.
Trace one real caller → handler → effect path before proposing a replacement; for greenfield work, trace the closest existing primitive or integration caller.
Recommend the smallest sufficient change; when evidence is missing, propose a decision-changing check rather than a larger architecture.

## Read First

Discover and follow the target repository's guidance for architecture, ownership, data and effects, testing, and design documents. Read the nearest instructions for every subsystem in scope; do not assume conventional paths exist.

## Routing

- No selected subsystem: use `opportunity-scan`
- Recurring historical pain may matter: use `pain-axis`
- Tracing the existing path leaves a genuine architectural choice: consult [alternatives](references/alternatives.md).
- That choice requires independent elaboration and critique: use [deliberation](references/deliberation.md), not a default multi-agent process.
- Selected design needs a requested repository plan: use `implementation-plan`; carry the existing boundary contract forward.
- A proposed mechanism's necessity or variability is unclear: consult [complexity justification](../references/complexity-justification.md).
- Current patch: use the repository's current-change review process

Read only the reference or skill needed for the concrete unresolved question.
Do not load a chain of design procedures by default.

## Inputs

For a staged new-tool workflow, consume approved requirements and repository integration constraints as the scope evidence. Do not invent product scope or observable behavior; record only design decisions needed to satisfy that evidence. The resulting design contributes to the implementation specification and does not replace it. For a greenfield tool, do not require a current implementation or extraction history.

Establish the target subsystem, current problem, constraints, non-goals, compatibility posture, and requested artifact: analysis, design document, issues, or some combination.
Before designing interfaces or configuration, list every dimension required to vary and the policy that remains fixed. For each configurable dimension, name its explicit requirement and authoritative source; prefer stable references to existing authorities over restating their contents. Record deliberately fixed behavior in the output.
Stop and use opportunity-scan if no subsystem is selected.
When comparing architectures, use the same observed path and requirements for each candidate; do not fabricate alternatives to fill slots.

## Principles

Avoid unnecessary coupling.
Interfaces should expose the caller’s intent without requiring knowledge of the callee’s implementation.
Keep policy separate from effects as declarative data, not runtime checks. Declarative policy may remain fixed and local: it implies no external assets, registry, extension interface, or runtime configurability unless an explicit requirement demands variation.
Before introducing coordination between systems, ask whether one owner can make the decision and pass a completed result across the boundary.
Do not mix concerns between two different systems just because it simplifies the current implementation.

Before designing an application-side workaround for a tool limitation, inspect the tool's data model and extension points.
Establish whether changing the tool is permitted; a missing CLI option does not prove a missing model capability or an immutable dependency.
When existing interfaces are insufficient, compare a narrow native extension with a separate adapter.
Include maintenance, packaging, and upstream review or release delays in that comparison.

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

Complete this inspection before choosing or proposing an API, protocol, or subsystem split.

For an existing subsystem, start with the affected specification, implementation, same-path tests, and callers.
Consult API inventories, generated contracts, issues, and prepared work only when they can change the proposed boundary or prevent duplicate work.
For a staged greenfield new tool, inspect adjacent systems, existing primitives, runtime and deployment boundaries, and integration callers instead; do not require a current implementation or extraction history.
For adapters and proxies, inspect the native interface and any existing analogous adapter before deciding what to forward, restrict, or replace.
Search by exact proposed title and boundary before recording work; do not duplicate a finding merely because publication is pending.
Use history as evidence when useful, but do not equate churn with pain. Check whether the proposed arrangement existed before and why it changed; a prior separation may encode a correctness constraint.

Classify responsibilities by reason to change: parsing, normalization, validation, domain policy, lifecycle, effects, projection, compatibility, and orchestration.
Record data shapes, effect owners, dynamic state, and dependency direction before naming destination modules or components.

#### Design risk applicability

Before choosing boundaries, check for shared state or external effects, asynchronous work, resource or performance constraints,
trust crossings, independent deployments or persisted formats, and diagnosis or recovery needs.
Read the corresponding [design-risk checks](references/design-risks.md#applicability) for each applicable case.
Establish a concrete constraint or failure case before adding a mechanism; reuse settled contracts rather than reopening them.

### 2. Find credible seams

A useful seam has a one-sentence job, a named boundary value, mostly one-way dependencies, and independent callers or tests. For existing subsystems, seek a concrete payoff such as removing a cycle, dependency, broad fixture, or recurring coupled edit. For a staged greenfield new tool, justify responsibility, data, and effect seams by approved requirements and lifecycle ownership instead of extraction payoff.
Consumer behavior should remain stable during extraction.

Reject seams supported only by line count, aesthetics, symmetrical names, or hypothetical reuse.
Prefer deleting obsolete, lossy, or misleading APIs over extracting new owners around them; a facade that drops diagnostics, provenance, lifecycle state, or other operation results is not a harmless convenience.
Before detailed design, run the cheapest check that could disprove the seam: a dependency trace, classpath-load check, differential fixture, effect inventory, or focused caller/test probe.
For proposed reusable machinery, plugin hooks, or configurable dimensions, establish the current consumer or hard constraint first.
Consult [complexity justification](../references/complexity-justification.md) only if necessity or required variability remains unclear.

### 3. Define the target boundary

Maintain one evolving boundary contract, reusing existing code and settled design decisions.
State moving and remaining responsibilities, allowed dependencies and forbidden reverse edges, API treatment, and any facade's justification and removal condition.
For unresolved or changed ownership, representations, effects, identity, lifecycle, or recovery guarantees, answer only the applicable [boundary-contract questions](references/boundary-contracts.md).
Do not repeat this analysis as a separate declaration phase at specification, planning, delegation, or implementation handoff.
For staged new tools, keep the contract in the implementation specification without changing approved scope or behavior.

Reapply the design-risk scan only to risks introduced or changed by the proposed boundary.
Keep extraction separate from behavior changes, schema redesign, message rewrites, new frameworks, and public API expansion unless those changes are explicitly in scope.

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

### 5. Challenge and present the design

When a durable document is requested, follow the repository's convention; otherwise use Typst when available.
Include only applicable scope, evidence, selected and rejected seams, ownership, data/dependency flow, compatibility, tests, risks, acceptance evidence, and open questions.
Compile the document when its format requires it.
Architecture assessment alone does not require a new document, implementation tasks, or a commit plan.

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
