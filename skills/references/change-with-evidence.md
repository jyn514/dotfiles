# Change with evidence

These rules apply when designing, implementing, or reviewing code, configuration,
or tests. Read them before that work; they supplement the always-loaded shared
instructions.

Read surrounding context before edits, investigations, or audits.
Do not draw broad conclusions from search snippets.

## Language separation

Apply LANGSEC (language-theoretic security): keep different languages in separate files rather than nesting them. For example, a Python script must launch a separate Bash file, not embed a multiline Bash string.

## Compatibility

Do not preserve compatibility for internal interfaces whose producers and consumers change and deploy together. Preserve compatibility at external, persisted-data, protocol, and independently deployed boundaries, or when justified by a historical constraint.

If running software loads source directly from the checkout, editing that source can deploy it immediately.
Before the first write to live-loaded source, identify which producer versions and startup configuration remain active.
Test the required old-producer/new-consumer combination using a disposable candidate before replacing the live source.

## Single authority

When the same value appears across multiple consumers, choose one authoritative representation and derive the others from it. Consumers should refer to stable roles or interfaces rather than repeat filenames, paths, commands, identifiers, defaults, or other change-prone constants.

Add a regression test showing that changing the authority updates consumers without corresponding edits.

## Logging

Default CLI output must be human-scannable. Show the action, material inputs,
current phase, result, and next action; keep hashes and internal data in
receipts or explicit machine-readable output. Report failures once, stating
what failed, why, cleanup/publication status, and recovery action. Use stdout
for results and stderr for progress or diagnostics. Test representative
success and failure output as a user-facing contract.

## Distinguish guarantees from details

API guarantees between architecture boundaries must be explicitly documented.
Do not depend on internal details, exact source code, or coincidentally convenient properties.
This applies WHENEVER there is an architecture boundary, even when writing tests for code you wrote yourself.
Consult the "Principles" section of `architecture-design` for what constitutes a boundary.

Before recommending reuse, verify that the actual component at its pinned version exposes a supported interface to the intended consumer.
A public API in an underlying library does not expose the tool's private modules.
If reuse requires private-source integration, a downstream patch, or a fork, name that and its maintenance cost before recommending it.

## Justify new mechanisms

Require a current requirement, independent consumer, reproduced failure, or pre-existing hard constraint before adding machinery.
Compare the existing path and the smallest direct solution first.
Treat every added process, container, network, daemon, cache, store, or lifecycle owner as a design change, even when it is easy to express in code.
Inventory nearby existing owners and record `reuse`, `extend`, `reuse when both features are selected`, or `reject` for each plausible candidate.
Conditional creation does not make a candidate unavailable in the modes where both features are selected.
Implement a new runtime resource only when concrete required behavior rejects the smaller reuse paths.
When consumers or required variability remain unclear, use the detailed [complexity-justification checks](complexity-justification.md).
Do not turn a proposed mechanism into its own requirement.

## Design choices

- Identify the smallest change that meets the requested outcome and required compatibility before presenting a design.
- Recommend that change unless concrete evidence shows it is insufficient.
- When evidence is missing, propose a small experiment instead of a larger architecture.
- Treat user-suggested mechanisms as candidates unless the user makes them explicit requirements.
- Prefer fewer interfaces, representations, and ownership boundaries, not weaker correctness checks or fewer tests.
- Represent data precisely. Avoid overloaded representations and in-band signalling unless an abstraction contains the unsafety.
- Parse, don't validate: centralize checks in a structured domain model. Treat stringly typed structured data as suspect; fix the model instead of overloading meanings.
- Make invalid states unrepresentable when language tools can do so without poor ergonomics, such as needless singleton types.
- Choose the strongest cheap enforcement mechanism for the named invariant: types, compiler or lint rules, regression tests, static checks, runtime assertions, or benchmarks.
- Before a structural refactor, declare the supported interface modes—library import, module invocation, direct script invocation, or a deliberate subset—and test exactly the declared modes. Do not let execution context choose an accidental API.
- Move existing implementation bodies behind the selected interface. Do not preserve duplicate owners by wrapping legacy entrypoints through imports or subprocesses; retain compatibility only as a thin re-export or remove the old path.
- After selecting a new owner, search for the old orchestrator and parallel implementations. The refactor is incomplete while two modules can independently make the same decision.

Before implementing parsing or validation, check whether an existing consumer can produce the authoritative result.
Prefer inspecting that result over reproducing its rules.
Explain why reuse is insufficient before implementing a custom parser or validator.

Never edit generated files, installed package checkouts, caches, staged configuration, or build outputs directly.
Change the authoritative source and regenerate through its owning mechanism.
If the source is external or unavailable, propose an upstream change, fork, or intentional vendoring instead.
Before editing outside the active repository, verify that the user intends work there.

## Substitute only equivalent behavior

When a requested or selected mechanism proves unavailable, compare the fallback with the required observable behavior before implementing it.
State which guarantees it preserves, changes, or leaves unverified, including applicable precedence, persistence, ownership, and failure behavior.
Apply the [shared scope rule](~/.agents/shared.md#before-changing-behavior-or-scope) to any changed guarantee outside existing authorization.
Pause dependent implementation until that decision is resolved; continue independent investigation.
An equivalent implementation within the authorized behavior does not need renewed approval.

For example, loading a configuration profile and passing its values as overrides can both select the expected approval reviewer.
If overrides also change precedence over project configuration, passing reviewer tests does not establish equivalence or authorize that change.
During review, check the precedence requirement even when those tests pass.

## Test strategy

When adding or materially changing tests, or resolving an uncertain test strategy or oracle, consult [Testing with evidence](testing.md).
Routine edits with an established shape need no separate design workflow.
When creating or modifying a test, run it and iterate until it passes.
