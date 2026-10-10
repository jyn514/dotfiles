---
name: mutation-testing
description: Set up, scope, run, and analyze mutation-testing campaigns using project-compatible tools or bounded hand-selected mutations. Use for mutation testing, surviving or equivalent mutants, questions about assertion usefulness or whether tests catch plausible implementation mistakes, or diagnosing test sensitivity after a reproduced bug escaped passing tests. Not for ordinary test writing, confirming a single regression, line-coverage review, property-test authoring alone, or vulnerability discovery without mutation evidence.
---

# Mutation testing

Change an implementation deliberately and ask whether its tests notice. A surviving
mutation is a reason to investigate, not proof of a production bug. This skill owns
campaign selection, execution checks, and survivor analysis—not a particular engine,
test framework, version-control system, or repository runner.

## Start within the authorized scope

Read the project's instructions, relevant contracts, source, tests, and test commands.
A request to run mutation testing authorizes temporary mutations in an isolated
experiment, subject to repository restrictions. Reviewing existing results does not
authorize execution. Neither request grants permission to change maintained code or
tests, publish artifacts, or access live application state. For automatically routed
test-sensitivity work, use only the execution authority of the enclosing task;
loading this skill grants none. Confirming a single known regression can stay under
`design-for-change` without a campaign.

Use an explicitly selected target. Otherwise, use the component already under
discussion; if none exists, inspect the requested project and select the smallest
maintained component with existing tests and an identifiable contract. Explain the
choice. Ask when there is no safe, meaningful default. Do not expand to the whole
repository merely because an engine can scan it.

For supplied results, establish their scope, source identity, mutation definitions,
and test/build commands first. Read [survivors](references/survivors.md) and analyze
what the evidence supports; missing execution provenance remains a limitation.
Re-running requires execution authority.

## 1. Establish the execution path

Use the project's documented environment, isolation, build, and test mechanisms.
Keep temporary variants separate from maintained source and unrelated work. Mutate
maintained source rather than generated files, installed packages, or vendored code
owned elsewhere. Regenerate or rebuild through the owning mechanism when the tested
consumer needs an artifact. Use disposable data; a temporary checkout does not make
commands that contact live services or stores safe.

Identify which tests exercise the selected behavior, including subprocess, loader,
serialization, and filesystem paths where applicable. Run the chosen baseline and
confirm the intended cases execute without skips. If it fails, stop that scope and
report the prerequisite failure rather than count subsequent failures as detections.

Before the campaign, use a positive control: a deliberate behavior change that an
existing assertion should detect. Verify that the test consumes the changed code
and fails for that change—not an import, environment, or unrelated build failure.
If it survives, distinguish stale artifacts or a disconnected test path from weak
assertions before interpreting other results. Resolve the execution path or report
it unverified; do not assume a surviving control proves the suite is weak.

For a Rust constructor, the path may be source → rebuilt crate → rejection test.
For a TypeScript extension, it may be source → host loader → filesystem fixture.
A Python generator may need source → generated artifact → native consumer. A helper
test alone cannot establish the last two paths.

## 2. Select mutations and cost

Prefer an existing project-compatible mutation engine when its supported mutations
and test invocation fit the target. Check installed command help before choosing
flags. Follow `dependency-review` for adding or selecting external tooling; this
skill does not require mewt, muton, or a new installation mechanism.

When automation is unavailable or rebuild costs make a small pilot preferable,
enumerate hand-selected mutations and save their exact diffs. State that their
selection limits coverage. Do not turn a one-off script into a reusable runner.

Choose changes that challenge the declared behavior: remove a required check or
effect, invert a condition, shift a reachable boundary, alter an error result, or
omit information from serialization or identity calculation. Exclude tests,
expectations, generated outputs, and unrelated source from mutation targets.

Measure baseline runtime, including rebuilding, and estimate campaign cost from
mutation count and per-variant work. Set a finite budget and timeout appropriate to
the project. Narrow the scope or ask before materially exceeding the agreed budget;
do not silently launch an overnight or whole-compiler campaign.

## 3. Execute independent variants

Start each variant from the recorded baseline. Run one mutation at a time or use
separate engine-managed variants. Keep test inputs, assertions, build flags, and
execution environment fixed. Do not bless snapshots, edit tests, or repair production
code during the campaign. If mutation generation or rebuilding fails, inspect that
failure before consuming its output or testing an older artifact.

Record each exact mutation, source identity, build/test command, result, and decisive
failure or output. Distinguish:

- **Detected:** an executed test observes the mutation through the intended path.
- **Survived:** the selected tests execute and pass with the mutation present.
- **Invalid:** the mutation cannot form a valid program or artifact; a compiler
  rejection is not evidence that behavioral assertions work.
- **Inconclusive:** timeout, environment failure, skipped or disconnected tests,
  unrelated build failure, or uncertain artifact identity.
- **Not run:** excluded, budget-stopped, or engine-skipped variants.

A nonzero exit alone does not establish detection. A crash caused by a valid mutation
can count when an exercised behavioral test detects it; failed test setup cannot.

## 4. Resolve survivors and report

Read [survivors](references/survivors.md) for each surviving mutation or when
interpreting supplied results. Separate demonstrated test gaps, proven equivalent
mutations, and unresolved cases. Do not infer a defect in the original implementation
from a defect deliberately introduced by a mutation.

Recommend the smallest distinguishing tests. If permanent test changes are authorized,
use `design-for-change` for contracts, regression/valid-change evidence, and test
reachability; use `property-based-testing` when a whole input domain needs coverage.
After adding tests, rerun the unchanged baseline and relevant mutations in a fresh,
separately identified run. Use `double-check` only for its declared completion-audit
scope, not as a required campaign phase.

Finish with the target and selection method, execution-path evidence, outcome counts
with denominators, concrete survivor conclusions, and remaining gaps. Identify
excluded and unexamined work. Keep exact inputs and evidence needed to replay reported
findings, without prescribing a report filename or artifact schema. A partial campaign
is a valid result when labeled; unresolved cases are not clean results. Do not convert
one campaign's detection rate into overall test adequacy or impose a universal score
threshold.

Source and license: [adaptation notice](README.md).
