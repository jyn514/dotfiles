# Cached discovery and unsuccessful lookups

Read this example when designing a cache for ordered discovery or resource selection.
It illustrates the need to establish the cache's required behavior, not a requirement to track every possible filesystem change.

## A new candidate changes an unchanged lookup

Ccache's direct mode can reuse a compilation without running the preprocessor.
It records the headers read by the compiler and validates those files before returning a cached result.
That does not capture every condition that made the compiler select them.

In [issue #504][ccache-report], both `a_test/` and `b_test/` already exist.
Compilation with `-Ia_test -Ib_test` selects `b_test/test.h`, which declares a function that the source calls with two arguments.
The caller then creates `a_test/test.h`, declaring the same function with three arguments, and repeats the command.
The source and previously selected header remain unchanged, but the compiler should now select the earlier header and reject the call.
The reporter observes a direct-mode cache hit instead.
The missing dependency is the unsuccessful earlier lookup, not another file's previously read contents.

The maintainer identifies this as a documented limitation and advises disabling direct mode when this case must be handled.
Preprocessor fallback is not an independent check on successful direct hits: those return before preprocessing runs.
Moving work to a fallback therefore does not protect a path that never reaches it.

## A partial mitigation has a narrower claim

The [2024 mitigation][ccache-mitigation] adds the existence of include-directory path arguments to the direct-mode key.
Its test starts with an absent higher-priority directory, creates it with a header, and expects a new compilation result.
That detects an appearing directory, but not a new header inside an already-existing directory, as in the earlier report.
Both the patch and the [pinned manual][ccache-manual] explicitly retain that limitation.

For a similar design, distinguish dependencies on the previous winner from conditions that let it win an ordered search.
If the contract requires rediscovery, include an appearing higher-priority candidate in the acceptance cases without changing the old winner.
Check where validation and fallback actually execute before claiming they protect a hit.
If narrower behavior is acceptable, state that limit rather than describing a partial mitigation as complete dependency tracking.
This case does not justify adding directory scans or negative-lookup records to every cache.

**Evidence:** the upstream report, mitigation patch and committed test, pinned manual, and direct-hit return path were inspected.
The reported failure is attributed to the upstream reporter; neither it nor the mitigation test was executed for this example.

[ccache-report]: https://github.com/ccache/ccache/issues/504
[ccache-mitigation]: https://github.com/ccache/ccache/commit/b672f7ebad0967551d48cf93a65e052fb5cb3049
[ccache-manual]: https://github.com/ccache/ccache/blob/a71fe22a9f480e9c785ee65997c2fcaeeb8bc350/doc/manual.adoc#L1711-L1756
