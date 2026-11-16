# Data and effects

Read when changing records, options, configuration, mutable state, environment access, collaborators, validation, or equality.

## Single authority

Similar names or currently equal values do not establish that two concepts are the same state.
Before unifying them, identify what each means, who owns it, and which events may change it.
If they can legitimately differ, preserve that distinction and test a case where they do.

When the same value appears across multiple consumers, choose one authoritative representation and derive the others from it.
Consumers should refer to stable roles or interfaces rather than repeat filenames, paths, commands, identifiers, defaults, or other change-prone constants.

Add a regression test showing that changing the authority updates consumers without corresponding edits.
For persisted representations, include independent readers such as launchers and discovery commands, and test their agreement on mixed old/new records.

Tests and test doubles are consumers too.
Do not duplicate real configuration values in fixtures or assertions.
For configuration wiring, set a synthetic, non-default value at the authority and assert that it reaches the consuming boundary.
Changing real configuration must not require corresponding test edits.

Keep independent expected values for behavioral and protocol requirements.
Do not make assertions tautological by deriving the expected result from the implementation being tested.

Verify propagation at the application's supported reload or restart boundary.
This does not require hot reload or new runtime configurability solely for testing.

## Represent shared data precisely

- Represent data precisely.
  Avoid overloaded representations and in-band signalling unless an abstraction contains the unsafety.
- Parse, don't validate: centralize checks in a structured domain model.
  Treat stringly typed structured data as suspect; fix the model instead of overloading meanings.
- Make invalid states unrepresentable when language tools can do so without poor ergonomics, such as needless singleton types.
- Choose the strongest cheap enforcement mechanism for the named invariant: types, compiler or lint rules, regression tests, static checks, runtime assertions, or benchmarks.

Keep shared types, schemas, or documented record shapes with the contract owner and reuse them across producers, adapters, and tests.
Do not copy field lists into competing definitions.
A runtime schema is not required for every map; choose the representation and enforcement the contract needs.

When optional data controls defaults, validation, effects, or output accounting, identify its exact absence representation.
Check every consumer against valid values such as `false`, `0`, and an empty string.
A default for absent configuration must not replace a configured `false` merely because the language treats it as falsey.

## Forward records; narrow dependencies

Pass an established record unchanged when a caller only forwards it and the callee uses that contract.
Do not unpack it merely to rebuild the same keys for the next function.
Narrow it where values are used, shape is validated, ownership changes, or fields are deliberately dropped for soundness.

Do not turn this into a universal application context that every function can inspect.
Give leaf helpers the values or capabilities they use, such as a filesystem reader, page lookup, diagnostics sink, clock, or process runner.
Broader assembly objects can belong at orchestration boundaries.
For example, an adapter forwards a request record intact, while a renderer receives its page lookup rather than credentials and process execution.

## Own effects and environment access

Prefer pure transformations over hidden mutation.
Keep real runtime state with the owner of the cache, queue, process, watcher, or other effect; do not add mutable state merely to avoid returning a value.
Make outside-world dependencies visible at the owning boundary and keep core calculations callable with deterministic inputs.
Use existing options, functions, or narrow capabilities when needed; do not require a new protocol or injected collaborator for every helper.

Resolve application-specific environment configuration in the application adapter and pass the resolved values into reusable code.
A library may deliberately own a documented environment convention, with an explicit override when deterministic callers need one.
For example, a presentation library can honor `NO_COLOR` without making application-specific configuration part of its public API.

## Validate before protected effects

Trace enforcement through supported entrypoints and every intervening validator or normalizer.
Distinguish reachable caller behavior, values rejected earlier, and defensive fallback code; a direct downstream call alone does not establish reachability.

When preparation failure must leave state unchanged, validate and finish fallible preparation before the first protected effect in the owning orchestration path.
Inspect work deferred into execution, including serialization, encoding, and resolution.
For example, a plan that serializes its second output only after writing the first can still fail after mutation.
Prepare both outputs before publication if the contract promises no writes on preparation failure.
Trace the full operation rather than treating a no-write helper test as evidence for it.
Streaming and partial-progress contracts need their declared [failure and recovery behavior](failures-and-recovery.md#partial-failure-and-recovery), not an invented all-or-nothing guarantee.

## Reuse and invalidation

Construct a relevant change that keeps a proposed key or comparison equal but could change a required observation.
Follow every consumer whose work equality suppresses, including helpers, diagnostics, and errors.
Check both its data and the signal that makes it run; complete upstream data cannot refresh a cached consumer alone.

For example, moving an unchanged broken link can leave HTML equal but move a warning's source location.
An HTML-only dependency can retain the old warning location.
Reusing emitted bytes can be correct while reusing the warning is not.
Keep a refresh path through the full dependency, a source-location update, or conservative invalidation.
Inspect helpers and errors before calling a consumer content-only.

When equivalence is unproven, preserve distinctions or invalidate conservatively.
Finer projections are optional; additional comparison machinery needs workload evidence that saved work earns its cost.

## Trust and authority

Trace untrusted data to protected effects, including bypass paths and sensitive diagnostics or persisted data.
Name the authorizing caller and enforcing component; privileges do not authorize every request.
Choose controls for that crossing, not a new authentication subsystem for every helper.
