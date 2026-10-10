# Generating Property-Based Tests

Writing the `@given` decorator is the easy part. These are the decisions that make
the difference between a suite that finds bugs and one that just runs.

## Put constraints in the strategy, not in `assume()`

This is the single highest-value habit. `assume()` discards inputs after generation,
so a filter that rejects most candidates wastes the budget and can trigger
Hypothesis's failing health check for excessive filtering.

```python
# Slow, and mostly discards
@given(st.integers())
def test_positive(x):
    assume(x > 0)
    ...

# Generates only what you want
@given(st.integers(min_value=1))
def test_positive(x):
    ...
```

Reserve `assume()` for conditions you genuinely cannot express as a generator — a
relationship between two already-generated values, usually.

Build compound inputs with `st.builds`, and derive dependent fields with
`st.composite` or `.flatmap` rather than generating independently and filtering:

```python
@st.composite
def sized_list_and_index(draw):
    xs = draw(st.lists(st.integers(), min_size=1))
    i = draw(st.integers(min_value=0, max_value=len(xs) - 1))
    return xs, i
```

## Pin the edge cases you already know about

Random generation finds boundaries eventually; `@example` finds them on every run and
documents that you thought about them.

```python
@given(st.lists(st.integers()))
@example([])
@example([1])
@example([1, 1, 1])
def test_sort(xs): ...
```

Empty, single-element, all-duplicates, zero, negative, and the maximum representable
value are the ones that recur.

## Settings

Choose settings for the input space, per-case cost, and execution environment.
These are illustrative profiles, not required case counts:

```python
@settings(max_examples=10)                      # local iteration
@settings(max_examples=200)                     # CI
@settings(max_examples=1000, deadline=None)     # nightly
```

For variable-cost integration work, disabling a per-case deadline can avoid
machine-dependent failures; retain an outer timeout or another execution budget.
Do not disable a contractual performance bound just to make a slow test pass.
For required input-class evidence and failing-input replay, follow
[design-for-change](../../design-for-change/SKILL.md#design-for-testing).

## Determinism as a property

`f(x) == f(x)` is a tautology for a pure function and a real test for anything else.
Serializers over dicts or sets, anything involving hashing, iteration order, or time —
those can and do return different output for the same input. Assert it where a broken
implementation could falsify it, and not otherwise.

## Testing the error path

`st.binary()` against a decoder is worth writing: the contract is usually "raises
`DecodeError` or succeeds, never `IndexError`, never hangs". Catch only the documented
exception and let everything else fail the test.
