---
name: architecture-design
description: "Design, critique, or choose a bounded software architecture: subsystem ownership, dependency direction, data/effect and lifecycle contracts, API shape, maintainability gain, and churn. Use for architecture documents, extraction candidates, unresolved architecture choices, or whether a split/refactor is worth doing. Use also when authoring or revising a design/specification requires choosing an approach or introducing or changing guarantees, supported cases, or failure behavior, even when the request is framed as updating documentation. Trace the existing path first; optional references support genuine alternatives and independent deliberation. Reuse settled contracts. Not for broad project discovery, implementation planning, recording already-settled decisions, prose-only edits, routine local edits with settled boundaries, or current-change review."
---

# Architecture design

Choose responsibilities that meet the required outcome and earn their implementation and maintenance cost.
Start with a caller-to-result path, not a proposed component diagram.
For critique, report supported findings, consequences, and the smallest useful corrections; a review request does not authorize edits or require a replacement design.

## Establish the outcome and authority

Identify the subsystem, problem, constraints, non-goals, compatibility, and requested output.
State the minimum observable outcome and its practical purpose before choosing mechanisms.
Stop and use `opportunity-scan` if no subsystem is selected.
Read the repository's relevant architecture, ownership, data/effects, testing, and design-document guidance and nearest subsystem instructions.
For staged new-tool work, contribute to the implementation specification against approved requirements and integration constraints without inventing product scope.

Use the shared decision-authority rule to distinguish requirements from proposed guarantees.
Before elaborating a mechanism, name its requirement or hard constraint and the case the existing path cannot satisfy.
Identify required variability and its authoritative sources; keep adjacent policy fixed and record deliberate defaults.
Require explicit input when omission could choose the wrong identity, target, scope, or high-consequence action; otherwise choose a sensible default.

Before choosing persistence, establish the data's owner, medium, form, lifetime, readers, and rotation or recovery authority.
Changes to principal, medium, protection, or lifetime change behavior.
Ask about unsettled consequential storage changes before designing dependent mechanisms; continue independent analysis.

## Trace the smallest complete solution

Follow one caller-to-result path through commands, identifiers, defaults, effects, and failures.
Inspect its specification, implementation, callers, and same-path tests; for greenfield work, trace the closest primitive or integration caller.
Compare it with the outcome and required ownership, authorization, compatibility, storage, and supported interfaces.
Before designing an application workaround for a tool limitation, inspect the tool's data model and extension points and establish whether changing the tool is permitted.
Use the cheapest decision-changing check where sufficiency is uncertain.
If the path or a local change suffices, recommend it and stop before proposal-specific inspection or boundary design.

For example, an existing save-and-exit operation and verifiable saved record may preserve sessions through restart without a new receipt protocol.
They cannot acknowledge a specific save while the session continues running.
Read the [contrasting examples](references/simplicity-examples.md) when a proposed mechanism obscures the simpler complete path.

## Inspect the gap that remains

Let the unmet behavior determine what to inspect next.
The aim is to find which responsibility must change, not to complete an inventory of surrounding systems.

**Is a capability missing, or merely behind another interface?**
For an intermediary, compare retaining, replacing, and bypassing it against required capabilities.
Inspect the native interface and an analogous adapter before choosing what to forward or restrict.
If the native interface is insufficient, compare a narrow extension with an adapter, including maintenance, packaging, and upstream delay.

