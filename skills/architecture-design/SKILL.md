---
name: architecture-design
description: "Design, critique, or choose a bounded software architecture: subsystem ownership, dependency direction, data/effect and lifecycle contracts, API shape, maintainability gain, and churn. Use for architecture documents, extraction candidates, unresolved architecture choices, or whether a split/refactor is worth doing. Use also when authoring or revising a design/specification requires choosing an approach or introducing or changing guarantees, supported cases, or failure behavior, even when the request is framed as updating documentation. Trace the existing path first; optional references support genuine alternatives and independent deliberation. Reuse settled contracts. Not for broad project discovery, implementation planning, recording already-settled decisions, prose-only edits, routine local edits with settled boundaries, or current-change review."
---

# Architecture Design

Design or critique one selected subsystem and decide whether a change is worth its churn.
Recommend the smallest sufficient change, grounded in a real caller path and governing requirements, rather than file size or hypothetical reuse.
For critique, report supported findings, consequences, and the smallest useful corrections; a review request does not authorize edits or require a replacement design.
Use the procedure below when developing or comparing approaches is requested.

## Establish scope and authority

Identify the target, current problem, constraints, non-goals, compatibility posture, and requested output.
Read the target repository's architecture, ownership, data/effects, testing, and design-document guidance, plus nearest instructions for every subsystem in scope.
Stop and use `opportunity-scan` if no subsystem is selected.
For staged new-tool work, use approved requirements and integration constraints without inventing product scope; design contributes to the implementation specification and does not replace it.
Check the practical purpose of the request as well as its literal wording, without overriding explicit requirements.
State the minimum observable outcome before considering state, tracking, acknowledgment, or coordination mechanisms.
For each proposed mechanism, identify the requirement or pre-existing constraint that needs it; apply the shared decision-authority rule when classifying proposed guarantees.
Before designing interfaces or configuration, list each dimension the request requires to vary and its authoritative source; keep unspecified policy fixed and record deliberately fixed behavior.
Before choosing persistence, identify who owns the data, where and in what form it persists, its lifetime, who can read it, and who can rotate or recover it.
Changing the principal or medium changes behavior and requires authority.
Changing persistence, protection, or lifetime is not a routine implementation choice.
If the request does not settle a consequential storage-boundary change, ask before designing the dependent mechanism.
Continue independent analysis while that decision is unresolved.
Compare the smallest existing-primitive solution first.
Use the [contrasting examples](references/simplicity-examples.md) when a proposed mechanism, guarantee, or intermediary obscures that comparison.

## Principles

A boundary is an interface across which caller intent, ownership, data, effects, or lifecycle must remain clear; use these principles for design and critique without starting the full workflow.
Avoid unnecessary coupling: expose caller intent rather than callee details, keep policy separate from effects as declarative data, and let one owner make a decision before passing its result across systems when possible.
Do not mix concerns just because it simplifies the current implementation.

Before designing an application workaround for a tool limitation, inspect the tool's data model and extension points and establish whether changing the tool is permitted.
A missing CLI option does not prove a missing model capability or immutable dependency.
If the existing interface is insufficient, compare a narrow native extension with an adapter, including maintenance, packaging, and upstream delay.

Prefer simplicity over exhaustiveness: complexity can itself reduce reliability.
Prefer designs that work without ongoing intervention.
Before adding coordination, retries, monitoring, or lifecycle state, check whether changing ownership or batching removes the need; before extending for edge cases, check whether requirements can be narrowed without violating them.
Add no feature or configurable dimension without an explicit requirement; keep adjacent policy fixed.
Require explicit input when omission could choose the wrong identity, target, scope, or high-consequence action; otherwise use a sensible default.

## Trace, challenge, decide

