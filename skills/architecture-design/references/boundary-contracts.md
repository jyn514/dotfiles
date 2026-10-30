# Boundary contracts

Consult the applicable questions only when ownership, effects, representation, or lifecycle contracts remain unclear or change.
Maintain one evolving contract in existing code or the selected design; do not start a separate declaration phase or repeat settled analysis at handoff.
During review, assess the stated contract without treating these questions as permission to redesign.

For a staged new-tool workflow, update the implementation specification's boundary section using approved requirements and the design contribution.
Do not add product scope or observable behavior.
For coupled-worker assignments, use [delegation's shared-contract check](../../delegation/references/shared-contracts.md) without starting an architecture workflow.

## Procedure

1. Identify the sole owner and permitted writers of each mutable state.
   Where calls overlap or results arrive late, state the invariant and how conflicting or stale updates are ordered or rejected, including ownership transfer.
2. Identify where side effects are permitted and which effects form one publication.
   State the commit or visibility point and what observers may see before and after it; name any partial visibility intentionally allowed.
   Name what each success signal establishes by locating its producer relative to the required decision or effect.
   For example, a public health check can succeed before caller admission; retrying it cannot establish that admission succeeded.
   Use an observation of the required stage instead, unless the earlier stage is itself the promised outcome.
   For interactive changes, compare workflow separately from authority.
   State where interaction occurs, which application receives input, and any changes in focus or interruption behavior.
   A narrower authority boundary does not make a different workflow equivalent; identify which interactions must remain unchanged.
3. Identify authoritative raw representations and every derived, normalized, serialized, or displayed projection.
   Validate before a projection can discard distinctions needed by later checks.
   When layered inputs define overrides, resolve effective values by their source identities first.
   Then translate the winning values into consumer effects, even when that translation changes their shape or names.
   Otherwise a losing definition can leave effects that the winning projection no longer replaces.
4. Identify object identity independently of names and ambient state: filesystem identity, selected revision, provider, platform, and configuration scope where applicable.
   Trace which namespace each receiver uses to resolve a name, including URI authority, filesystem root, and revision.
   Treat dropping or re-resolving those components as a behavior change, not string cleanup.
   When multiple effects must describe one selection, pass its identity with its data instead of resolving a mutable selector again.
   At trust crossings, state whose authority permits the effect and where it is enforced, including alternate entry points.
5. Identify lifecycle states, invalid transitions, deadlines, and cancellation owners.
   Distinguish a live owner from the currently selected request or scheduled action.
   Where only current work may act, check that dispatched callbacks still own their effects; cancellation alone may not revoke them.
   Distinguish pending intent from effects already delivered.
   Undoing local state does not itself reverse an external effect: correcting text need not undo a keyboard shortcut already sent.
   State whether cancellation or correction prevents pending delivery or only changes bookkeeping.
   If it reverses or compensates for a delivered effect, identify the supported operation and its authority.
   State who owns outstanding work and resource cleanup after cancellation or shutdown, and whether failure can leave an effect committed, failed, or outcome-unknown.
6. For destructive or multi-step work, identify recovery authority and the evidence available after interruption, including durable state when needed.
   Ensure required recovery evidence remains available if primary paths move or disappear.
   State which effects can safely retry, how repeated requests are recognized if necessary, and what must be reconciled before retrying an unknown outcome.
   Do not require persistence, deduplication, or compensation without a supported recovery need.
7. Identify APIs across which ownership, identity, representation, or lifecycle assumptions must not leak.
   Name independently deployed or persisted contracts and their required compatibility using
   [Change with evidence](../../references/change-with-evidence.md#compatibility).
8. Keep the declaration short enough to review before coding.
   Include only applicable contracts; reuse settled ones rather than inventing new policies or implementation machinery.

## Output

Summarize the applicable answers in the existing contract, with explicit non-goals.
Omit unaffected categories; this is not a required inventory or a request for a separate document.

## Constraints

- This is not an implementation plan.
- Prefer falsifiable statements such as “X is the sole writer of Y” over vague principles.
- Distinguish containment from ownership, successful mutation from successful presentation, and failure from unknown outcome.
- If a boundary cannot yet be stated clearly, stop and surface the ambiguity before implementation expands around it.
