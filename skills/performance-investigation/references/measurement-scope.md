# Measurement scope and isolation

Use this check to choose what a measurement includes or decide which concurrent work would confound it.
Stop when the required scope and isolation are clear.
Consulting this reference does not start a benchmark, require a fresh baseline or evidence artifacts, launch diagnosis, or serialize unrelated work.
Actual measurements remain subject to performance-investigation's applicable [baseline](../SKILL.md) and [evidence-preservation requirements](../SKILL.md#preserve-evidence); this check does not waive them.

## Match the measured boundary to the question

Before measuring an operation, establish how production invokes it: in a fresh process or inside an already-initialized caller.
For added latency or overhead, measure at that production call site; do not charge the operation for initialization the caller already performs.
Measure full-command latency separately.
A standalone helper benchmark that includes runtime or dependency loading measures startup-inclusive cost, not incremental overhead.

## State what counts and overlaps

State whether subprocess counts cover direct launches or all descendants, and whether threads are included.
Label timings as inclusive or exclusive.
Do not sum overlapping parent/child durations or report reductions between differently scoped counts.

## Separate attribution from timing comparisons

Keep profiled attribution separate from unprofiled timing benchmarks.
Do not convert traced time shares into unprofiled savings; instrumentation overhead can differ by operation.

Choose isolation for the claim being made.
Attribution does not automatically require controlled before/after precision; controlled comparisons need comparable measurement conditions.
Hold only concurrent work that would confound the required attribution or comparison, not unrelated work merely because a measurement is planned.
