# Testing examples: required populations and cancellation results

Read the relevant example when a report may omit required items, or a cancellation result controls the caller's next action.
These cases illustrate existing [testing guidance](testing.md), not new acceptance requirements for every project.

## Coverage and required populations

In [Precise, consistent, and reliable code coverage][coverage-talk], the apparently better 99.5% report omitted executable functions.
The percentage alone could not distinguish better testing from a smaller reported population.
The account compares coverage with a separate certified-function inventory instead of letting the profiler define the required population.
That inventory comes from certification attributes collected after macro expansion, independently of which functions appear in the profiling data.

The comparison adds an "ignored" category alongside tested, partially tested, and untested functions.
It makes missing entries visible without automatically treating every omission as a test failure.
For example, `Infallible::clone` can legitimately have no generated body because no valid receiver exists.
The mismatch needs an explanation, not a blanket requirement to execute every declared function.

For a similar reporting system, a useful regression would remove a required item from the observed data and check that the report exposes the discrepancy.
A valid exclusion should remain possible when the governing requirements justify it.
Derive the required population independently of the discovery or filtering stage whose omissions the test must detect.
Printing a numerator and denominator helps reveal changes, but cannot detect an item missing from both reports' populations.

**Evidence:** the talk's automatic captions, especially 08:08–08:58 and 15:35–19:58.
This is the speaker's historical account; the underlying Ferrocene changes were not independently inspected or reproduced for this example.

## Cancellation and return values

The [Go timer repair][timer-repair] addresses a case where an in-flight timer send was cancelled but `Stop` or `Reset` could return `false`.
In the affected caller protocol, that result led the caller to wait for a timer value that would never arrive.
Preventing the send alone therefore did not establish correct cancellation behavior.
The return value had to describe the outcome consistently with what the caller could observe next.

The patch tracks in-flight sends and adds `TestStopResult` and `TestResetResult`.
These tests exercise the return value and the caller's conditional receive, rather than checking only that stale values disappear.
For another cancellation API, derive that follow-up action from its actual contract and preconditions.
Do not copy a timer-draining idiom across versions or concurrent-receiver arrangements without checking those conditions.

A useful regression checks the caller's whole protocol under the interleaving that caused the disagreement.
A valid implementation change may alter internal bookkeeping while preserving the result and required follow-up behavior.
This is an application of consumer-validated oracles and API guarantees, not a new universal cancellation protocol.

**Evidence:** the Go runtime patch and its tests were inspected as source.
No execution of this historical repair is claimed here.
The [OpenTelemetry discussion][otel-discussion] supplies consumer context.
It distinguishes a corrected diagnosis from a separate older timer-contract violation.

[coverage-talk]: https://www.youtube.com/watch?v=P9lmSc4oLFs
[timer-repair]: https://github.com/golang/go/commit/3b2e846e11d0c31a556b198f6c700745de5c9780
[otel-discussion]: https://github.com/open-telemetry/opentelemetry-go/issues/5868
