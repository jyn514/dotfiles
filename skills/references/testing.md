# Testing with evidence

Consult when adding or materially changing tests, or resolving test-strategy or oracle uncertainty.
Use the surrounding tests for an established pattern; do not start a design or completion audit merely to choose a test.


## Choose the test shape

Split meaningful business logic and likely bugs where they can be tested. Prefer running most of the system in memory so generated tests can cover many cases cheaply. If database behavior or subtle invariants belong to the trusted computing base, run the real database in memory when practical instead of mocking it. The plan-execute pattern often helps.

## Execution and case coverage

- Follow the [shared test isolation constraints](~/.agents/shared.md#before-running-tests) when running tests or checking regeneration.
  When a test launches a production entrypoint, inspect inherited inputs that select files, sockets, services, or credentials.
  Explicitly replace or remove those inputs unless the test intentionally supplies an owned disposable resource.
  A private HOME does not redirect explicit destinations; preserve inherited inputs the test deliberately needs.
- Register automated suites with the repository's top-level test command, either by default or through a documented opt-in mode. Verify that the command discovers and executes them; a focused invocation alone does not prove reachability. Report missing prerequisites and skips distinctly from passing checks.
- Use property tests when generators express the input space better than enumerated examples. When combinations or action sequences exceed a practical hand-written matrix, use bounded generated tests with requirement-derived or consumer-validated oracles. Record failing inputs for replay and reduce them to small regressions when practical. Use [property-based-testing](../property-based-testing/SKILL.md) for property-specific generator design and review.
- Verify that executed generated cases contain the declared input classes and selected interactions, including after filtering or deduplication. Do not infer this from generator code alone. Include required cases explicitly when random generation cannot reliably exercise them; this check does not require an exhaustive cross-product.
- Use golden tests with thoughtful fixtures at a consumer-meaningful layer; one shared check function should make cases easy to add and review.

## Expected behavior and regression evidence

- For ports or parity-preserving rewrites, identify the reference implementation or pinned test revision and compare both implementations on the same cases. Keep reference expectations separate from candidate-generated output. Record intended divergences against the governing requirements; ask only when accepting a divergence would change those requirements. Treat formatting normalization separately from changes to values, error behavior, or case eligibility.
- Establish expected behavior before using a passing test as evidence of correctness.
  Identify the concrete source for each expectation: a governing requirement, external specification, reviewed fixture, or independent consumer.
  Existing tests, docstrings, snapshots, and current output can repeat the same defect; agreement alone is not independent confirmation.
  When a test fails, determine whether the code, expectation, or specification is wrong before changing it.
  Do not change expectations solely to match current output or obtain a passing test.
  If the evidence does not settle the expected behavior, report the uncertainty and ask when resolving it requires a requirements decision.
- Seek courage, not coverage: tests should catch consumer-visible divergences and permit refactoring. Do not mirror implementation constants in tests.
- Do not mechanically update tests that assert implementation text, constants, or structure. When such a test breaks, identify the consumer-visible regression it prevents; replace it with a behavioral test, or delete it if no practical test protects that behavior. An existing test is not evidence that it is valuable.
- Before adding or updating a test, name a realistic regression caused by a likely edit or previously observed failure and a valid change the test must allow. Verify the test fails when the regression is reintroduced. Otherwise, do not add or update it. When expected values depend on mutable configuration or dependency behavior, exercise the valid change within the supported modes, or explain why the governing contract fixes those values. Distinguish reproducing the reported error from demonstrating a related failure; state what the experiment proves.
- When a reported bug escapes passing tests, identify the missing input dimension, action sequence, or incorrect oracle assumption. Update the corresponding case matrix, generator, or oracle and retain the concrete regression; adding only the failing example does not address the testing gap. If sensitivity to specific plausible faults remains uncertain beyond confirming that regression, use [mutation-testing](../mutation-testing/SKILL.md) for a bounded check, not a whole-suite campaign.
- When several conditions determine acceptance, selection, or a lifecycle transition, build a small decision table from the requirements. For each independently significant condition, include two feasible cases that differ only in that condition and produce the required difference in observable behavior. Record coupled or infeasible combinations. Add interaction cases justified by the contract or observed failures; independent-condition pairs do not establish interaction coverage. Derive expected results independently of the implementation. The table can live in parameterized test cases; no separate artifact is required. This checks the declared decision model, not instrumented code coverage.

## Consumer and integration boundaries

- Validate the test oracle against the consumer's actual behavior. A mock accepting generated Docker arguments does not establish that Docker can mount them. Check equivalence and cardinality when relevant: distinct occurrences, objects, refs, paths, or owners must not collapse because normalized text or fingerprints match. If no reliable oracle is available, record that validation limit rather than claiming the invariant is protected.
- When a change binds a discovered resource to an owner, test both sides of that lifetime.
  Verify that the existing owner consistently uses its selected resource despite unrelated ambient changes, and that a new owner observes a new selection.
  Verify that intentionally dynamic inputs still change within the existing owner's lifetime.
  Exercise the binding through the subprocess or protocol boundary where the resource is actually used, when one exists.
  Lookup-count assertions alone do not establish correct resource selection or freshness.
- When behavior is assembled from multiple producers, test the complete consumer-visible result and make the original failure recur when any producer duplicates or omits an entry.
- When overrides can change output shape or identity, test those transitions as well as same-form value changes.
  Where the contract requires replacement, verify that winning effects appear and obsolete effects from losing definitions are absent.
  For example, switching an alias between a command abbreviation and a differently named shell abbreviation must not leave both forms.
- Start integration testing with one small workflow through the normal production entrypoint and a fresh disposable fixture.
  Reuse automatic build and artifact selection when the entrypoint already provides it.
  Do not ask the tester to reconstruct private cache paths or pass manual selection flags instead.
  Introduce each handoff through its intended native producer-to-consumer interfaces;
  for example, pass a CLI a small valid input snapshot rather than adding a fixture-JSON API.
- Keep functional smoke tests separate from precise edge-case tests.
  Check command success and resulting contents or history in the smoke test;
  use separate controlled tests at the boundary required by the guarantee for in-flight cancellation, strict interleaving, or overlapping database commits.
  Choose unit, component, or integration tests as appropriate; retain actual OS or provider acceptance tests where the guarantee requires them.
  A sampler missing a short-lived process does not establish command failure.
  Successful concurrent loops do not establish those precise ordering guarantees.
  Do not compare monotonic timestamps from different kernels.
- Allow temporary probes or fixture-specific adapters only to resolve a demonstrated uncertainty or prerequisite; a future integration TODO is insufficient. Preserve probes that establish acceptance as regression tests; one-off uncertainty probes need not persist. Do not promote temporary implementations into production interfaces.

## Failure paths and lifecycle cases

- Test both failure directions: accepting invalid results and losing required valid results. Include representative non-special-cased inputs where general behavior is required. For bounded algorithms, test forced work separately from branching work; small fixtures must not conceal the required input-population constraint. Preserve validation and publication constraints rather than relaxing them for a passing test.
- Make example tests read as a meaningful narrative about important edges and costly regressions.
- State concurrency requirements as states and ordering, independently of the callbacks used to pause the fixture.
  Assert the precondition that makes a race valid before starting or releasing a competing operation.
  When upstream moves a callback, move the fixture only if it still proves the same ownership, admission, and cancellation contract; otherwise resolve the behavior change first.
- For public refactors, run a clean-interpreter check from the repository root for every supported import and invocation mode; test discovery or an injected module path does not establish package reachability.
- After applying the [shared rejected-design stop rule](~/.agents/shared.md#when-the-user-rejects-a-design), restate the revised ownership boundary before resuming dependent implementation.
- When claiming that a change fixes an observed failure, compare baseline and candidate from the same pre-failure state.
  Verify that the baseline reproduces the failure and judge improvement by observable behavior.
  Identify other differences that could explain the result, including test setup, dependencies, model versions, and randomness.

## Review and workflow routes

When reviewing a system and its tests, check both directions: required behavior without a test, and tested behavior without a corresponding requirement. Apply this to code, APIs, policies, prompts, workflows, and specifications.

Use [ratchet](../ratchet/SKILL.md) for unresolved enforcement-policy decisions about existing violations, baseline updates, bounded exceptions, or replacing guarantees. A new regression test or a better oracle alone does not need that workflow.

Use [review evidence standards](../review/references/evidence.md) to determine what the checks prove; use the [completion audit](../review/references/completion.md) only after substantial owned edits are complete and its scope applies.
For explicitly authorized autonomous work, [autonomous-work](../autonomous-work/SKILL.md) owns run continuity and acceptance order, not test construction.
