# Whole-spec audit

Use this procedure when the request covers the full current specification.
Use the specification and tracker selected in [Conformance review](conformance.md#establish-scope-and-authority).

## Coverage ledger

Create a temporary ledger outside tracked files; do not commit it as a second specification or ownership database.

1. Enumerate the full specification from its entry point, following local includes or links that define its normative scope.
   If no entry point exists, enumerate the normative documents in the selected specification directory and state exclusions.
2. Record one row per specification file.
3. For each row, inspect normative prose, implementation owners, owning tests, generated artifacts, and relevant open and recently closed issues.
4. Mark a row complete only after confirming its requirements or recording each divergence, existing issue, or deliberate deferral.
5. Compare the final ledger against the enumerated scope and require no missing, extra, or pending rows.

For each candidate divergence, retain:

- stable specification label or exact normative statement;
- producing implementation boundary and downstream adapters;
- owner tests, including negative and failure-path evidence;
- repository-wide absence evidence when absence matters;
- duplicate search across open and recently closed issues;
- resulting specification edit, existing issue, new issue, proposed action, or explicit deferral.

Narrow searches locate owners; widen before claiming absence.
Inspect calls and return shapes across dataflow boundaries: repository-wide field absence cannot prove that an adapter forbids a value.

## Delegated audits

Give each worker an explicit file list and an exact temporary report path.
Workers may write scratch evidence and reports, but must not edit tracked files or mutate the issue store.
The parent owns authorized specification edits, issue writes, deduplication, and ledger reconciliation.

Require each worker to name its report path and provide one disposition row per assigned file:

- verified boundaries with source, test, or reproduction evidence;
- confirmed divergences and proposed dispositions;
- deferred or unexamined requirements, owners, and failure paths, with the reason and remaining check.

A finding or passing focused test does not establish whole-file coverage.
If a worker stops after a bounded investigation, explicitly defer the remaining scope rather than leaving a row pending or calling it verified.

Reconcile reports against assigned file lists and merge dispositions into the ledger.
Carry deferrals forward unless further evidence resolves them; a complete disposition ledger is not a whole-runtime conformance claim.

## Durable output and closeout

Keep current contracts in the specification and implementation deficits in the selected tracker.
Use the project's existing requirement labels and implementation/test references where available; do not introduce a new metadata system for the audit.
Do not commit dated matrices, issue inventories, command transcripts, or completion checklists.

Before completion:

- verify every enumerated file has a completed disposition row;
- run format-specific validation and focused owner tests for changed surfaces;
- read back filed issues and verify required labels;
- inspect the owned diff without disturbing unrelated work;
- report deferred and unexamined scope, unavailable tools, and checks not run.
