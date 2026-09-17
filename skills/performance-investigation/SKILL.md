---
name: performance-investigation
description: Diagnose performance regressions, hangs, unexpectedly slow commands, and quota-bound external operations. Use for profiling or benchmarking commands, tests, builds, CI, startup, configuration reload, APIs, cloud queries, or remote acquisition when execution is slow, silent, rate-limited, concurrency-sensitive, or requires defensible performance evidence. Do not use merely because edited code is performance-sensitive.
---

# Performance Investigation

Before editing, record the baseline command, environment, metric, narrowest representative workload, elapsed time, and whether the run is cold or warm. Reproduce the user's actual command resolution; the agent's inherited shell may differ. Prior baselines are useful when environment differences are named, but precise comparisons require same-machine before/after measurements.

## Diagnose boundedly

When a command exceeds its expected duration or remains unexpectedly silent for 30 seconds:

1. Record elapsed time, output so far, and the process tree. Use shell timestamps when no portable timing tool exists, and keep logs and stack samples under `target/` or temporary storage.
2. Capture descendants recursively and, when children are short-lived, repeatedly. Identify the active child operation rather than attributing its time to the outer command.
3. Classify the active phase as CPU-bound, I/O-bound, blocked, sleeping, or waiting on a child.
4. For JVM work, take a thread dump; for other runtimes, use a bounded stack or syscall sample.
5. Separate launcher setup, dependency resolution, discovery/loading, execution, reporting, and shutdown.
6. Stop once the sample answers the current question. If terminating a wrapper, clean up only descendants created by that invocation; preserve shared daemons and pre-existing workers.

Completion-only profilers cannot diagnose hangs. Locate the expensive phase with bounded samples before running a representative completion run.

## Improve the measured boundary

Look first for repeated process startup, duplicate runtime loading, overly broad dependency or source scope, unnecessary freshness checks, uncached generated work, and metadata-heavy filesystem traffic. Use temporary local storage for disposable intermediates only when measurement shows significant filesystem overhead.

When one process waits on another, determine whether it can perform the work directly before proposing a persistent daemon. For runtime-configuration regressions, inspect effective state, reload idempotence, hidden callbacks, and subprocesses.

## External and quota-bound benchmarks

Use this procedure when the measured system is an API, cloud query, remote archive, registry, or other service where points, requests, bytes, reset windows, throttling, or server-side execution constrain throughput.

1. Define the measured contract before running: exact query or request shape, production fields and pagination paths included, sample authority, cold/warm state, credential class, quota window, concurrency, retries, and required finalization.
2. Make the runner write the final evidence artifact directly. Record the script or query hash, configuration hash, sample identifiers, start/end timestamps, provider request IDs when available, environment, raw per-request measurements, incomplete work, and projection formula. Do not manually transcribe totals into a second report.
3. Keep provider limits separate: primary quota consumed, reset waits, secondary throttles, concurrency caps, server CPU/time, response bytes, retries, and wall time. Concurrency may reduce latency without reducing quota cost.
4. Compare batch sizes or concurrency sequentially against the same workload. Randomize or alternate order when provider load or cache state could bias later runs. Stop increasing concurrency after throttling, timeout growth, or a worse completed-throughput result.
5. Exercise every overflow or continuation path required by the claimed contract. A first-page or query-shape probe cannot establish end-to-end cost when production requires additional fields, pagination, storage writes, normalization, or artifact finalization.
6. Classify the output precisely:
   - *Query-shape probe:* one request design's fields, cost, size, and failure behavior.
   - *Batching probe:* batch/concurrency behavior for the declared sample.
   - *Cold end-to-end benchmark:* all required phases from named empty caches through finalization.
   - *Population projection:* an explicit extrapolation from measurements to a larger workload.
7. Label projections as a *representative estimate*, *conservative bound*, *lower bound*, *upper bound*, or *planning datum only*. Bounds require a sampling model and calculation proving their direction. Convenience, adversarial, or deliberately skewed samples are planning data unless weighted against the population.
8. Treat quota resets and provider variability as part of literal elapsed time. A quota-capacity calculation is not an elapsed-time minimum unless starting balance, reset boundaries, retry behavior, and secondary limits support that claim.

Stop when the cheapest measurement settles the decision. Do not spend quota to improve precision that cannot change the selected design.

## Verify

Before comparing timings, verify that the optimization is active using runtime evidence and a negative control. Do not infer activation from configuration alone: in Node, even `NODE_DISABLE_COMPILE_CACHE=0` disables the compile cache.

Measure the changed phase and the full user command. Preserve correctness checks, compare cold and warm results on the same machine, and repeat runs when variance could change the conclusion. Report missing tools and other environmental failures separately from performance results. Confirm the optimization did not merely move work into an unmeasured phase.

When controllable, instrument opaque subprocesses with phase timing; an enclosing test or CI-job duration is insufficient attribution. Completion requires the consumer-visible evidence artifact, not terminal output or a handwritten summary.
