# Reviewing Property-Based Tests

Review the requested tests, not every public API. For each issue, quote the code,
state the contract or evidence it violates, and suggest the smallest repair.
Distinguish a demonstrated blind spot from an unverified coverage concern; severity
comes from the affected behavior, not a fixed ranking of assertion styles.

## Checklist

- **Independent oracle:** reject tautologies and assertions that reuse the candidate
  to compute its expected result. Check actual values or consumer behavior when
  length, type, success status, or absence of crashes would accept wrong results.
- **Vacuity:** inspect executed cases, not strategy declarations. Contradictory
  `assume()` conditions in Hypothesis exhaust generation and fail its health checks;
  they do not constitute a passing property. Heavy filtering can still waste the
  budget or obscure missing classes. Prefer constructing valid inputs directly.
- **Domain and resource bounds:** compare generators with the contract. Do not
  narrow a range or remove a failing value class merely to obtain green tests.
  Bound collection sizes, recursion, and execution cost explicitly; distinguish
  those practical limits from restrictions on scalar values or legal inputs.
- **Both directions:** for parsers and validators, require valid inputs to retain
  required behavior and invalid inputs to be rejected, not merely avoid a crash.
  Ground each direction in its own contract; not every API has a rejection path.
- **Configuration and variants:** exercise relevant non-default knobs, types, and
  sibling variants within the requested scope. Record intentionally excluded
  combinations. Fixed examples can pin required boundaries, but a few fixed values
  do not replace a generator for the wider domain.
- **Failure signals:** separate unrelated contracts that need different diagnosis
  or shrinking. Keep complementary assertions together when they establish one
  property, such as sortedness plus permutation preservation.
- **Exactness:** keep equality, ordering, hashing, documented exact roundtrips,
  and endpoint laws exact. Use approximate comparisons only where the contract
  permits error, with a justified tolerance. A tolerance widened after a failure
  needs contract evidence, not an explanation that floating point is imprecise.
- **Failure history:** account for every observed counterexample. Do not silently
  delete assertions, ignore tests, add `should_panic`, or narrow inputs to hide a
  bug. A panic expectation is legitimate only when that is the required behavior.
- **Budget and replay:** choose case counts and time limits for the cost and input
  space; neither a small count nor a disabled per-case deadline is inherently
  wrong. Preserve seeds or concrete failing inputs and check that cases execute
  through the intended test route. An ignored or skipped test is not a pass.

For regression/valid-change probes, executed input-class evidence, isolation, and
suite reachability, follow [design-for-change's testing rules](../../design-for-change/SKILL.md#design-for-testing).
For a failure whose meaning is unclear, read
[interpreting-failures.md](interpreting-failures.md).

## Determinism is conditional

`result == result` cannot constrain the implementation. Repeated calls to `f(x)`
can establish determinism when nondeterminism is a realistic regression: hashing,
iteration order, serialization hooks, or clocks may affect the result. For an
obviously pure function, repeated equality is usually redundant. State what could
make the two calls differ before calling this a useful property.
