---
name: completion-audit
description: Check whether a completed substantial owned change fulfills the original request, governing requirements, and acceptance conditions, using final-state evidence. Use after multi-component implementation, refactoring, or migration, or for an explicit completion-audit request. Map requirements to concrete final-state evidence and report unmet outcomes. Routine localized edits need diff review and native validation, not this audit. Not for standalone specification critique or a whole-spec conformance survey.
---

# Completion audit

Connect each promised outcome to evidence from the finished change.
A multi-component refactor or persisted-data migration needs this audit; a documented keybinding change needs diff review and native config validation.

Audit after owned edits are complete, while the patch is uncommitted.
Before then, identify required evidence from the request and governing specification without starting the audit.
Use [Evidence standards](../references/review-evidence.md) to interpret checks; consulting them does not start an audit.

## Fix the acceptance scope

Read the request, acceptance criteria, governing specification or design, and repository review and validation guidance.
Identify the owned diff and protected unrelated work.
Fix scope, including required independent review, from the acceptance cases established before implementation; derive missing cases from the governing request.
Hypothetical edge cases add no obligations.

Build an acceptance matrix:

| Requirement | Mode or condition | Expected observable behavior | Evidence command or artifact | Result |
| --- | --- | --- | --- | --- |

Include every requirement and its named modes, option combinations, and exceptions.
For staged new-tool work, use approved requirement IDs and implementation-spec commitments; consult the original request for unexplained omissions.
Honor approved exclusions and non-goals.
Add cases only for governing requirements or reproduced failures of them.
Check applicable rows, explain inapplicable ones, and treat missing rows as missing evidence.

## Follow each claim to its evidence

Choose final-file inspection, native validation, focused tests, generated-artifact checks, or migration and compatibility checks according to the claim.
For cross-process or permission-boundary changes, exercise the assembled runtime path and a forbidden effect at the enforced boundary.

For example, a conversion unit test against known expected values can establish data conversion.
An upgrade claim needs old-format persisted data migrated through the production entrypoint and read by the new runtime.
Leave unavailable runtime evidence unverified.

Compare governing acceptance text with implementation, tests, specification, and close note.
Report drift when later artifacts narrow requirements, not when they honor approved exclusions.

### Would the assertions reject the wrong behavior?

When tests, fixtures, snapshots, skiplists, or comparisons change, inspect decisive assertions and setup.
Identify newly passing behavior and required cases no longer exercised.
Justify relaxations and exact expectations from requirements, not current output.
Trace reference-based expectations to the declared reference or authorized divergence.
Normalization must preserve values, errors, and case eligibility.

Read [Testing](../references/testing.md) for regression and valid-change evidence, condition matrices, generated cases, isolation, and dispatch.
Flag exact expectations that freeze configuration or dependency internals without a contract.

### Does the suite exercise the claimed behavior?

For multi-condition decisions, check omitted or masked conditions and justified interactions.
For generated cases, check executed classes, interactions, and replayable failures.
Consider bounded [property-based testing](../property-based-testing/SKILL.md) when repeated examples miss requirement-relevant dimensions or action sequences.
PBT's absence alone is not a finding.
Inspect changed tests' effect destinations and top-level command reachability.
They must preserve authoritative source and live state unless explicitly authorized.
Separate prerequisites and skips from executed passing cases.

### Does the repair address the demonstrated cause?

For escaped bugs, assess the testing-gap diagnosis and corrected test model, not just the new regression example.
Use bounded [mutation testing](../mutation-testing/SKILL.md) when in-scope sensitivity remains uncertain beyond the named regression, within existing execution authority.
A routine audit needs no mutation campaign.

## Check the assembled change

Within scope, search for stale names, paths, representations, documentation, duplicates, bypasses, temporary probes, and unhandled lifecycle states.
For added or retained runtime resources, compare before/after counts and topology across every relevant capability combination and owner.
Check overlapping trust, connectivity, and lifecycle roles.
Reject an existing owner only for a concrete unmet requirement; conditional creation alone is insufficient.

Select the cheapest realistic boundary cases the matrix needs:

- Duplicate inputs or multiple selected objects/refs; equal, aliased, symlinked, ancestor, or descendant paths.
- Interruption or timeout around effects or publication; successful mutation followed by failed optional presentation.
- Selection changing before mutation; ambient checkout, configuration, platform, or provider differing from the selected object.
- Produced-native execution where compilation or JVM tests cannot establish reachability.

These examples add no mandatory cases.

## Resolve, report, and stop

Fix in-scope failures only under existing implementation or repair authority; otherwise report without mutation.
Rerun affected checks, inspect the complete resulting diff, and leave unrelated failures and protected files alone.
Reopen the design only for a reproduced acceptance failure; record optional alternatives without implementing them.

Apply repository review thresholds.
Request independent review for broad, cross-boundary, security-sensitive, destructive changes or those exceeding self-review authority.
After the initial audit and required review, check corrections only: failed checks and changed code or boundaries.
A second broad audit requires user approval.

Report each requirement or applicable review area's result with file paths, command output, issue criteria, or specification sections.
Unrelated baseline failures and unverified requirements are not successes.
Claim completion only with evidence for every requirement; otherwise name remaining failures or external blockers.
Stop when scoped checks pass; reopen only for a reproduced governing-requirement failure or authorized scope change.
