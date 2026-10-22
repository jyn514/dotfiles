---
name: review
description: Review a design/specification against its purpose and constraints; compare implementation and tests with a normative specification for conformance and bidirectional spec drift; or audit completed owned substantial changes against task acceptance. Use for design critique, bounded or whole-spec conformance audits, and completion audits after substantial edits or on explicit request. Not for selecting competing proposals, implementing conformance fixes, read-only exploration, or progress updates. Routine localized edits need diff review and native validation, not a full audit. Evidence standards can be consulted separately without starting a completion audit.
---

# Review

## Select the review target

Read the request and repository guidance. Establish the artifact, authoritative
inputs, owned scope, and requested output before choosing **one** procedure:

- **Design/spec vs purpose and constraints:** read [Design review](references/design.md).
  Establish maturity and upstream authority; check consistency, completeness,
  necessity, and unsupported narrowing. This critiques one design or a related
  specification set, not selection among competing proposals.
- **Implementation vs normative spec:** read [Conformance review](references/conformance.md).
  Start with the named files, sections, symbols, tests, commands, or revisions;
  without narrower scope, follow its whole-spec procedure. Check missing/partial
  implementation and bidirectional drift, not only whether code follows prose.
- **Completed owned substantial change vs task acceptance:** read
  [Completion review](references/completion.md) after edits are complete, or for
  an explicit completion-audit request. A multi-component refactor or migration
  warrants this; a localized keybinding edit needs diff review and native config
  validation instead.

Do not run all three by default. Keep one evolving review target; consult another
procedure only for a concrete question within that target, not as a fresh audit.
If no safe target or governing authority can be established, ask for clarification.
For evidence planning or interpreting checks at any time, consult
[Evidence standards](references/evidence.md) independently; this does not invoke
completion review. Implementation preferences live in
[Design choices](../references/change-with-evidence.md#design-choices); test
construction lives in [Testing](../references/testing.md).

## Preserve authority

Review-only work authorizes findings, not repairs. Specification reconciliation
and issue filing each require explicit permission. Conformance review never
implements fixes. Completion review may fix in-scope failures only under existing
implementation or repair authorization; loading this skill grants none.

Report supported findings and evidence, checked scope, exclusions, deferrals,
and unavailable validation. Do not turn silence into completeness or invent
findings to fill categories. Stop when the selected procedure's scoped checks
settle the task; do not reopen unchanged boundaries without its stated trigger.
