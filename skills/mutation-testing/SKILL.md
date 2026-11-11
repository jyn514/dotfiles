---
name: mutation-testing
description: Set up, scope, run, and analyze mutation-testing campaigns using project-compatible tools or bounded hand-selected mutations. Use for mutation testing, surviving or equivalent mutants, questions about whether assertions are useful or tests catch plausible implementation mistakes, or diagnosing test sensitivity after a reproduced bug escaped passing tests. Not for ordinary test writing, confirming a single regression, line-coverage review, property-test authoring alone, or vulnerability discovery without mutation evidence.
---

# Mutation testing

Deliberately change an implementation and ask whether its tests notice.
Explain survivors: they may expose a test gap, an equivalent change, or an execution problem.
A survivor does not establish a production bug.

## Choose the question and scope

Read the project's instructions, contracts, source, tests, and test commands.
Use the selected target, otherwise the component under discussion.
If neither exists, select the smallest maintained component with tests and an identifiable contract; explain why.
Ask when no safe, meaningful default exists.
An engine's scanning range is not a reason to expand the target.
Confirming one known regression can stay under [testing guidance](../references/testing.md).

A request to run mutation testing permits temporary mutations in an isolated experiment, subject to repository restrictions.
It does not permit maintained code or test changes, publication, or live-state access.
Reviewing results grants no execution authority; automatically routed work uses only the enclosing task's authority.
For supplied results, establish scope, source identity, exact mutations, and build/test commands, then read [survivor analysis](references/survivors.md).
Retain missing provenance as a limitation; rerunning requires execution authority.

## Verify what the tests consume

Use the project's environment, isolation, build, and test mechanisms.
Keep variants separate from maintained source and unrelated work.
Mutate maintained source, not tests, expectations, generated outputs, unrelated source, installed packages, or externally owned vendored code.
Rebuild or regenerate through the owner when the consumer needs an artifact.
Use disposable data: checkout isolation does not make live services safe.

Identify the tests exercising the behavior, including indirect consumers.
Run a baseline and confirm the intended cases execute without skips.
If it fails, stop that scope and report the prerequisite failure.

Before the campaign, make a positive control: a behavior change an existing assertion should detect.
Verify that the test consumes the changed code and fails because of it, rather than an import, environment, or unrelated build failure.
If it survives, check stale artifacts and disconnected paths before judging assertions.
Resolve the path or report it as unverified; survival alone does not establish weak tests.

Trace the complete consumer path, for example:

- Rust constructor: source → rebuilt crate → rejection test.
- TypeScript extension: source → host loader → filesystem fixture.
- Python generator: source → generated artifact → native consumer.

A helper test alone cannot establish the last two paths.

## Choose meaningful mutations within a budget

Challenge the contract: remove a required check or effect, invert a condition, shift a reachable boundary, alter an error, or omit serialized or identity-significant information.
Prefer an existing compatible engine when its mutations and test invocation fit.
Check installed command help before choosing flags; use `dependency-review` for external tooling selection or addition.
No particular engine or installation mechanism is required.

When automation is unavailable or rebuild cost favors a small pilot, enumerate hand-selected mutations with exact diffs and disclose their selection limits.
Keep a one-off script a one-off, not a reusable runner.
Measure baseline runtime including rebuilding.
Estimate total cost from mutation count and per-variant work, then set a finite budget and timeout.
Narrow scope or ask before materially exceeding the agreed budget.

## Run comparable variants

Start each variant from the recorded baseline, one mutation at a time or in separate engine-managed variants.
Keep inputs, assertions, build flags, and environment fixed; do not bless snapshots or repair tests or production code mid-campaign.
Inspect generation or rebuild failures before consuming output or testing an older artifact.

Record each exact mutation, source identity, build/test command, result, and decisive output.
Classify by evidence, not exit status:

- **Detected:** an executed test observes the mutation through the intended path.
- **Survived:** selected tests execute and pass with the mutation present.
- **Invalid:** the mutation cannot form a valid program or artifact; compiler rejection does not test behavioral assertions.
- **Inconclusive:** timeout, environment or unrelated build failure, skipped/disconnected tests, or uncertain artifact identity.
- **Not run:** excluded, budget-stopped, or engine-skipped.

A valid mutation causing a crash can count as detected by an exercised behavioral test; failed setup cannot.

## Explain survivors and deliver

Use [survivor analysis](references/survivors.md) to distinguish demonstrated gaps, proven equivalence, and unresolved cases.
Recommend the smallest distinguishing tests.
Permanent test changes require authorization; use [testing guidance](../references/testing.md) for their design and `property-based-testing` for domain-wide coverage.
After adding tests, rerun the unchanged baseline and relevant mutations in a fresh, separately identified run.
[Completion review](../completion-audit/SKILL.md) applies only within its own scope, not to every campaign.

Report target and selection method, execution-path evidence, outcome counts with denominators, survivor conclusions, and excluded or unexamined work.
Preserve replayable inputs and decisive evidence without imposing a filename or schema.
Label partial campaigns and unresolved cases; a detection rate neither establishes overall test adequacy nor justifies a universal score threshold.

Source and license: [adaptation notice](README.md).
