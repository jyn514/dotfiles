# Develop a boundary design

Read when the initial caller-to-result trace leaves an unmet behavior requiring an ownership, dependency, interface, or resource-lifetime decision.
These development checks also apply when critiquing such a decision; review does not authorize redesign.

## Inspect the gap that remains

Let the unmet behavior determine what to inspect next.
The aim is to find which responsibility must change, not to complete an inventory of surrounding systems.

**Is a capability missing, or merely behind another interface?**
For an intermediary, compare retaining, replacing, and bypassing it against required capabilities.
Inspect the native interface and an analogous adapter before choosing what to forward or restrict.
If the native interface is insufficient, compare a narrow extension with an adapter, including maintenance, packaging, and upstream delay.

**Does work need a new owner, or does an existing owner already do it?**
For repeated construction, follow constructors and factories into configuration, discovery, admission, process launches, and network requests.
Locate existing owners and apply the [runtime-resource reuse check](../../references/code-structure.md#justify-new-mechanisms) before adding discovery or resources.
This establishes what can be shared; its lifetime determines whether reuse is correct.

**What must stay bound together, and what must refresh?**
For resource bindings, establish the owner, lifetime, and replacement event, including later-loaded executable contents.
Check producer and consumer deployment lifetimes; a shared checkout does not make updates atomic.
Reuse selection for its established lifetime, retain fresh admission checks where required, and identify dynamic observations such as identity, credentials, and contents.
For ordered discovery caches, read the [unsuccessful-lookup example](caching-examples.md); for reuse or equality changes, read [Reuse and invalidation](../../references/data-and-effects.md#reuse-and-invalidation).

Inspect adjacent systems, generated contracts, issues, or prepared work when they can settle the choice or prevent duplication.
Use `pain-axis` when recurring historical pain can change it.
Read [Map design alternatives](alternatives.md) for genuine alternatives and [independent deliberation](deliberation.md) when independent elaboration and critique earn their cost.
Use [complexity justification](../../references/complexity-justification.md) for unclear necessity or variability, and the [non-narrowing check](../../spec-review/references/non-narrowing.md) for possible requirement narrowing.

## Principles

Apply the shared [boundary and caller-contract rules](../../references/code-structure.md#distinguish-guarantees-from-details).
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

Use [boundary contracts](boundary-contracts.md) for changed or unresolved guarantees.
Continue applying the topic references selected through `coding-judgement`, including during critique.
Ground each check in a requirement, observed constraint, or concrete failure case; choose workload and compatibility targets from requirements.
Compare removing the interaction or using its existing owner before adding machinery.
Resolve risks with the cheapest sufficient evidence and record unresolved or changed guarantees in the boundary contract.
During critique, report contract gaps rather than redesigning the system.
For independently deployed components or persisted state, use the shared [deployment and evolution checks](../../references/deployment-and-evolution.md).
Carry settled contracts forward.
Run the cheapest check that could disprove the seam: a dependency trace, load check, effect inventory, or focused caller/test probe.

Keep consumer behavior stable during extraction.
Separate schema redesign, message rewrites, new frameworks, and public API expansion unless explicitly in scope.
When tests or fixtures move, use [test partitioning](../../references/testing.md#partition-tests-alongside-an-extraction) to preserve owner-specific cases and assembled integration coverage.

Return to [Decide whether the gain earns the cost](../SKILL.md#decide-whether-the-gain-earns-the-cost) before recommending or handing off the result.
