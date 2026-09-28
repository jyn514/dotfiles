---
name: double-check
description: Audit completed implementation or refactor work before claiming it is done or closing its issue. Use after the owned edits are complete when acceptance, specification match, tests, migrations, or loose ends must be checked. It may be consulted earlier only to define completion evidence; do not run the audit for read-only exploration or early progress reports.
---

# Double-check your work

Audit completion against evidence, not confidence. Run the full procedure after the owned edits are complete; before then, use only the original request and governing specification to identify evidence the eventual audit must require.

## Read First

Discover and follow the target repository's guidance for review thresholds, testing, code and documentation style, generated files, migrations, and issue completion. Read the original request, acceptance criteria, and any governing specification or design.

## Procedure

1. Identify the owned diff, explicit requirements, acceptance criteria, and protected unrelated work while the patch is still uncommitted.
1. Map every requirement to concrete evidence from the final files, focused tests, native parsers or linters, generated-artifact checks, and migration or compatibility checks where applicable.
   Build an acceptance matrix from the original issue. For staged new-tool work, use approved requirement IDs and implementation-spec commitments instead; use the original issue or request only to identify unexplained omissions. Treat approved exclusions and non-goals as valid, not as drift. Include each named input mode, option combination, and explicitly named exception.
   Each row records the requirement, mode or condition, expected observable behavior, evidence command or artifact, and result.
   Add rows only where behavior can differ; do not enumerate irrelevant combinations.
   Test every applicable row or record why a row is inapplicable.
   Treat a missing row as missing evidence.
   For cross-process or permission-boundary changes, include the assembled runtime path and a forbidden effect in the matrix, and test at the enforced boundary. Label each test by the process or boundary it reaches: a unit/helper or mocked-launcher test proves only that layer; it does not prove the receiver loaded the extension, ran the hook, or received the transformed payload. For receiver-visible claims, trace the production path from entrypoint through configuration, launch, handler order, and receiver, then use an integration test that reaches the receiver or direct runtime observation. If unavailable, mark the behavior unverified; component-test results support but do not substitute.
1. Compare the issue's original acceptance text with the implementation, tests, close note, and specification.
   For staged new-tool work, report acceptance drift only when a later artifact is narrower than the governing approved requirements; do not report approved exclusions or non-goals as drift.
1. Ask yourself: is this the right approach? Are you sure this fixes the underlying bug? Would a better approach be simpler or more maintainable?
   If so, go with that approach instead.
1. Search for likely loose ends: stale names and paths, old representations, duplicate implementations, bypass paths, temporary probes, unhandled lifecycle states, and documentation that still describes the prior behavior.
1. Challenge applicable boundaries with the cheapest realistic cases:
   - duplicate identical inputs and multiple selected objects or refs
   - equal, aliased, symlinked, ancestor, and descendant paths
   - interruption or timeout before and after each effect or publication transition
   - successful mutation followed by failed optional presentation
   - stale selection changed before mutation
   - ambient checkout, configuration, platform, or provider differing from the selected object
   - produced-native execution when compilation or JVM tests cannot establish runtime reachability
1. If the user authorized implementation or repair, fix in-scope failures, rerun affected checks, and inspect the resulting complete diff. Otherwise report findings without mutation.
1. Apply the repository's review threshold. Request independent review when the change is broad, cross-boundary, security-sensitive, destructive, or otherwise requires authority beyond self-review.
1. Do not claim completion while any requirement lacks evidence. Distinguish an unrelated baseline failure from an unverified requirement; neither is silently converted into success.

## Reporting

Report one line per requirement or applicable review area: pass with concrete evidence, or fail with what remains. Cite anchors such as file paths, command output, issue criteria, or specification sections; do not report only that the work “looks good.”

If a failure is outside the owned slice, name it as unrelated and leave the protected files alone.
