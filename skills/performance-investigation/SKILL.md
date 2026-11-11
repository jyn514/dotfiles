---
name: performance-investigation
description: Diagnose unexpected execution delay, hangs, observed contention, and quota-constrained operations, or perform explicitly requested profiling and benchmarking. Use for commands, tests, builds, CI, startup, configuration reload, APIs, cloud queries, or remote acquisition when one of those conditions requires investigation. Do not load for missing, late, or out-of-order UI updates alone; first use ordinary correctness debugging to check event delivery, parsing, and rendering. Slow execution or blocked rendering on that path does trigger it. Expected execution, silence alone, concurrent execution, and performance-sensitive code do not trigger it.
---

# Performance investigation

Choose a measurement that can settle the performance decision, then stop when it does.
An unexpectedly stalled build needs investigation; a quiet build progressing within its expected duration does not.

## Choose the question and boundary

Name the decision and the least attribution detail it needs before choosing tools.
Choose diagnostic windows and observation points to answer the question within user limits and preservation requirements.
For example, relax a self-imposed ten-second window when an existing profiler needs longer to answer it.
Use existing evidence or the cheapest viability check to select an existing tool.
Add custom instrumentation only for a required answer existing tools demonstrably cannot supply.

For whole-command latency, build a phase-time budget accounting for overlap.
Estimate the maximum end-to-end benefit before pursuing a local optimization.
Use [measurement scope and isolation](references/measurement-scope.md) to choose call-site, counting, timing, and attribution boundaries and necessary isolation.

Before editing, record the baseline command, environment, metric, narrowest representative workload, elapsed time, and cold/warm state.
Reproduce the user's command resolution; your inherited shell may differ.
Name environment differences when reusing baselines; precise before/after comparisons require the same machine.

## Preserve evidence

Before measuring, choose storage that survives session/environment resets and benchmark cleanup.
Save exact runner, query, and analysis sources with raw per-run results, preserving each run's source version.
Hashes or terminal output cannot reconstruct lost sources.
Keep disposable build outputs separate; verify retained evidence can reproduce reported measurements before cleanup.

Keep captured tests outside the measured workload through runner discovery roots or exclusions.
Check discovery: Git-ignored files may still run.
Archives or non-test suffixes are fallbacks; preserve original paths and bytes for reconstruction.

## Locate the active work

When a command exceeds its expected duration or stays unexpectedly silent for 30 seconds:

1. Save elapsed time, output, and process trees in the evidence directory; shell timestamps suffice without a portable timing tool.
2. Capture descendants recursively, repeatedly for short-lived children, to identify the active operation.
3. Classify it as CPU-bound, I/O-bound, blocked, sleeping, or waiting on a child.
   Separate setup, dependency resolution, discovery/loading, execution, reporting, and shutdown.
4. For a hang, take a JVM thread dump or bounded stack/syscall sample for other runtimes before attempting a completion run.
   Save diagnostic logs and samples in the evidence directory.
5. Stop when the sample answers the question.
   If terminating a wrapper, clean up only its invocation's descendants; preserve shared daemons and pre-existing workers.

For progressing CPU-heavy work, prefer an existing profiler over sampling hooks.
Completion-only profiling suits work that finishes or safely unwinds on timeout, not a hang.
Check whether relevant stop conditions and user limits let it save results; name conditions that lose them.
When controllable, add phase timing inside opaque subprocesses: enclosing test or CI duration cannot attribute their cost.

## Choose an improvement

Use the budget to find avoidable work: repeated startup/loading, excessive dependency or source scope, redundant freshness checks, uncached generation, or metadata-heavy filesystem traffic.
Use temporary local storage for disposable intermediates only when measured filesystem overhead warrants it.

Before optimizing subprocess calls or adding a daemon, check whether an existing runtime's supported API can remove the boundary.
Compare moving work into that runtime before introducing quoting, framing, or parsing to consolidate calls.
For configuration regressions, inspect effective state, reload idempotence, hidden callbacks, and subprocesses.
After a meaningful improvement, refresh the budget and rank remaining costs rather than following yesterday's bottleneck.

## Measure external and quota-bound work

For APIs, cloud queries, archives, or registries, define the contract before spending quota:
request shape, production fields and pagination, sample authority, cache state, credential class, quota window, concurrency, retries, and finalization.

Have the runner write the final evidence artifact directly, including source/query and configuration hashes, sample IDs, start/end timestamps, provider request IDs when available, environment, raw per-request measurements, incomplete work, and projection formula.
Do not transcribe totals into another report.

Keep quota consumption, reset waits, secondary throttles, concurrency caps, server CPU/time, bytes, retries, and wall time separate.
Concurrency can reduce latency without reducing quota cost.
Compare batch sizes or concurrency sequentially on the same workload; alternate or randomize order when load or caches could bias results.
Stop increasing concurrency when throttling, timeouts, or completed throughput worsen.

Exercise every overflow or continuation path required by the claim.
A first-page request establishes query shape, not end-to-end cost through pagination, storage, normalization, and artifact finalization.
Match the claim to the completed work:

- **Query-shape probe:** one request's fields, cost, size, and failures.
- **Batching probe:** batch/concurrency behavior for the declared sample.
- **Cold end-to-end benchmark:** all required phases from named empty caches through finalization.
- **Population projection:** explicit extrapolation to a larger workload.

Label projections representative estimates, conservative/lower/upper bounds, or planning data only.
Bounds need a sampling model and calculation proving their direction.
Convenience, adversarial, or skewed samples remain planning data unless weighted against the population.
Include resets and provider variability in literal elapsed time.
Quota capacity establishes no elapsed-time minimum without supporting starting balance, reset boundaries, retry behavior, and secondary limits.
Stop spending quota when more precision cannot change the decision.

## Verify the result

Verify activation with runtime evidence and a negative control before comparing timings.
Configuration alone is insufficient: Node's `NODE_DISABLE_COMPILE_CACHE=0` still disables the compile cache.

Measure both the changed phase and the full user command, including artifact finalization, to detect work moved outside the timer.
Preserve correctness checks and compare cold/warm results on the same machine.
For toolchain comparisons, alternate sequential trials on the real workload and exclude setup runs with unequal cache state.
Repeat when variance could change the conclusion; report environmental failures separately.
Finish with the consumer-visible evidence artifact, not terminal output or a handwritten summary.
