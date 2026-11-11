# Investigate surviving mutations

Read this for campaign survivors or supplied results.
Inspect the exact change, original code, callers, contracts, and responsible tests.
Prioritize affected behavior over engine severity: arithmetic at a critical boundary can matter more than a highly ranked log-message change.

## Establish what survived

Confirm that tests executed against the changed implementation through rebuilds, generated artifacts, imports, installed code, and subprocesses as applicable.
An unverified path remains an execution gap, not equivalence or an assertion failure.
Coverage absence does not prove dead code.

If both true and false replacements survive a condition, distinguish an unexecuted path, assertions that miss the difference, and a redundant condition by inspecting execution and outcomes.

## Find a distinguishing case

State the observable difference between original and mutant, then try the smallest input or action sequence that should expose it.
Choose contract-relevant boundaries, malformed inputs, error paths, or state transitions.
Use the real consumer: CLI output, native decoding, or disposable filesystem/store fixtures for effects.

A temporary probe must pass on the original and fail on the mutant for the intended assertion or effect.
Keep its result separate from the original suite's result.
Use an independent expectation, not a helper recomputing the mutated logic or a snapshot regenerated from the mutant.

- **Empty-value rejection:** pair rejected empty input with accepted nonempty input, so rejecting everything cannot pass.
- **Decision hash:** vary inputs only in the omitted, contract-significant field and assert that identities differ.
- **Record byte limit:** test the accepted boundary and rejected next byte; multibyte text distinguishes byte length from character count.
- **CLI output:** invoke a successful command and assert its output; renderer-only and command-failure tests miss publication.

## Establish equivalence or leave it unresolved

Equivalence means no observable difference within the declared contract and supported input/environment domain.
Try a distinguishing case, then explain why differences are ruled out by types, reachability, effects, and consumers.
Passing examples alone are insufficient; untested code may still be reachable in supported use.

Unsigned `x > 0` and `x != 0` are equivalent only if obtaining `x` has the same effects and nothing else changes.
Removing a final whitespace trim can be equivalent if earlier operations guarantee that trimming; inspect them.
A boundary change is equivalent only if equality is unreachable.
Unchanged return values do not establish equivalence when publication, diagnostics, or cleanup changes.
Matching outputs under one compiler do not justify equivalence for a mutation introducing undefined behavior.

## Record the conclusion

- **Demonstrated test gap:** record the contract, mutation, responsible tests, passing original-suite result, and distinguishing probe; recommend the missing case or assertion.
  The introduced defect does not establish a bug in the original code.
- **Equivalent:** record the bounded domain and semantic argument, including relevant effects and consumers.
- **Unresolved:** name missing provenance, uncertain contract, reachability, or distinguishing evidence.

Stop at the agreed budget and account for unexamined survivors.
Permanent repairs and wider bug searches need their own scope and authority.
