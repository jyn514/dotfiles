# Deployment and evolution

Use these checks when components update independently, persisted state outlives code, or live work can survive a deployment.
They apply to architecture decisions and operator workflows; they do not require support for version combinations outside the task's requirements.

Apply [Compatibility](change-with-evidence.md#compatibility) to establish what deploys together, persists, or upgrades independently.
Trace required old/new pairs and persisted-data transitions through release order, interrupted migration, and rollback where applicable.
Reverting code may not undo data changes.
Name rollout or migration decisions needed to preserve data or authority before endorsing the boundary; mixed-version support needs an actual requirement.

Identity or representation changes also affect live leases, queued work, and resumable operations.
Rewritten issue IDs can orphan a live lease, making ownership appear absent while its worker can still act.
Compare finishing and releasing old work under existing identities with translating live state.
Establish when old consumers can act or resume and which identities they use; an empty queue does not prove old work ended.
Translation must preserve ownership, continuity, and already-delivered effects; restart alone does not establish this.

Define observable guarantees before choosing compatibility signals.
Versions, schemas, fixture digests, and contract tests protect only represented behavior; timing, ordering, errors, effects, and lifecycle can escape them.
Exclude implementation details, mutable contents, and fields that cannot alter those guarantees.
Before replacing exact artifact identity or coordinated deployment with a selective check, compare false acceptance and rejection costs.
Require evidence that accepted variation preserves guarantees and rejection identifies consequential incompatibility.
Otherwise retain matched implementations or coordinated replacement rather than a weak signal or broad equality check.
