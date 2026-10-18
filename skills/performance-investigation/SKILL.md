---
name: performance-investigation
description: Diagnose unexpected delay, hangs, observed contention, and quota-constrained operations, or perform explicitly requested profiling and benchmarking. Use for commands, tests, builds, CI, startup, configuration reload, APIs, cloud queries, or remote acquisition when one of those conditions requires investigation. Do not load merely because a command is silent, runs concurrently, or edits performance-sensitive code; expected execution and ordinary correctness debugging do not trigger this skill.
---

# Performance Investigation

Establish the unexpected delay, observed contention, quota constraint, or requested measurement before starting. An unexpectedly stalled build triggers this skill; a quiet build progressing within its expected duration does not.

Before editing, record the baseline command, environment, metric, narrowest representative workload, elapsed time, and whether the run is cold or warm. Reproduce the user's actual command resolution; the agent's inherited shell may differ. Prior baselines are useful when environment differences are named, but precise comparisons require same-machine before/after measurements.

## Preserve evidence

Before the first measurement, choose an evidence directory that survives session/environment resets and benchmark cleanup. Save exact runner, query, and analysis sources alongside raw per-run results there, preserving the source version for each run. Temporary copies, terminal output, or hashes alone cannot recover lost evidence.

Prefer the runner's discovery roots or exclusions to keep captured test sources outside the measured workload.
Do not assume Git-ignored directories are excluded; check the runner's discovery behavior.
Use archives or non-test suffixes only as a fallback, preserving original paths and file bytes for reconstruction.

Keep disposable build outputs separate from evidence. Before cleanup, verify that retained sources and raw results suffice to recompute reported measurements.

## Choose the simplest measurement

Before choosing tools, name the question, the decision it informs, and the least attribution detail sufficient to decide.
Separate user limits and preservation requirements from diagnostic choices, such as sampling windows and observation points.
Do not reject an alternative because it cannot satisfy conditions needed only by the current diagnostic.

For whole-command latency, start with a phase-time budget; account for overlap rather than adding concurrent phases.
Estimate the maximum end-to-end benefit before pursuing a local optimization.
After meaningful improvements, refresh the budget and rank the remaining avoidable costs rather than following the previous bottleneck.

Distinguish a progressing, CPU-heavy computation from a hang.
For a progressing computation, prefer an existing profiler that can answer the question over sampling hooks or custom telemetry.
Use existing evidence or the cheapest viability check; do not require an expensive profiling run just to rule out a tool.
Completion-only profiling cannot diagnose a hang, but may capture a computation that completes or safely unwinds on timeout.
Check the output path under relevant stop conditions and user limits; name conditions that can lose results.
State whether subprocess counts cover direct launches or all descendants, and whether threads are included.
Label timings as inclusive or exclusive.
Do not sum overlapping parent/child durations or report reductions between differently scoped counts.
Keep profiled attribution separate from unprofiled timing benchmarks.
Do not convert traced time shares into unprofiled savings; instrumentation overhead can differ by operation.
Before adding custom instrumentation, identify the required answer an existing tool cannot provide and the evidence of that limitation.

## Diagnose boundedly

When a command exceeds its expected duration or remains unexpectedly silent for 30 seconds:

1. Record elapsed time, output so far, and the process tree. Use shell timestamps when no portable timing tool exists, and retain diagnostic logs and stack samples in the evidence directory.
2. Capture descendants recursively and, when children are short-lived, repeatedly. Identify the active child operation rather than attributing its time to the outer command.
3. Classify the active phase as CPU-bound, I/O-bound, blocked, sleeping, or waiting on a child.
4. For hangs, take a JVM thread dump or a bounded stack or syscall sample for other runtimes.
5. Separate launcher setup, dependency resolution, discovery/loading, execution, reporting, and shutdown.
6. Stop once the sample answers the current question. If terminating a wrapper, clean up only descendants created by that invocation; preserve shared daemons and pre-existing workers.

For a hang, locate the active phase with bounded samples before attempting a representative completion run.

## Improve the measured boundary

Look first for repeated process startup, duplicate runtime loading, overly broad dependency or source scope, unnecessary freshness checks, uncached generated work, and metadata-heavy filesystem traffic. Use temporary local storage for disposable intermediates only when measurement shows significant filesystem overhead.

Before optimizing subprocess calls or adding a daemon, check whether an existing runtime and supported API can remove the boundary.
If consolidation needs new quoting, framing, or parsing, compare moving the work into that runtime before adding another representation.
For runtime-configuration regressions, inspect effective state, reload idempotence, hidden callbacks, and subprocesses.

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

When comparing toolchains, alternate sequential trials on the real workload, include artifact finalization, and exclude setup runs with unequal cache state.

Measure the changed phase and the full user command. Preserve correctness checks, compare cold and warm results on the same machine, and repeat runs when variance could change the conclusion. Report missing tools and other environmental failures separately from performance results. Confirm the optimization did not merely move work into an unmeasured phase.

When controllable, instrument opaque subprocesses with phase timing; an enclosing test or CI-job duration is insufficient attribution. Completion requires the consumer-visible evidence artifact, not terminal output or a handwritten summary.
