---
name: design-for-change
description: Apply jyn's design and testing preferences when a change requires unresolved decisions about data modeling, parsing, invariants, interfaces, ownership, enforcement mechanisms, regression-test strategy, or test oracles. Examples include changing a parser's accepted language, separating a CLI from its library, or replacing a mock that misses consumer failures. Baselines of existing violations, exception expiry, and rules for weakening enforcement belong to ratchet. Do not load for routine edits, simple configuration changes with an established shape (such as changing a documented keybinding and validating the config), read-only diagnosis, or general project advice.
---

# Design for Change

Load once per coherent change; reload only when scope or governing constraints change.

## Model the domain

- Represent data precisely. Avoid overloaded representations and in-band signalling unless an abstraction contains the unsafety.
- Parse, don't validate: centralize checks in a structured domain model. Treat stringly typed structured data as suspect; fix the model instead of overloading meanings.
- Make invalid states unrepresentable when language tools can do so without poor ergonomics, such as needless singleton types.
- Choose the strongest cheap enforcement mechanism for the named invariant: types, compiler or lint rules, regression tests, static checks, runtime assertions, or benchmarks.
- Before a structural refactor, declare the supported interface modes—library import, module invocation, direct script invocation, or a deliberate subset—and test exactly the declared modes. Do not let execution context choose an accidental API.
- Move existing implementation bodies behind the selected interface. Do not preserve duplicate owners by wrapping legacy entrypoints through imports or subprocesses; retain compatibility only as a thin re-export or remove the old path.
- After selecting a new owner, search for the old orchestrator and parallel implementations. The refactor is incomplete while two modules can independently make the same decision.

## Design for testing

Split meaningful business logic and likely bugs where they can be tested. Prefer running most of the system in memory so generated tests can cover many cases cheaply. If database behavior or subtle invariants belong to the trusted computing base, run the real database in memory when practical instead of mocking it. The plan-execute pattern often helps.

- Tests may mutate owned disposable resources, but must not modify the authoritative checkout's source files or checked-in artifacts, real user state, or shared services. Test regeneration in temporary storage or check-only mode; a failing freshness check must not repair the artifact it checks. Require explicit authorization for exceptions that affect live state.
- Register automated suites with the repository's top-level test command, either by default or through a documented opt-in mode. Verify that the command discovers and executes them; a focused invocation alone does not prove reachability. Report missing prerequisites and skips distinctly from passing checks.
- Use property tests when generators express the input space better than enumerated examples. When combinations or action sequences exceed a practical hand-written matrix, use bounded generated tests with requirement-derived or consumer-validated oracles. Record failing inputs for replay and reduce them to small regressions when practical. Use [property-based-testing](../property-based-testing/SKILL.md) for property-specific generator design and review.
- Verify that executed generated cases contain the declared input classes and selected interactions, including after filtering or deduplication. Do not infer this from generator code alone. Include required cases explicitly when random generation cannot reliably exercise them; this check does not require an exhaustive cross-product.
- Use golden tests with thoughtful fixtures at a consumer-meaningful layer; one shared check function should make cases easy to add and review.
- For ports or parity-preserving rewrites, identify the reference implementation or pinned test revision and compare both implementations on the same cases. Keep reference expectations separate from candidate-generated output. Record intended divergences against the governing requirements; ask only when accepting a divergence would change those requirements. Treat formatting normalization separately from changes to values, error behavior, or case eligibility.
- Seek courage, not coverage: tests should catch consumer-visible divergences and permit refactoring. Do not mirror implementation constants in tests.
- Do not mechanically update tests that assert implementation text, constants, or structure. When such a test breaks, identify the consumer-visible regression it prevents; replace it with a behavioral test, or delete it if no practical test protects that behavior. An existing test is not evidence that it is valuable.
- Before adding or updating a test, name a realistic regression caused by a likely edit or previously observed failure and a valid change the test must allow. Verify the test fails when the regression is reintroduced. Otherwise, do not add or update it. When expected values depend on mutable configuration or dependency behavior, exercise the valid change within the supported modes, or explain why the governing contract fixes those values. Distinguish reproducing the reported error from demonstrating a related failure; state what the experiment proves.
- When a reported bug escapes passing tests, identify the missing input dimension, action sequence, or incorrect oracle assumption. Update the corresponding case matrix, generator, or oracle and retain the concrete regression; adding only the failing example does not address the testing gap.
- When several conditions determine acceptance, selection, or a lifecycle transition, build a small decision table from the requirements. For each independently significant condition, include two feasible cases that differ only in that condition and produce the required difference in observable behavior. Record coupled or infeasible combinations. Add interaction cases justified by the contract or observed failures; independent-condition pairs do not establish interaction coverage. Derive expected results independently of the implementation. The table can live in parameterized test cases; no separate artifact is required. This checks the declared decision model, not instrumented code coverage.
- Validate the test oracle against the consumer's actual behavior. A mock accepting generated Docker arguments does not establish that Docker can mount them. Check equivalence and cardinality when relevant: distinct occurrences, objects, refs, paths, or owners must not collapse because normalized text or fingerprints match. If no reliable oracle is available, record that validation limit rather than claiming the invariant is protected.
- When behavior is assembled from multiple producers, test the complete consumer-visible result and make the original failure recur when any producer duplicates or omits an entry.
- Introduce each handoff with the smallest native producer-to-consumer regression through the intended interfaces. For example, test a CLI with a small valid input snapshot rather than replacing its snapshot consumer with a separate fixture-JSON API.
- Allow temporary probes or fixture-specific adapters only to resolve a demonstrated uncertainty or prerequisite; a future integration TODO is insufficient. Preserve probes that establish acceptance as regression tests; one-off uncertainty probes need not persist. Do not promote temporary implementations into production interfaces.
- Test both failure directions: accepting invalid results and losing required valid results. Include representative non-special-cased inputs where general behavior is required. For bounded algorithms, test forced work separately from branching work; small fixtures must not conceal the required input-population constraint. Preserve validation and publication constraints rather than relaxing them for a passing test.
- Make example tests read as a meaningful narrative about important edges and costly regressions.
- For public refactors, run a clean-interpreter check from the repository root for every supported import and invocation mode; test discovery or an injected module path does not establish package reachability.
- When a user rejects the current design, stop implementation, restate the revised ownership boundary, and continue only from that boundary.

When reviewing a system and its tests, check both directions: required behavior without a test, and tested behavior without a corresponding requirement. Apply this to code, APIs, policies, prompts, workflows, and specifications.

Use [ratchet](../ratchet/SKILL.md) for unresolved enforcement-policy decisions about existing violations, baseline updates, bounded exceptions, or replacing guarantees. A new regression test or a better oracle alone does not need that workflow.

Use [double-check's evidence standards](../double-check/SKILL.md#evidence-and-integration-status) to determine what the checks prove; run its full audit only after the owned edits are complete. For explicitly authorized unattended work, [autonomous-implementation](../autonomous-implementation/SKILL.md) owns milestone order and continuity, not test construction.
