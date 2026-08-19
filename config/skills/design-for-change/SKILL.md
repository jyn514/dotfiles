---
name: design-for-change
description: Apply jyn's design and testing preferences when designing, implementing, reviewing, debugging, or refactoring code, APIs, schemas, configuration, or tests. Use for ordinary code changes too, especially data modeling, parsing, invariants, regression coverage, test strategy, and maintainability.
---

# Design for Change

## Model the domain

- Represent data precisely. Avoid overloaded representations and in-band signalling unless an abstraction contains the unsafety.
- Parse, don't validate: centralize checks in a structured domain model. Treat stringly typed structured data as suspect; fix the model instead of overloading meanings.
- Make invalid states unrepresentable when language tools can do so without poor ergonomics, such as needless singleton types.

## Design for testing

Split meaningful business logic and likely bugs where they can be tested. Prefer running most of the system in memory so generated tests can cover many cases cheaply. If database behavior or subtle invariants belong to the trusted computing base, run the real database in memory when practical instead of mocking it. The plan-execute pattern often helps.

- Use property tests when generators express the input space better than enumerated examples.
- Use golden tests with thoughtful fixtures at a consumer-meaningful layer; one shared check function should make cases easy to add and review.
- Seek courage, not coverage: tests should catch consumer-visible divergences and permit refactoring. Do not mirror implementation constants in tests.
- Make example tests read as a meaningful narrative about important edges and costly regressions.

When reviewing a system and its tests, check both directions: required behavior without a test, and tested behavior without a corresponding requirement. Apply this to code, APIs, policies, prompts, workflows, and specifications.