**Does work need a new owner, or does an existing owner already do it?**
For repeated construction, follow constructors and factories into configuration, discovery, admission, process launches, and network requests.
Locate existing owners and apply the [runtime-resource reuse check](../references/change-with-evidence.md#justify-new-mechanisms) before adding discovery or resources.
This establishes what can be shared; its lifetime determines whether reuse is correct.

**What must stay bound together, and what must refresh?**
For resource bindings, establish the owner, lifetime, and replacement event, including later-loaded executable contents.
Check producer and consumer deployment lifetimes; a shared checkout does not make updates atomic.
Reuse selection for its established lifetime, retain fresh admission checks where required, and identify dynamic observations such as identity, credentials, and contents.
For ordered discovery caches, read the [unsuccessful-lookup example](references/caching-examples.md); for reuse or equality changes, read [Reuse and invalidation](references/design-risks.md#reuse-and-invalidation).

Inspect adjacent systems, generated contracts, issues, or prepared work when they can settle the choice or prevent duplication.
Use `pain-axis` when recurring historical pain can change it.
Read [Map design alternatives](references/alternatives.md) for genuine alternatives and [independent deliberation](references/deliberation.md) when independent elaboration and critique earn their cost.
Use [complexity justification](../references/complexity-justification.md) for unclear necessity or variability, and the [non-narrowing check](../spec-review/references/non-narrowing.md) for possible requirement narrowing.

## Principles

A boundary is an interface across which caller intent, ownership, data, effects, or lifecycle must remain clear.
These principles also apply to critique without a full design workflow.

When possible, let one owner decide and pass its result across systems rather than making consumers decide again.
Expose caller intent rather than callee details, separate policy from effects as declarative data, and group responsibilities by their reasons to change.
Keep single-consumer policy with its domain owner.
A coherent lifecycle or shared contract makes a stronger owner than convenient helpers.

Prefer arrangements that work without ongoing intervention.
Before adding coordination, retries, monitoring, or lifecycle state, compare changing ownership or batching to remove the interaction.
Test whether removing a candidate's hardest part preserves required behavior, timing, coverage, and constraints.
Simplicity does not authorize narrower requirements.

## Develop and test the boundary

Use the inspected gap to define what moves, what remains, and why.
Identify data, effect owners, and dynamic state before naming components.
Define allowed dependencies, forbidden reverse edges, API treatment, and any facade's purpose and removal condition.
A useful seam has a one-sentence job, a named boundary value, mostly one-way dependencies, and independent callers or tests.
A cycle fails it unless an existing public adapter owns the composition.

For an existing system, demonstrate a payoff: a removed cycle, dependency, broad fixture, or recurring coupled edit.
Check previous separations when history could reveal a correctness constraint; churn alone is not pain.
For greenfield work, derive seams from approved requirements and lifecycle ownership.
Line count, symmetry, and hypothetical reuse do not establish a payoff.
Consider deleting obsolete or lossy APIs rather than preserving facades that discard diagnostics, provenance, lifecycle state, or results.

Use [boundary contracts](references/boundary-contracts.md) for changed or unresolved guarantees and [design-risk checks](references/design-risks.md#applicability) for the actual subsystem and boundary.
Carry settled contracts forward.
Run the cheapest check that could disprove the seam: a dependency trace, load check, effect inventory, or focused caller/test probe.

Keep consumer behavior stable during extraction.
Separate schema redesign, message rewrites, new frameworks, and public API expansion unless explicitly in scope.
When tests or fixtures move, use [test partitioning](../references/testing.md#partition-tests-alongside-an-extraction) to preserve owner-specific cases and assembled integration coverage.

## Decide whether the gain earns the cost

Compare demonstrated maintenance or safety gain with affected callers, tests, dynamic state, generated artifacts, inventories, and compatibility surfaces.
For greenfield work, compare implementation and integration cost instead of migration churn.
Moving functions alone is not a benefit.
Challenge the weakest seam: does it improve ownership, hide coupling behind a facade, give a leaf orchestration or policy, or reopen settled contracts?
Use existing evidence when sufficient; delegate one review only for independent evidence or useful parallelism.
Revise the recommendation when evidence challenges it.

Classify the result:

- `RECOMMEND`: demonstrated gain exceeds bounded cost.
- `CONDITIONAL`: one named measurement, consumer, or prerequisite remains.
- `REJECT`: complexity or churn exceeds demonstrated benefit.

Stop extraction when it removes the motivating pain; stop greenfield design when approved requirements are met without unsupported machinery.
Keep speculative hardening outside the recommendation.

## Present or hand off

Report the classification, chosen solution, decisive comparison, gain, costs, risks, verification limits, rejected broader design, and next action.
An early recommendation needs no inapplicable boundary detail or new document.
A requested durable document follows repository conventions and records applicable scope, evidence, contracts, tests, acceptance evidence, and open questions; compile when required and report its path.
Architecture assessment does not itself require implementation tasks or a commit plan.
Use `implementation-plan` only when a repository plan is requested; carry the contract forward.
Use the repository's review process for a current patch.

Open issues only when requested, following tracker guidance and searching by exact title and boundary for duplicates.
Separate independent extractions and record the motivating coupling, boundary contract, checks, exclusions, and stopping point.
Keep conditional work out of an implementation-ready state until its prerequisite exists.
