# Code structure

Read when adding or moving helpers, modules, macros, APIs, compatibility paths, abstractions, or runtime resources.

## Compatibility

Do not preserve compatibility for internal interfaces whose producers and consumers change and deploy together.
Preserve compatibility at external, persisted-data, protocol, and independently deployed boundaries, or when justified by a historical constraint.

If running software loads source directly from the checkout, editing that source can deploy it immediately.
Before the first write to live-loaded source, identify which producer versions and startup configuration remain active.
Test the required old-producer/new-consumer combination using a disposable candidate before replacing the live source.
For example, an already-running launcher can retain its old environment while its next call loads an edited connector from the checkout.
Run that old-launcher/new-connector regression against a disposable candidate before editing the live connector, not during later integration testing.

## Distinguish guarantees from details

API guarantees across ownership, data, effect, or lifecycle boundaries must be explicitly documented.
Do not depend on internal details, exact source code, or coincidentally convenient properties.
This also applies when testing code you wrote yourself.
A boundary is an interface across which caller intent, ownership, data, effects, or lifecycle must remain clear.

When diagnosing a failure across a boundary, identify the producer, consumer, authoritative contract, and contract owner before choosing a fix location.
Repair the owner that violates the contract; do not make a consumer compensate unless a governing compatibility requirement or historical constraint requires it.
If the contract or owner is unsettled, use `architecture-design` to trace the existing path and settle the boundary before editing either side.

Separate caller documentation from implementation comments.
Document a helper's purpose and non-obvious usage contract beside its declaration when callers would otherwise need to read its implementation.
Cover relevant setup, lifecycle ordering, side effects, ownership, failure behavior, and what returned observations include or omit.
For example, explain whether a test harness snapshot includes live state or only persisted entries.
Describe the contract without making callers understand how the implementation fulfills it.

Put implementation comments beside the code they explain.
Explain why a surprising choice exists and what a simpler alternative would break.
Use higher-level summaries to explain an algorithm's intent or invariant when readers would otherwise need to mentally execute the code.
Do not paraphrase statements or repeat what names, types, or straightforward code already explain.
Prefer clearer names and simpler code when those can remove the confusion; retain reasoning that code alone cannot express.
Keep operator instructions and cross-component guarantees in their canonical documentation rather than duplicating them in comments.

Before recommending reuse or implementing nontrivial solved-problem logic, use [Use a library](../use-a-library/SKILL.md) to check the supported interface at its actual pinned version and the cost of private-source integration.

## Choose functions, helpers, and modules

Prefer ordinary functions when they express the required behavior.
Use macros when callers need control over evaluation, binding, syntax, or compile-time generation that ordinary functions cannot provide.
Keep expansion focused on constructing code; put ordinary computation and validation in functions where possible.
Test caller-visible behavior, adding expansion-level checks when the generated shape itself is the contract.
Do not hide ordinary control flow or error handling in a macro merely to shorten the call site.

Before adding a helper, search for existing behavior by its shape and purpose, not just the proposed name.
Share mechanics when callers have a real shared invariant; superficial similarity does not establish one.
A small helper can name a domain concept, isolate effects, or expose a useful contract even with one caller.
Remove obsolete wrappers, aliases, ignored arguments, and duplicate definitions after moving behavior, subject to required compatibility.

Keep behavior with the owner whose job it serves and keep dependencies directed toward that owner rather than back toward an orchestrator.
Do not extract by line count or symmetry.
When ownership or the payoff of a split is unsettled, use [architecture design](../architecture-design/SKILL.md) rather than inventing a boundary for a local edit.
Make optional results, conversions, effects, and failure behavior clear through the language's types, naming conventions, and declaration documentation.

## Design for expected changes

Identify the changes the next editor is likely to make, using the task and existing editing patterns.
Keep things that change together together, and separate independently changing material from the machinery that interprets it.
Give each expected change a clear, authoritative editing location that does not require understanding unrelated implementation details.
Use appropriate native formats and existing mechanisms; avoid speculative abstractions.

For example, keep an HTML footer's copy and layout together in a template; Python supplies the URL and truncation flag.
Changing punctuation or line layout should not require tracing backend branches or editing Python-generated markup.
Keep algorithm internals in code rather than turning every constant into configuration.

When reviewing, ask: does a small, expected change require tracing or modifying unrelated code?

## Define structural refactor interfaces

- Before a structural refactor, declare the supported interface modes—library import, module invocation, direct script invocation, or a deliberate subset—and test exactly the declared modes.
  Do not let execution context choose an accidental API.
- Move existing implementation bodies behind the selected interface.
  Do not preserve duplicate owners by wrapping legacy entrypoints through imports or subprocesses; retain compatibility only as a thin re-export or remove the old path.
- After selecting a new owner, search for the old orchestrator and parallel implementations.
  The refactor is incomplete while two modules can independently make the same decision.

## Justify new mechanisms

Require a current requirement, independent consumer, reproduced failure, or pre-existing hard constraint before adding machinery.
Compare the existing path and the smallest direct solution first.
Treat every added process, container, network, daemon, cache, store, or lifecycle owner as a design change, even when it is easy to express in code.

Before proposing a new runtime resource, inventory nearby existing owners, including resources on the same trust, connectivity, and ownership path.
Give each plausible candidate one disposition: `reuse`, `extend`, `reuse when both features are selected`, or `reject`.
For a rejection, name the concrete requirement the resource cannot meet.

A conditionally created resource remains a reuse candidate.
Absence in some modes does not justify a parallel resource in modes where both exist.
For example, compare extending a gateway only when two capabilities overlap before assigning the second capability its own sidecar.
Do not design or implement the new resource until every closer existing owner has a supported rejection grounded in concrete required behavior.

When consumers or required variability remain unclear, use the detailed [complexity-justification checks](complexity-justification.md).
Do not turn a proposed mechanism into its own requirement.
