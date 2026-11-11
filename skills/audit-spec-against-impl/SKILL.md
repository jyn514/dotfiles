---
name: audit-spec-against-impl
description: Compare what the current normative specification promises with implementation and tests, in both directions. Check for missing or partial implementation, undocumented intentional behavior, spec lag, and obsolete requirements. Use for bounded or whole-spec conformance audits and bidirectional drift. A review request authorizes findings only; reconcile specification text or file issues only when requested. Do not implement fixes. Not for critiquing a specification's design or auditing completion of an owned change.
---

# Audit specification against implementation

Find both unfulfilled promises and intentional behavior the specification no longer describes.
The mismatch establishes drift; evidence of project intent determines which side needs to change.
Use [evidence standards](../references/review-evidence.md) when supporting findings and stating what checks establish.

## Establish scope and authority

Read repository instructions and contributor documentation for specification, ownership, tracker, and validation rules.
Use the documented specification; otherwise start in `doc/` and identify current normative documents rather than design snapshots.
Report a missing or ambiguous contract instead of inventing requirements.

Start with the scope named in the request.
For a named revision, inspect its changes first; use a specification change as the requirement delta and audit the current tree against the resulting contract.

Consult issue history when evidence, authorized reconciliation, or filing needs it.
Whole-spec audits require issue-history coverage and deduplication even without filing authority.
A bounded findings-only comparison with sufficient contract, implementation, and test evidence needs no tracker lookup.
Use the documented tracker; otherwise use TicGit (`ti`) and read the `ticgit` skill for commands.
This fallback is independent of the specification fallback.
If the needed tracker is unavailable, report the affected limitation and continue independent checks rather than switching trackers.

A review request authorizes findings only.
Reconcile specification text or file issues only when requested, within that scope.
Do not implement fixes.

With no narrower scope, read [Whole-spec audit](references/whole-spec-audit.md) and audit the full current specification.

## Trace the disagreement in both directions

Read the relevant specification, implementation owners, and owning tests end to end.
Follow calls across libraries and output boundaries, including adapters that transform or mask a producer's behavior.
From each requirement, trace the path that should satisfy it.
From implemented public behavior, look back for its specification contract and evidence of intent.
Verify whether declarations such as “design only” and “partially implemented” remain current.

Suppose the contract promises diagnostic severity: the producer attaches it, but an output adapter drops it.
The consumer path reveals partial implementation despite a passing producer test.
Conversely, an approved additional output mode missing from the prose calls for a specification update.
Establish intent from project decisions or other authoritative evidence, not implementation alone.

For each candidate, retain the normative statement or missing contract, producing boundary, downstream transformations, and tests of current or superseded behavior.
Widen searches repository-wide when claiming absence.
Field absence alone cannot prove an adapter forbids a value; inspect its calls and return shapes.
Confirm divergences with an implementation or test oracle; defer suspicions that lack one.

## Choose the disposition

- **Missing feature:** no implementation path satisfies the requirement.
- **Partial implementation:** only some required branches, contexts, or boundaries exist.
- **Undocumented behavior:** intentional public behavior lacks a specification contract.
- **Spec lag:** implementation intentionally advances beyond the prose.
- **Obsolete spec:** authoritative text describes behavior that should no longer exist.

Report each finding:

```text
[TYPE] Short description
  Spec: <file>:<line or stable label> — requirement or missing contract
  Impl: <owner>:<line> — actual behavior
  Tests: <owner>:<line> — current contract, if any
  Impact: <consequence>
  Action: fix implementation | update spec | open issue | already tracked (<ID>) | defer
```

With specification-edit authority, reconcile confirmed spec lag, obsolete spec, and undocumented intentional behavior in the owning specification.
Run its required validation; do not file an issue merely to track that edit.

With filing authority, file issues for missing or partial implementation in the selected tracker under repository issue policy.
Search related open and recently closed issues first: a new specification can supersede a closed issue's contract without duplicating it.
Group by independently implementable ownership boundary and acceptance test.
Requirements needing the same runtime change belong together; representation, diagnostics, and policy can be separate when each can land and verify independently.
Include requirement, observed behavior, evidence, impact, and acceptance condition.
Read back filed issues to verify IDs, bodies, and required labels.
Without the relevant authority, report proposed actions.

Report verified filed and existing IDs, specification edits, deferred suspicions, and checked scope.
Name excluded, skipped, and unexamined areas and unavailable validation; bounded evidence does not establish whole-runtime conformance.
