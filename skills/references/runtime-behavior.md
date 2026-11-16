# Runtime behavior

Read when changing traversal, worklists, arithmetic, threads, callbacks, queues, concurrency, cancellation, or execution restrictions.

## Bound stack and deferred work

For traversal or worklists whose input depth or frontier can grow without a small enforced bound, avoid unbounded call-stack or deferred-evaluation depth.
An iterative loop is not enough if each iteration wraps the remaining work in another lazy concatenation or callback chain.
Use an explicit stack or queue that does not accumulate nested evaluation; represent enter/exit work explicitly when post-order results are needed.
Recursion can be appropriate when a small maximum depth is enforced at the input boundary or the runtime guarantees bounded stack use for that form.

Test the dangerous dimension: a deep chain exercises recursive depth, while a wide frontier exercises accumulated worklist nesting.
Choose a regression size that exposes the former failure in the supported CI runtime without relying on the local machine's stack size.
For example, in Clojure, repeatedly replacing a frontier with `(concat (next frontier) new-items)` can accumulate lazy `Concat` nesting despite `loop`/`recur`.
An explicit persistent stack or queue avoids that nesting.
The same check applies to deferred chains in other runtimes, not just Clojure sequences.

## Preserve context at asynchronous handoffs

When adding a thread, task, callback, or queue handoff, identify the execution context required by downstream work.
Capture request identity, tracing, diagnostic provenance, or other required context explicitly or with the runtime's supported propagation mechanism.
Do not assume thread-local or dynamically bound values cross the handoff.
For example, a worker may complete successfully yet lose the source root needed to render an exception's file snippet.
Check the worker's error path as well as its result and preserve ownership after cancellation as required by the contract.

## Concurrency safety

Trace an interleaving of competing writers or delayed results, including reentrant callbacks and observations stale before commit.
Apply ownership, publication, and lifecycle contracts at every mutation entry point so an old result cannot overwrite a newer owner's state.
Completion without deadlock does not establish correctness.

## Runtime progress

Trace waits and their enabling transitions, including held locks, admission slots, bounded queues, and reentrant callbacks.
Check cycles, starvation, retries without progress, and cancellation or shutdown waiting on work they must release.
Distinguish slow external work from an unresolvable cycle.

A callback cannot await persistence if persistence needs that callback to return.
Retries need a changed condition, wake-up source, or finite stopping rule.
A timeout alone does not establish that a circular wait is resolved; include resulting partial effects in the recovery contract.

## Resource bounds

Identify what drives latency, memory, outstanding work, handles, and external cost.
Trace amplification, such as concurrency × retained bytes or fan-out × retries.
Establish required bounds, capacity behavior, and release on cancellation and cleanup.
Use known workloads or bounded estimates; measure when it can change the design rather than automatically adding benchmarks, caches, queues, or configurable limits.

## Optimization and caching

Before optimizing or caching an operation, check whether the operation or intermediate representation can be eliminated.
For cache keys, reuse, or invalidation changes, apply [Reuse and invalidation](data-and-effects.md#reuse-and-invalidation) to data, diagnostics, errors, and refresh signals.

## Check numerical calculations

When calculating with offsets, positions, or timestamps, identify their units and origins, distinguishing coordinates from lengths or durations.
Bring coordinates to a common frame where the operation requires it; matching units alone do not establish matching origins.
For example, compare an offset relative to a section's start with that section's length, not with its cumulative end.

When choosing or rearranging a numerical calculation, check intermediate operations over the accepted input range.
Algebraic equivalence does not establish equivalent behavior in the implementation's arithmetic.
Trace cases where overflow, underflow, or cancellation could violate a required result or downstream decision.
Choose the smallest formulation that preserves the contract.
Do not narrow accepted inputs, clamp results, or widen tolerances merely to hide a failure.
Non-finite intermediates or rounding differences are not defects by themselves when the required behavior remains valid.

## Restricted execution contexts

When an execution context already forbids allocation, blocking, or another operation, apply that restriction to the complete path.
Include error handling, cleanup, indirect helpers, and first-use initialization.
Check that a path intended to avoid forbidden work makes its decision before invoking helpers that can perform that work.
Do not impose the same restrictions on ordinary contexts without a requirement.

[Rust's panic repair](https://github.com/rust-lang/rust/pull/102460) moves the abort-only check before the thread-local counter access.
The previous path accessed that counter before checking the mode; its first-use initialization could allocate in the restricted child process.
