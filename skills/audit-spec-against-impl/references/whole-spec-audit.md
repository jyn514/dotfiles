# Whole-spec audit

For a full-specification audit, use the specification and tracker selected in [Establish scope and authority](../SKILL.md#establish-scope-and-authority).

## Account for the full scope

Create a temporary ledger outside tracked files, with one row per specification file.
Enumerate from the specification entry point, following normative includes and links.
Without an entry point, enumerate normative documents in the selected directory and state exclusions.

For each row, inspect normative prose, implementation owners, owning tests, generated artifacts, and relevant open and recently closed issues.
Retain the [finding evidence](../SKILL.md#trace-the-disagreement-in-both-directions), including negative and failure-path tests, and the duplicate search.
Record confirmed requirements and each divergence's disposition: specification edit, existing or new issue, proposed action, or deliberate deferral.
A status-marker search or passing focused test does not establish file coverage.

Before closing the ledger, compare it with the enumeration: every file needs a completed disposition, with no missing, extra, or pending rows.
Explicit deferrals account for unfinished work; they do not verify it.

## If delegating

Give each worker an explicit file list and exact temporary report path.
Workers may write scratch evidence and reports, not tracked files or the issue store.
The parent owns authorized specification edits, issue writes, deduplication, and ledger reconciliation.

Require workers to return their report path and one disposition row per assigned file:

- verified boundaries with source, test, or reproduction evidence;
- confirmed divergences and proposed dispositions;
- deferred or unexamined requirements, owners, and failure paths, with reasons and remaining checks.

Reconcile reports against assignments and merge them into the ledger.
Explicitly defer unfinished scope and carry deferrals forward until evidence resolves them.
A complete ledger is not a whole-runtime conformance claim.

## Close out

Keep current contracts in the specification and implementation deficits in the selected tracker.
Reuse existing requirement labels and implementation/test references rather than creating audit metadata.
Do not commit the ledger, dated matrices, issue inventories, command transcripts, or completion checklists.

For changed surfaces, run format-specific validation and focused owner tests, then inspect the owned diff without disturbing unrelated work.
Follow the main skill's [disposition and reporting requirements](../SKILL.md#choose-the-disposition), including issue readback and deferred, unexamined, or unvalidated scope.
