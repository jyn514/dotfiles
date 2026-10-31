---
name: property-based-testing
description: "Write, review, and debug property-based tests — Hypothesis, fast-check, proptest, jqwik, rapid, and Echidna or Medusa for Solidity invariants. Use whenever tests should cover a whole input domain rather than a hand-picked list of examples: encode/decode and serialize/deserialize pairs, parsers, canonicalizers and normalizers, validators, numeric and Decimal types, comparators and sort order, data structures, stateful/model-based action sequences and lifecycle transitions, and smart-contract state invariants. Also use when adding cases to an existing @given, fast-check, or proptest suite; judging whether existing property tests assert anything real; or distinguishing a wrong property from a genuine bug after a generator shrinks a counterexample. Not for coverage-guided binary fuzzing (libFuzzer, AFL), mutation-testing campaigns, static analysis, benchmarking, or end-to-end UI tests."
---

# Property-Based Testing

## Decide whether a property test fits

An example test asserts one point.
A property asserts a rule over the whole input domain and lets the generator hunt for a
counterexample.
Use property-based testing when the code has an algebraic shape — such as an inverse,
invariant, or oracle.
Otherwise, example tests are the better fit; reporting that is a valid outcome.

## If no direct property is exposed

The code may have a property but no direct seam for asserting it. For example, I/O may
wrap a calculation, concatenation may build a string, or a function may mutate in place.
If that is the obstacle, see [references/refactoring.md](references/refactoring.md)
for possible small rearrangements before concluding there is nothing to assert.

## Start within the authorized scope

Inspect the requested surfaces, their contracts, existing tests, and test runner.
Choose properties whose expected results are independent of the implementation.
Use [testing guidance](../references/testing.md) for regression/valid-change
evidence, executed-case coverage, isolation, and top-level test reachability; this
skill owns property and generator design, not production refactoring or broader
coverage policy. Review-only requests
do not authorize edits. Do not expand a bounded task to every public API.

Use the existing test framework. Bounded generated tests can use its ordinary
assertions without a new PBT dependency; retain the seed and failing input for
replay, and reduce failures manually when automatic shrinking is unavailable.

## Property catalog

| Property | Formula | Where it applies |
|---|---|---|
| Roundtrip | `decode(encode(x)) == x` | Serialization, conversion pairs |
| Inverse | `f(g(x)) == x` | encrypt/decrypt, compress/decompress |
| Oracle | `new(x) == reference(x)` | Optimization, refactoring, reimplementation |
| Idempotence | `f(f(x)) == f(x)` | Normalization, formatting, sorting |
| Invariant | Holds before and after | Any transformation, contract state |
| Easy to verify | `is_sorted(sort(x))` | Complex algorithms with cheap checkers |
| Commutativity | `f(a, b) == f(b, a)` | Binary and set operations |
| Associativity | `f(f(a,b), c) == f(a, f(b,c))` | Combining operations |
| Identity | `f(x, e) == x` | Operations with a neutral element |

These properties constrain different behavior; there is no universal strength
ordering. A roundtrip can preserve a mutually incompatible encoder/decoder pair,
and idempotence accepts a normalizer that returns a constant. Combine complementary
checks or an independent consumer where the contract requires them.

Assert the strongest practical checks for the requested contract. "No crash" alone
rarely justifies a PBT dependency. If that is all you can find, consider whether a small
rearrangement would expose a stronger property. Rule out that option before reporting
that the code is a poor PBT candidate.

## The two ways a property test asserts nothing

- **Tautology.** `assert add(a, b) == a + b` restates the implementation; no bug they
  share can fail it. Pick a property that constrains the function without recomputing
  it. Note the exception: `f(x) == f(x)` is a genuine determinism property when `f`
  is not obviously pure — serializers over dicts or sets, hashing, anything reading
  the clock.
- **Vacuity.** `assume()` that filters out nearly every input passes without
  exercising the required input classes. Hypothesis rejects exhausted generation
  through health checks, but passing counts alone still do not establish useful
  coverage. Push constraints into the strategy to produce valid inputs directly.

## Where to look next

Load the one that matches the task in front of you:

| Task | File |
|---|---|
| Writing new tests, designing strategies | [references/generating.md](references/generating.md) |
| The code has no property to assert yet | [references/refactoring.md](references/refactoring.md) |
| Reviewing existing property tests | [references/reviewing.md](references/reviewing.md) |
| A property test just failed | [references/interpreting-failures.md](references/interpreting-failures.md) |
| Library choice, Echidna and Medusa | [references/libraries.md](references/libraries.md) |

Before completion, run the written tests, inspect executed input classes, and
review them with `references/reviewing.md`. Report failures and validation limits,
not only aggregate case counts.

## Introducing PBT to a project that lacks it

If the project already uses a PBT library, just write the tests in it. If it does not,
adding one is a dependency decision that belongs to the user — offer it once with the
specific property you would write, and take the answer either way.

Source and licenses: [adaptation notice](README.md).
