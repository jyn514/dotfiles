# Shared contracts for coupled workers

Before assigning coupled implementation, identify decisions one worker could make that would change another worker's inputs, outputs, or invariants.
Separate file ownership does not establish independence.

State the shared representation, producer and consumer responsibilities, and failure behavior.
Confirm both assignments use that contract.
Reuse existing code or a short declaration; do not require a new document, exhaustive API specification, or architecture workflow.
If a consequential contract remains unclear, consult only the applicable [boundary-contract questions](../../architecture-design/references/boundary-contracts.md).

Resolve shared choices before dependent implementation.
If unresolved, delegate investigation or contract design instead; continue independent work.
Recheck affected assignments when the contract changes.
If a running tool imports or invokes helpers from the working copy, create and test a new helper before changing a live caller to use it.
Sequence coupled workers accordingly: confirm the helper exists and passes its focused check before the caller worker switches the import or invocation.
A final test after both edits cannot prevent an intermediate missing helper from disabling the tools needed to finish or recover.
Independent investigation or review needs no shared-contract declaration unless it defines or changes a boundary.

For example, workers preparing pronunciation analyses and executable rule data may own separate files but both depend on sound-unit identity and matching semantics.
Settle those representations before implementing their producers and consumers in parallel.
Collecting pronunciation provenance and specification examples can proceed independently while that contract remains unresolved.
