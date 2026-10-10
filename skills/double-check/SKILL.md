---
name: double-check
description: Audit completed substantial implementation or refactor work when acceptance spans multiple components, a specification, migration, or consequential boundary. Use after owned edits are complete, or when the user explicitly requests a completion audit. For a routine localized edit or simple config, inspect the diff and run the appropriate native check without loading this skill. Its evidence standards may be consulted separately; do not run the audit for read-only exploration or progress updates.
---

# Double-check your work

Audit completion against evidence, not confidence. Run the full procedure after the owned edits are complete; before then, use only the original request and governing specification to identify evidence the eventual audit must require.

Use the full audit for changes such as a multi-component refactor or persisted-data migration. A documented keybinding change needs a diff review and native config validation, not this workflow. In either case, report what was checked and leave unavailable runtime evidence explicit.

## Read First

Discover and follow the target repository's guidance for review thresholds, testing, code and documentation style, generated files, migrations, and issue completion. Read the original request, acceptance criteria, and any governing specification or design.

## Evidence and integration status

These standards define what checks prove during implementation and at completion; consulting them early does not start the full audit. [Design-for-change](../design-for-change/SKILL.md#design-for-testing) owns test construction. [Autonomous-implementation](../autonomous-implementation/SKILL.md) applies these standards to milestone readiness during explicitly authorized unattended work.

A worker report, aggregate test count, correct helper, or atomic commit is not evidence that the assembled path works. Distinguish:

- **Component-tested / local-only:** checks pass only for an isolated component or mocked path.
- **Integrated:** the required consumer-path check passes through intended interfaces for the declared scope.
- **Verified with required real inputs:** checks also pass with the credentials, data, or environment explicitly required by the governing acceptance condition.

Fixture inputs through intended interfaces can establish integration, but cannot satisfy a condition requiring real inputs. A feasibility or component milestone can complete at its declared scope without completing downstream integration. Record a failed check or unresolved contract that prevents integration as **blocked**; do not certify blocked outputs or claim broader completion.

Label each check by the process or boundary it reaches. A unit/helper or mocked-launcher test does not prove that the receiver loaded an extension, ran a hook, or received a transformed payload. For receiver-visible claims, trace the production path from entrypoint through configuration, launch, handler order, and receiver, then use an integration test that reaches the receiver or direct runtime observation. If unavailable, mark that behavior unverified; component results support but do not substitute.

## Procedure

1. Identify the owned diff, explicit requirements, acceptance criteria, and protected unrelated work while the patch is still uncommitted. Use the acceptance cases established before implementation; if none exist, derive them from the governing request before auditing. Fix audit scope, including required independent review; hypothetical edge cases add no obligations.
1. Map every requirement to concrete evidence from the final files, focused tests, native parsers or linters, generated-artifact checks, and migration or compatibility checks where applicable.
   Build an acceptance matrix from the original issue. For staged new-tool work, use approved requirement IDs and implementation-spec commitments instead; use the original issue or request only to identify unexplained omissions. Treat approved exclusions and non-goals as valid, not as drift. Include each named input mode, option combination, and explicitly named exception.
   Each row records the requirement, mode or condition, expected observable behavior, evidence command or artifact, and result.
   Add rows only for governing requirements or reproduced failures of them; possible behavior differences alone add no cases.
   Test every applicable row or record why a row is inapplicable.
   Treat a missing row as missing evidence.
   For cross-process or permission-boundary changes, include the assembled runtime path and a forbidden effect in the matrix, and test at the enforced boundary. Apply the [evidence standards](#evidence-and-integration-status) to every result.
1. Compare the issue's original acceptance text with the implementation, tests, close note, and specification.
   For staged new-tool work, report acceptance drift only when a later artifact is narrower than the governing approved requirements; do not report approved exclusions or non-goals as drift.
   If the owned diff changes tests, fixtures, snapshots, skiplists, or comparison logic, inspect the decisive assertions and setup, not test names or aggregate counts. Identify behavior that now passes but previously failed, and required paths or cases no longer exercised. Justify each relaxation against the governing requirements; changed expectations alone do not establish correctness. For reference-based claims, trace final expectations to the declared reference or an authorized divergence; formatting normalization must not hide changed values, missing errors, or excluded cases.
   For changed tests, identify the requirement that fixes important exact-value expectations. Check the regression and valid-change evidence required by [design-for-change](../design-for-change/SKILL.md#design-for-testing); passing tests or matching current output are insufficient. Flag expectations that freeze configuration or dependency internals without a contractual reason.
   For multi-condition decisions, check the condition-matrix evidence required by design-for-change, including omitted conditions, masking by other conditions, and justified interactions.
1. Check that the implementation fixes the demonstrated failure rather than its symptom. Reopen the selected design only for a reproduced acceptance failure; record optional alternatives without implementing them.
1. Within the fixed scope, search for likely loose ends: stale names and paths, old representations, duplicate implementations, bypass paths, temporary probes, unhandled lifecycle states, and documentation that still describes the prior behavior.
1. Challenge applicable boundaries with the cheapest realistic cases needed by the acceptance matrix, not every case in this list:
   - duplicate identical inputs and multiple selected objects or refs
   - equal, aliased, symlinked, ancestor, and descendant paths
   - interruption or timeout before and after each effect or publication transition
   - successful mutation followed by failed optional presentation
   - stale selection changed before mutation
   - ambient checkout, configuration, platform, or provider differing from the selected object
   - produced-native execution when compilation or JVM tests cannot establish runtime reachability
1. If the user authorized implementation or repair, fix in-scope failures, rerun affected checks, and inspect the resulting complete diff. Otherwise report findings without mutation.
1. Apply the repository's review threshold. Request independent review when the change is broad, cross-boundary, security-sensitive, destructive, or otherwise requires authority beyond self-review.
1. After the initial audit and required independent review, check corrections only: rerun failed checks and checks for changed code or boundaries. Do not restart the audit or search unchanged boundaries for hypotheses; a second broad audit requires user approval.
1. When scoped checks pass, report completion or external blockers and stop. Reopen only for a reproduced governing-requirement failure or authorized scope change. Do not claim completion without evidence for every requirement; unrelated baseline failures and unverified requirements are not successes.

## Reporting

Report one line per requirement or applicable review area: pass with concrete evidence, or fail with what remains. Cite anchors such as file paths, command output, issue criteria, or specification sections; do not report only that the work “looks good.”

If a failure is outside the owned slice, name it as unrelated and leave the protected files alone.
