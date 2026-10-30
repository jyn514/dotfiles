# Testing examples: populations, cancellation, and reference behavior

Read the relevant example when a report may omit required items, a cancellation result controls the caller's next action,
or an unoptimized implementation is proposed as the test oracle.
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

### What source inspection establishes

Separately, Ferrocene revision `4a8f685da19c66d95a8d59b5c0cd8d20c35f4ac2` confirms the inventory-and-report mechanism.
The [inventory exporter][ferrocene-inventory] selects expanded compiler definitions using certification policy and explicit exclusions, not execution records.
Its independence is from the observed coverage population, not from compiler configuration or the eligibility policy itself.

The [reader][ferrocene-reader] iterates every inventory entry and looks up coverage by source filename and inclusive line span.
It discards the linkage name rather than matching compiled function symbols or generic instantiations independently.
The [classifier][ferrocene-classifier] initially marks a missing file's lines untested, before applying annotations.
If the file exists in the coverage map but no regions intersect a required definition's span, that definition becomes `FullyIgnored`.

The inventory therefore keeps required definitions visible, but does not independently establish why their coverage is absent.
Correct classification still depends on coverage-map completeness and source-location attribution.
The presence of an inventory row does not establish coverage of every generic instantiation.

**Evidence:** the talk's automatic captions, especially 08:08–08:58 and 15:35–19:58, plus the separately pinned source above.
The exact talk/demo revision, percentages, and generated outputs were not independently validated.
The `Infallible::clone` example remains part of the speaker's historical account, not a reproduction against the inspected revision.
No runtime execution is claimed here.

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

## Reference behavior and remembered renames

An unoptimized implementation can be a useful comparison without defining every correct result.
Git's [remembered-renames rationale][rename-rationale] gives a concrete counterexample.
During a sequence of merges, an earlier clean merge establishes a file correspondence that fresh similarity detection can later miss.

Start with `numbers` containing lines 11–30.
Upstream renames it to `sequence` and prepends lines 1–10.
A topic commit keeps only lines 11–13; merging that commit onto upstream produces `sequence` containing lines 1–13.
The next topic commit immediately reverts the deletion.
At the default similarity threshold, fresh detection no longer pairs the short `numbers` with `sequence`, producing a modify/delete conflict.
Remembering their correspondence permits a three-way content merge that restores lines 1–30 in `sequence`.
The optimization changes which current files are merged together; it does not return cached file contents.

The author explicitly accepts that behavioral difference rather than requiring equivalence to fresh detection.
Reuse checks that the next merge's trees continue the previous operation, and user interruption discards the in-memory cache.
This is not permanent file identity or permission to reuse arbitrary earlier results.
It is also not a claim about every `git rebase`: the [activation commit][rename-activation] explains that the ordinary sequencer discards
this state between picks, while the original example uses `test-tool fast-rebase`.

For another optimization, establish whether the governing requirement is exact parity or a result that a heuristic comparison may fail to find.
If parity is required, keep the differential check.
If a behavioral change is authorized, test that requirement independently and record the intended divergence instead of treating all differences as defects.
This example does not authorize changing requirements to accommodate an optimization.

**Evidence:** the original rationale, activation patch, and before/after test were inspected as source; no execution is claimed.
The immediate-revert test checks successful replay and rename-detection count, not the final file contents.
The expected contents above follow the described three-way merge and the author's rationale, not a separately reproduced result.

[coverage-talk]: https://www.youtube.com/watch?v=P9lmSc4oLFs
[ferrocene-inventory]: https://github.com/ferrocene/ferrocene/blob/4a8f685da19c66d95a8d59b5c0cd8d20c35f4ac2/ferrocene/tools/symbol-report/src/main.rs#L183-L248
[ferrocene-reader]: https://github.com/ferrocene/ferrocene/blob/4a8f685da19c66d95a8d59b5c0cd8d20c35f4ac2/ferrocene/tools/blanket/src/rustc_driver.rs#L31-L63
[ferrocene-classifier]: https://github.com/ferrocene/ferrocene/blob/4a8f685da19c66d95a8d59b5c0cd8d20c35f4ac2/ferrocene/tools/blanket/src/main.rs#L234-L305
[timer-repair]: https://github.com/golang/go/commit/3b2e846e11d0c31a556b198f6c700745de5c9780
[otel-discussion]: https://github.com/open-telemetry/opentelemetry-go/issues/5868
[rename-rationale]: https://github.com/git/git/commit/64aceb6d738394130a6e215dc6de51d8452313e0
[rename-activation]: https://github.com/git/git/commit/25e65b6dd52c987056f1cac00fe6073fbf8ea237
