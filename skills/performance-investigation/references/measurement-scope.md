# Measurement scope and isolation

Choose what to count and which concurrent work would confound it, then stop.
Consulting this reference alone starts no benchmark, diagnosis, baseline, evidence collection, or serialization.
Actual measurements retain the skill's [baseline](../SKILL.md#choose-the-question-and-boundary) and [evidence requirements](../SKILL.md#preserve-evidence).

## Measure where production calls

Does production start a fresh process or use an initialized caller?
Measure added overhead at that call site and full-command latency separately.
A standalone helper including runtime or dependency loading measures startup-inclusive cost, not incremental overhead in an initialized caller.

## Make counts comparable

State whether process counts include direct launches or all descendants, and whether they include threads.
Label timings inclusive or exclusive; never sum overlapping parent/child durations or compare differently scoped counts.

## Choose isolation for the claim

Keep profiled attribution separate from unprofiled timing comparisons.
Instrumentation overhead varies by operation, so traced time shares do not establish unprofiled savings.
Attribution need not provide controlled before/after precision; comparisons need comparable conditions.
Hold only concurrent work that would confound the required attribution or comparison.
