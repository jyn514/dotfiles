---
name: architecture-design
description: "Design, critique, or choose a bounded software architecture: subsystem ownership, dependency direction, data/effect and lifecycle contracts, API shape, maintainability gain, and churn. Use for architecture documents, extraction candidates, unresolved architecture choices, or whether a split/refactor is worth doing. Use also when authoring or revising a design/specification requires choosing an approach or introducing or changing guarantees, supported cases, or failure behavior, even when the request is framed as updating documentation. Trace the existing path first; optional references support genuine alternatives and independent deliberation. Reuse settled contracts. Not for broad project discovery, implementation planning, recording already-settled decisions, prose-only edits, routine local edits with settled boundaries, or current-change review."
---

# Architecture Design

Design or critique one selected subsystem and decide whether changing it is worth the churn.
Produce a falsifiable recommendation, not a diagram justified by file size.
Trace one real caller → handler → effect path before proposing a replacement; for greenfield work, trace the closest existing primitive or integration caller.
Recommend the smallest sufficient change; when evidence is missing, propose a decision-changing check rather than a larger architecture.

For critique, evaluate the supplied candidate using the relevant caller trace, principles, and boundary or risk checks.
Report supported findings, their consequences, and the smallest useful corrections.
A review request does not authorize edits or require developing a replacement architecture.
Use the design procedure below when developing or comparing approaches is requested.
For a concrete question about whether the proposed contract narrows governing requirements, consult `spec-review`'s [non-narrowing check](../spec-review/references/non-narrowing.md), not another full review.

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

### Outcome and authority

Establish the target subsystem, current problem, constraints, non-goals, compatibility posture, and requested artifact: analysis, design document, issues, or some combination.
Stop and use opportunity-scan if no subsystem is selected.

Check whether the design fulfills the practical purpose of the user's request, not just its literal wording or the terms of an earlier proposal.
What should the user or caller be able to know, decide, or do because of it?
Ground your interpretation of intent in the request; distinguish it from explicit requirements, and do not silently override those requirements.

