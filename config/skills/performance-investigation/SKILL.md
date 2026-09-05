---
name: performance-investigation
description: Diagnose performance regressions, hangs, or unexpectedly slow commands, tests, builds, CI jobs, startup, shell initialization, command resolution, and configuration reload. Use for profiling or benchmarking when execution exceeds its expected duration, remains unexpectedly silent, spends time in child processes or repeated initialization work, or a change requires performance measurement. Do not use merely because edited code is performance-sensitive.
---

# Performance Investigation

Before editing, record the baseline command, environment, metric, narrowest representative workload, elapsed time, and whether the run was cold or warm. Reproduce the user's actual command resolution; the agent's inherited shell may differ. Prior baselines are useful when environment differences are named, but precise comparisons require same-machine before/after measurements.

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

## Verify

Measure the changed phase and the full user command. Preserve correctness checks, compare cold and warm results on the same machine, and repeat runs when variance could change the conclusion. Report missing tools and other environmental failures separately from performance results. Confirm the optimization did not merely move work into an unmeasured phase.

When controllable, instrument opaque subprocesses with phase timing; an enclosing test or CI-job duration is not sufficient attribution.