Trace one complete caller-to-result path using existing commands, identifiers, and defaults.
For an existing subsystem, inspect the affected specification, implementation, same-path tests, and callers.
For greenfield work, trace the closest existing primitive or integration caller; do not require a current implementation or extraction history.
Inspect adjacent systems, runtime/deployment boundaries, and integration callers only when that can resolve a choice or establish candidate sufficiency.
Identify the result the caller needs and compare what the path already provides with the governing outcome.
Check ownership, authorization, compatibility, storage, and supported-interface constraints that could change whether the direct path suffices.
If sufficiency is uncertain, use the cheapest check that can decide it.
If the direct route meets the outcome, recommend it as complete and stop before proposal-specific inspection.

**If a choice remains,** use further implementation and resource inspection only when it can resolve that choice or establish a candidate's sufficiency.
Consult API inventories, generated contracts, issues, and prepared work only when they could change the boundary or prevent duplicate work.
For adapters and proxies, inspect the native interface and an existing analogous adapter before deciding what to forward, restrict, or replace.
Before replacing an intermediary, compare the current route with a direct producer-to-consumer route and identify the capability lost by omitting it and where that capability is required.
For repeated client, runtime, or adapter construction, trace constructors and factories through to external effects.
Identify repeated resource selection and admission checks, including configuration reads, process launches, and network requests; determine whether an existing owner already selected or admitted the resource before adding another discovery path.
Before proposing a new runtime resource or lifecycle owner, use the shared runtime-resource reuse check in `change-with-evidence` to inventory existing owners and justify the new resource.
For a proposed resource binding, identify its owner, lifetime, and replacement event; include executable code as well as configuration, since a fixed path does not bind later-loaded contents.
Check actual producer and consumer deployment lifetimes rather than assuming a shared checkout makes updates atomic.
Separate resource selection from admission checks and observations of mutable state.
Reuse a selection only for its established lifetime, retain fresh checks where required, and identify values that must remain dynamic within that lifetime, including caller identity, credentials, and resource contents.
For caches involving ordered discovery, read [the unsuccessful-lookup example](references/caching-examples.md).
For proposed reuse, invalidation, or equality changes, read [Reuse and invalidation](references/design-risks.md#reuse-and-invalidation).

Before elaborating a proposed interface, record, protocol, or resource, identify the concrete requirement it serves and the case the existing path cannot satisfy.
Distinguish required behavior from optional guarantees introduced by the proposal.
Name the hardest part and ask whether removing it preserves required behavior, timing, coverage, and constraints.
If a supported existing primitive or local change is sufficient, recommend it as complete and stop before boundary design.
Show the traced path, decisive comparison, required change, and verification limits.
Do not weaken a requirement to obtain a simpler design.
When sufficiency is uncertain, use the cheapest decision-changing check rather than assuming a larger design is needed.
Keep speculative hardening outside the recommendation.

Consult only the guidance needed for a concrete unresolved question:

- Use `opportunity-scan` when no subsystem has been selected.
- Use `pain-axis` when recurring historical pain may change the design.
- Read [alternatives](references/alternatives.md) when tracing leaves a genuine architectural choice.
- Use [deliberation](references/deliberation.md) only when that choice needs independent elaboration and critique; do not make multi-agent work the default.
- Use `implementation-plan` only when a repository plan is requested, carrying forward the boundary contract.
- If a boundary choice remains, use [design-risk applicability](references/design-risks.md#applicability) to select checks for the observed subsystem.
- After selecting a boundary, revisit only risks that boundary introduces or changes.
- Read [boundary contracts](references/boundary-contracts.md) only for unresolved or changed ownership, representations, effects, identity, lifecycle, or recovery guarantees.
- Use [complexity justification](../references/complexity-justification.md) when a mechanism's necessity, consumers, or required variability remains unclear.
- Use `spec-review`'s [non-narrowing check](../spec-review/references/non-narrowing.md) for a concrete question about whether a contract narrows governing requirements.
- For a current patch, use the repository's current-change review process.

## Choose a coherent boundary when needed

Continue only if a genuine architectural choice remains.

### Define the target contract

State the target contract: responsibilities moving and remaining, allowed dependencies and forbidden reverse edges, API treatment, and any facade's justification and removal condition.

Classify responsibilities by reason to change, then identify their data, effect owners, dynamic state, and dependency direction before naming destination components.
A useful seam has a one-sentence job, a named boundary value, mostly one-way dependencies, and independent callers or tests.
For existing systems, require a concrete payoff such as removing a cycle, dependency, broad fixture, or recurring coupled edit.
For staged greenfield tools, ground responsibility, data, and effect seams in approved requirements and lifecycle ownership.

Establish a concrete constraint or failure case before adding a mechanism.
Use history as evidence when useful, but do not equate churn with pain; check whether the proposed arrangement existed before and why it changed, since a prior separation may encode a correctness constraint.
Prefer an existing domain owner for single-consumer policy and a coherent lifecycle or shared contract over a bag of helpers.
Reject seams justified only by line count, aesthetics, symmetrical naming, or hypothetical reuse.
Prefer deleting obsolete, lossy, or misleading APIs over extracting owners around them; a facade that drops diagnostics, provenance, lifecycle state, or operation results is not harmless.
Run the cheapest check that could disprove a proposed seam, such as a dependency trace, classpath-load check, differential fixture, effect inventory, or focused caller/test probe.
For proposed reusable machinery, hooks, or configurable dimensions, establish the current consumer or hard constraint first.

Keep extraction separate from behavior changes, schema redesign, message rewrites, new frameworks, and public API expansion unless explicitly in scope.

Consumer behavior should remain stable during extraction.
When an extraction changes test ownership or shared fixtures, use [test partitioning](../references/testing.md#partition-tests-alongside-an-extraction) to separate owner-specific cases from assembled integration coverage.
A proposed cycle is a failed boundary unless an existing public adapter owns the composition.

## Compare gain with churn and challenge the result

Count affected callers, tests, dynamic state, generated artifacts, inventories, and compatibility surfaces.
For staged greenfield tools, compare implementation and integration cost instead of migration churn.
Name what becomes cheaper or safer; moving functions alone is not a benefit.
Classify the result:

- `RECOMMEND`: concrete gain exceeds bounded implementation and migration cost.
- `CONDITIONAL`: one named measurement, consumer, or prerequisite remains.
- `REJECT`: complexity, implementation cost, or churn exceeds demonstrated benefit.

For existing systems, a partial extraction is complete when it removes the motivating pain.
For greenfield tools, stop when the design meets approved requirements without unsupported machinery.
Challenge whether the design improves ownership rather than shortening a file, preserves coupling behind a facade, gives a leaf orchestration or policy, or reopens settled contracts.
Ask which seam is weakest and whether its gain exceeds its churn.
Use existing caller or test evidence when it settles remaining uncertainty.
Delegate one review only when independent evidence or useful parallelism earns its cost.
Revise the recommendation when the evidence challenges it.

## Present the result

For an early recommendation, omit inapplicable boundary details rather than completing the full procedure.
For a durable document, follow repository conventions and include only applicable scope, evidence, selected and rejected seams, ownership, data/dependency flow, compatibility, tests, risks, acceptance evidence, and open questions.
Compile it when its format requires it.
Architecture assessment alone does not require a new document, implementation tasks, or a commit plan.

Report the classification, recommended change, decisive evidence, maintenance gain, churn and risks, rejected broader decomposition, and next action.
Name the existing primitive, local change, or selected boundary.
For document tasks, report the document path and validation rather than repeating its contents.

## Issue handoff

Open issues only when requested.
Follow repository tracker guidance, search by exact proposed title and boundary to avoid duplicates, and separate independent extractions.
A ready issue names current coupling, selected owner, dependency direction, preserved behavior, compatibility treatment, tests, mechanical boundary checks, exclusions, and stopping point.
Keep conditional work out of an implementation-ready state until its named prerequisite exists.
