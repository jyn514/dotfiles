# Investigate surviving mutations

Read this when a campaign produces survivors or when analyzing supplied results.
Inspect the exact change, original code, callers, contracts, and responsible tests
before assigning a conclusion. Rank work by the affected behavior, not the mutation
engine's severity label. A low-ranked arithmetic mutation at a critical boundary can
matter more than a high-ranked change to a log message.

## Is the result usable?

Confirm that the selected tests executed against the changed implementation. Trace
rebuilds, generated artifacts, imports, installed code, and subprocess entrypoints.
If that path is unverified, retain an execution gap rather than call the mutation
equivalent or blame an assertion. Absence from coverage data is not proof of dead code.

Both true and false replacements surviving a condition can mean that its path never
executes, that assertions miss the difference, or that the condition is redundant.
Inspect the path and outcomes to distinguish them.

## Find a distinguishing case

State the behavior that differs between the original and mutated program. Try the
smallest input or action sequence that should expose it. Check reachable boundaries,
empty and malformed inputs, Unicode byte lengths, error paths, and state transitions
only where they affect the contract. Use the appropriate consumer: output comparisons
for a CLI, native decoding for an encoder, and disposable filesystem or store fixtures
for effects.

A temporary probe must pass on the original implementation and fail on the mutation
for the intended assertion or observed effect. Keep the original test suite's result
separate from the probe's result. A helper that recomputes the changed logic is not an
independent expectation; neither is regenerating an expected snapshot from the mutant.

Examples:

- Removing an empty-value rejection needs both a rejected empty input and an accepted
  nonempty input. Do not fix it with a test that rejects every input.
- Omitting a field from a decision hash needs inputs differing only in that
  contract-significant field, plus an assertion that their identities differ.
- Changing a record byte limit needs the accepted boundary and rejected next byte;
  multibyte text can distinguish byte length from character count.
- Removing CLI output needs a successful command invocation with expected output,
  not only direct tests of the renderer or command-failure tests.

## Establish equivalence, or leave it unresolved

An equivalent mutation has no observable difference within the declared contract and
supported input/environment domain. Inspect types, reachability, side effects, and
how the value is consumed. Passing examples alone cannot prove equivalence. Code
unreached by current tests is not necessarily unreachable in supported use.

Try a distinguishing case, then give the argument that rules out differences. For
example, changing unsigned `x > 0` to `x != 0` is equivalent only if obtaining `x`
has the same effects and no other behavior changes. Removing a final whitespace
trim can be equivalent when earlier operations guarantee the same trimming; inspect
those operations rather than assume it.

A changed boundary is not equivalent unless equality is unreachable. A removed
publication, diagnostic, or cleanup effect is not equivalent merely because the
returned value stays the same. Include externally observed effects required by the
contract. Do not classify undefined-behavior-introducing changes as equivalent based
on matching outputs under one compiler.

## Conclude each investigated survivor

- **Demonstrated test gap:** record the contract, mutation, responsible tests, passing
  original-suite result, and distinguishing probe. Recommend the missing case or
  assertion; do not label the original code buggy without independent evidence.
- **Equivalent:** record the bounded domain and semantic argument, including relevant
  side effects and consumers.
- **Unresolved:** name the missing provenance, uncertain contract, reachability, or
  distinguishing evidence. A suspicion is not a confirmed gap.

Stop at the campaign's agreed budget. Account for unexamined survivors rather than
implying they were cleared. Permanent repairs and wider bug searches require their
own scope and authority.
