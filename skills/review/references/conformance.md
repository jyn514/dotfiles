# Conformance review

## Establish scope and authority

Read repository instructions and contributor documentation for the specification entry point, issue tracker, ownership map, and validation rules.

### Select the tracker and specification independently

Use the documented issue tracker and specification.
If the tracker is not documented, use TicGit (`ti`) and consult the `ticgit` skill for its commands.
If the specification is not documented, start in `doc/` and identify the current normative documents, not obsolete design snapshots.
Apply these fallbacks independently; a documented tracker does not override the specification fallback or vice versa.
If the specification is missing or ambiguous, or the tracker is unavailable, report the limitation rather than inventing requirements or silently switching trackers.

### Choose bounded or whole-spec scope

Start with files, sections, symbols, tests, commands, or revisions named by the request.
For a named revision, inspect its changes first; treat a spec-changing revision as the requirement delta and audit the current tree against the resulting specification.
Only when the request gives no narrower scope, audit the current specification using [Whole-spec audit](whole-spec-audit.md).
Use the current specification and issue history as the gap ledger.

A review-only request authorizes findings, not specification edits or issue writes.
When asked to reconcile the specification or file bugs, perform those actions within the requested scope.
Do not implement fixes as part of this skill.

## Audit

1. Read the relevant specification, implementation owners, and owning tests end to end.
   Follow calls across libraries and output boundaries.
   For the full specification, use the temporary coverage ledger in the whole-spec procedure; status-marker searches do not establish coverage.
2. Find declarations such as “design only” and “partially implemented” and verify that each remains current.
3. For every candidate, identify the normative statement, producing implementation boundary, later adapters that mask or transform behavior, and tests asserting current or superseded behavior.
   Gather repository-wide absence evidence when the claim depends on absence.
4. Classify only confirmed divergences.
   Defer suspicions without an implementation or test oracle.
   Establish intent from project decisions or other authoritative evidence; implementation alone does not prove the specification is wrong.
5. Resolve authorized findings as described below; otherwise report proposed actions.

Useful signals include normative “must”/“shall” language, enumerated options, diagnostic contracts, executable examples, TODO/FIXME markers, and tests pinning contradicted behavior.

## Classify findings

- **missing feature** — no implementation path satisfies the requirement.
- **partial implementation** — only some required branches, contexts, or boundaries exist.
- **undocumented behavior** — intentional public behavior lacks a specification contract.
- **spec lag** — implementation is intentionally ahead of the prose.
- **obsolete spec** — authoritative text describes behavior that should no longer exist.

Report each finding as:

```text
[TYPE] Short description
  Spec: <file>:<line or stable label> — requirement
  Impl: <owner>:<line> — actual behavior
  Tests: <owner>:<line> — current contract, if any
  Impact: correctness | compatibility | diagnostics | documentation | cleanup
  Action: fix implementation | update spec | open issue | already tracked (<ID>) | defer
```

## Resolve divergences

When edits are authorized, update confirmed spec lag, obsolete spec, and undocumented intentional behavior in the owning specification and run its required validation.
Do not file an issue merely to track an authorized specification edit.

When filing is authorized, file issues for missing or partial implementation using the selected tracker and repository issue policy.
Search related open and recently closed issues first: a new specification may supersede a closed issue's contract without duplicating it.
Group issues by independently implementable ownership boundary and acceptance test, not by the number of specification statements.
Combine requirements needing the same runtime change; separate representation, diagnostics, and policy when each can land and verify independently.
Include the normative requirement, observed behavior, evidence, impact, and acceptance condition in each issue.
Read back filed issues to verify their IDs, bodies, and required labels.

Report verified filed IDs, existing IDs, specification edits, deferred suspicions, and checked scope.
Identify excluded, skipped, and unexamined areas and unavailable validation; a bounded audit does not establish whole-runtime conformance.
