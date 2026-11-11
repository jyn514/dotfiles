# Boundary contracts

Settle changed or unclear guarantees in one evolving contract in existing code or the selected design.
Use applicable questions below and carry settled answers forward.
During review, assess rather than redesign the contract.
For staged new-tool work, update the implementation specification's boundary section against approved requirements without adding scope or observable behavior.
For coupled-worker assignments, use [delegation's shared-contract check](../../delegation/references/shared-contracts.md) without starting architecture work.

## Procedure

### Ownership and publication

Name each mutable state's sole owner, permitted writers, and ownership transfers.
For overlapping calls or late results, state the invariant and how updates are ordered or rejected.
Containment does not establish ownership.

Locate permitted effects and their publication point: what can observers see before and after it, including partial visibility?
Locate each success signal relative to the promised decision or effect.
A health check before caller admission cannot establish successful admission, however often retried.
Observe the promised stage and distinguish successful mutation from presentation.

For interactive changes, identify where interaction occurs, which application receives input, and required focus or interruption behavior.
Assess workflow equivalence separately from a narrower authority boundary.

### Representations, identity, and authority

Identify authoritative raw data and its derived projections.
Validate before projection discards distinctions later checks need.
Resolve layered overrides by source identity before translating winners into effects, so losing definitions leave no effects behind.

Identify objects independently of names and ambient state.
Trace each receiver's namespace, including URI authority, filesystem root, and revision where applicable.
Dropping or re-resolving these components changes behavior.
Pass selection identity with its data when effects must describe one selection, rather than resolving a mutable selector again.
At trust crossings, locate the authority permitting each effect and its enforcement, including alternate entry points.

### Lifecycle, cancellation, and recovery

State lifecycle states, invalid transitions, deadlines, and cancellation owners.
A live owner is not necessarily the currently selected request: dispatched callbacks must still own their effects when only current work may act.
Cancellation alone may not revoke them.

Distinguish pending intent from delivered effects.
Correcting text need not undo a sent keyboard shortcut; resetting bookkeeping does not reverse it.
Specify whether cancellation or correction prevents delivery, changes bookkeeping, or compensates through an authorized supported operation.
Name owners of outstanding work and cleanup after cancellation or shutdown.
Distinguish committed effects, failure, and unknown outcomes.

For destructive or multi-step work, establish recovery authority and interruption evidence, durable when needed and accessible if primary paths move or disappear.
State safe retry conditions, request recognition where necessary, and reconciliation before retrying unknown outcomes.
Choose persistence, deduplication, or compensation only for a supported recovery need.

### Record the contract

Name APIs across which ownership, identity, representation, or lifecycle assumptions must not leak.
Apply [Compatibility](../../references/change-with-evidence.md#compatibility) to independently deployed or persisted contracts.
Prefer falsifiable guarantees such as “X is the sole writer of Y,” with applicable non-goals.
Surface ambiguity before implementation expands around it; record the contract, not a separate inventory or plan.