Before selecting state, tracking, acknowledgment, or coordination mechanisms, state the minimum observable outcome.
For each added mechanism, name the user requirement or pre-existing constraint that the direct solution cannot meet without it.
Apply the shared [decision-authority rule](~/.agents/shared.md#before-selecting-a-substantial-approach) when classifying proposed guarantees.
Compare the smallest existing-primitive solution first; show the decisive requirement and trade-off in the recommendation, not a separate checklist.
Compare a simpler approach against the practical purpose before preserving obligations inferred by the proposal.
For worked comparisons of added guarantees, operation scope, and representations, see the [contrasting examples](references/simplicity-examples.md).

When comparing architectures, use the same observed path and requirements for each candidate; do not fabricate alternatives to fill slots.

### Configuration and storage

#### Configuration

Before designing interfaces or configuration, list every dimension required to vary and the policy that remains fixed.

- For each configurable dimension, name the explicit requirement and its authoritative source.
- Prefer stable references to existing authorities over restating them.
- Record deliberately fixed behavior in the output.

#### Persistence

Identify the current storage boundary before selecting a persistence mechanism.
Record which principal owns the data, where and in what form it persists, its lifetime, who can read it, and who can rotate or recover it.

Moving data between principals or media changes behavior and requires authority.
Changing persistence, protection, or lifetime does too; none is a routine implementation choice.

If the request does not settle a consequential storage-boundary change, ask before designing the dependent mechanism.
Continue independent analysis while that decision is unresolved.

Examples:

- Moving a credential from a password manager into a host file changes its storage boundary, even when consumers receive the same bytes.
- Replacing a database library does not change the boundary when owner, format, access policy, and lifetime remain fixed.
- Turning an in-memory cache into a disk cache changes the boundary because persistence and recovery behavior change.

## Principles

Use these principles for both design and critique; consulting them does not start the full design procedure.

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
Otherwise choose sensible defaults that best satisfy the requirements; unspecified details are delegated decisions.

## Procedure

### 1. Trace the existing path

Complete the applicable inspection before choosing or proposing an API, protocol, or subsystem split.
Start with one complete caller-to-result interaction using existing commands, identifiers, and defaults.
For an existing subsystem, trace the affected specification, implementation, same-path tests, and callers.
Identify the result the caller needs, then inspect how far that interaction already gets before treating a missing proposed interface as a missing capability.

Compare that route with the governing outcome, including required maintenance or lifecycle changes, before investigating proposal-specific machinery.
Check the ownership, authorization, compatibility, storage, and supported-interface constraints needed to establish whether the direct route suffices.
If it does, use step 2 to state the complete recommendation and stop; do not investigate resources or boundaries for an addition that is no longer needed.
Use the further inspection below only where it can resolve a remaining choice or establish a candidate's sufficiency.

#### Inventory existing runtime resources

Before proposing a new runtime resource or lifecycle owner, apply the shared [runtime-resource reuse check](../references/change-with-evidence.md#justify-new-mechanisms) to inventory existing owners and justify any new resource.

#### Trace the existing implementation

Consult API inventories, generated contracts, issues, and prepared work only when they can change the proposed boundary or prevent duplicate work.
For a staged greenfield new tool, inspect adjacent systems, existing primitives, runtime and deployment boundaries, and integration callers instead; do not require a current implementation or extraction history.
For adapters and proxies, inspect the native interface and any existing analogous adapter before deciding what to forward, restrict, or replace.
When a repeated operation constructs a client, runtime, or adapter, trace its constructors and factories through to external effects.
Identify repeated resource selection and admission checks, including configuration reads, process launches, and network requests.
Check whether an existing owner has already selected or admitted that resource before proposing another discovery path.

For a proposed resource binding, name its owner, lifetime, and replacement event, such as a new request, attachment, or configuration reload.
Include executable code as well as configuration; a fixed path does not bind the contents later loaded from it.
Check actual producer and consumer deployment lifetimes rather than assuming a shared checkout makes their updates atomic.
Separate resource selection from admission checks and observations of mutable state.
Reuse a selection only for its established lifetime; do not remove fresh checks merely because they share the discovery path.
Check which values must remain dynamic within that lifetime, including caller identity, credentials, and resource contents.
For cache designs involving ordered discovery, see the [unsuccessful-lookup example](references/caching-examples.md).
For proposed reuse, invalidation, or equality changes, read [Reuse and invalidation](references/design-risks.md#reuse-and-invalidation).

Search by exact proposed title and boundary before recording work; do not duplicate a finding merely because publication is pending.
Use history as evidence when useful, but do not equate churn with pain. Check whether the proposed arrangement existed before and why it changed; a prior separation may encode a correctness constraint.

### 2. Challenge the hardest part and decide whether design is needed

Compare the traced interaction with the proposed addition before elaborating the addition's interface or failure handling.
Before introducing another input, identifier, persistent record, or protocol step, show a concrete case where that interaction fails a governing requirement.
If the comparison is unclear, use the [existing-operation example](references/simplicity-examples.md#start-with-the-existing-operation) to distinguish a missing capability from a preferred new interface.
Distinguish required behavior from optional guarantees introduced by the proposal.
Name the hardest part of the proposed approach and the guarantee, distinction, or coordination that makes it hard.
Ask whether the hard part can be removed while keeping required behavior, timing, and coverage fixed.
If the simpler interaction meets the governing requirements, remove the extra mechanism instead of elaborating it.
Otherwise retain it or find another approach; do not weaken the requirement without approval.
Keep speculative hardening outside the recommended interface.
Make the decisive comparison visible in the recommendation, not just a claim that the chosen design is simpler.

If an existing primitive or local change meets the governing requirements, report it as a complete recommendation and stop before subsystem mapping or boundary design.
Show the traced path, decisive requirement comparison, required change, and verification limits.
The recommendation must respect governing ownership, authorization, compatibility, and storage constraints; reuse must rely on a supported interface available to the intended consumer.
If sufficiency is uncertain, use the cheapest decision-changing check rather than assuming a boundary design is needed.
Continue through steps 3–6 only when a genuine architectural choice remains unresolved.

### 3. Find credible seams

Classify responsibilities by reason to change: parsing, normalization, validation, domain policy, lifecycle, effects, projection, compatibility, and orchestration.
Record data shapes, effect owners, dynamic state, and dependency direction before naming destination modules or components.

Before choosing boundaries, check for shared state or external effects, asynchronous work, resource or performance constraints,
trust crossings, independent deployments or persisted formats, and diagnosis or recovery needs.
Read the corresponding [design-risk checks](references/design-risks.md#applicability) for each applicable case.
Establish a concrete constraint or failure case before adding a mechanism; reuse settled contracts rather than reopening them.

A useful seam has a one-sentence job, a named boundary value, mostly one-way dependencies, and independent callers or tests. For existing subsystems, seek a concrete payoff such as removing a cycle, dependency, broad fixture, or recurring coupled edit. For a staged greenfield new tool, justify responsibility, data, and effect seams by approved requirements and lifecycle ownership instead of extraction payoff.
Consumer behavior should remain stable during extraction.

Reject seams supported only by line count, aesthetics, symmetrical names, or hypothetical reuse.
Prefer deleting obsolete, lossy, or misleading APIs over extracting new owners around them; a facade that drops diagnostics, provenance, lifecycle state, or other operation results is not a harmless convenience.
Before detailed design, run the cheapest check that could disprove the seam: a dependency trace, classpath-load check, differential fixture, effect inventory, or focused caller/test probe.
For proposed reusable machinery, plugin hooks, or configurable dimensions, establish the current consumer or hard constraint first.
Consult [complexity justification](../references/complexity-justification.md) only if necessity or required variability remains unclear.

### 4. Define the target boundary

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

### 5. Compare maintenance gain with churn

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

### 6. Challenge and present the design

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

Report the classification, recommended change, decisive evidence, maintenance gain, churn and risks, rejected broader decomposition, and next action.
Name the existing primitive, local change, or selected boundary.
For an early recommendation, omit inapplicable boundary details rather than completing the full design procedure.
For a document task, report its path and validation instead of repeating it.
