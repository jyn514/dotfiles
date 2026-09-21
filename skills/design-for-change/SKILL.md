---
name: design-for-change
description: Apply jyn's design and testing preferences when designing, implementing, reviewing, debugging, or refactoring code, APIs, schemas, configuration, or tests. Use for ordinary code changes too, especially data modeling, parsing, invariants, regression coverage, test strategy, and maintainability. Load once per coherent change; do not reactivate for continuation or commit-only prompts unless the design or testing problem changes.
---

# Design for Change

Apply these principles throughout one coherent change after loading them once. A continuation, review checkpoint, or commit request does not require reloading unless new information changes the design or testing problem.

## Model the domain

- Represent data precisely. Avoid overloaded representations and in-band signalling unless an abstraction contains the unsafety.
- Parse, don't validate: centralize checks in a structured domain model. Treat stringly typed structured data as suspect; fix the model instead of overloading meanings.
- Make invalid states unrepresentable when language tools can do so without poor ergonomics, such as needless singleton types.
- Before a structural refactor, declare the supported interface modes—library import, module invocation, direct script invocation, or a deliberate subset—and test exactly the declared modes. Do not let execution context choose an accidental API.
- Move existing implementation bodies behind the selected interface. Do not preserve duplicate owners by wrapping legacy entrypoints through imports or subprocesses; retain compatibility only as a thin re-export or remove the old path.
- After selecting a new owner, search for the old orchestrator and parallel implementations. The refactor is incomplete while two modules can independently make the same decision.

## Design for testing

Split meaningful business logic and likely bugs where they can be tested. Prefer running most of the system in memory so generated tests can cover many cases cheaply. If database behavior or subtle invariants belong to the trusted computing base, run the real database in memory when practical instead of mocking it. The plan-execute pattern often helps.

- Use property tests when generators express the input space better than enumerated examples.
- Use golden tests with thoughtful fixtures at a consumer-meaningful layer; one shared check function should make cases easy to add and review.
- Seek courage, not coverage: tests should catch consumer-visible divergences and permit refactoring. Do not mirror implementation constants in tests.
- Do not mechanically update tests that assert implementation text, constants, or structure. When such a test breaks, identify the consumer-visible regression it prevents; replace it with a behavioral test, or delete it if no practical test protects that behavior. An existing test is not evidence that it is valuable.
- Before adding or updating a test, name a realistic regression caused by a likely edit or previously observed failure, and verify the test fails when that regression is reintroduced. Otherwise, do not add or update it.
- When behavior is assembled from multiple producers, test the complete consumer-visible result and make the original failure recur when any producer duplicates or omits an entry.
- Make example tests read as a meaningful narrative about important edges and costly regressions.
- For public refactors, run a clean-interpreter check from the repository root for every supported import and invocation mode; test discovery or an injected module path does not establish package reachability.
- When a user rejects the current design, stop implementation, restate the revised ownership boundary, and continue only from that boundary.

When reviewing a system and its tests, check both directions: required behavior without a test, and tested behavior without a corresponding requirement. Apply this to code, APIs, policies, prompts, workflows, and specifications.
