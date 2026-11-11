# Design risks

## Applicability

Choose checks for introduced or changed risks in the actual subsystem, including during review.
Several may apply to one interaction.

| Subsystem behavior | Read |
| --- | --- |
| Shared state, concurrent callers, delayed results | [Concurrency safety](#concurrency-safety) |
| Queued work, external effects, persistence, multi-step publication | [Partial failure and recovery](#partial-failure-and-recovery) |
| Asynchronous work, callbacks, queues, cancellation | [Runtime progress](#runtime-progress) |
| Growing inputs, concurrency, fan-out, resource limits | [Resource bounds](#resource-bounds) |
| Changed reuse, invalidation, equality, projections | [Reuse and invalidation](#reuse-and-invalidation) |
| Trust or privilege crossings | [Trust and authority](#trust-and-authority) |
| Independent deployments, persisted formats | [Deployment and evolution](#deployment-and-evolution) |
| Operator diagnosis or recovery | [Diagnosability](#diagnosability) |

Ground each check in a requirement, observed constraint, or concrete failure case that can change the design.
Choose workload and compatibility targets from requirements, not this checklist.
Compare removing the interaction or using its existing owner before adding machinery.
Resolve risks with the cheapest sufficient evidence and record unresolved or changed guarantees in the [boundary contract](boundary-contracts.md#procedure).
During review, report contract gaps rather than redesigning the system.

## Concurrency safety

Trace an interleaving of competing writers or delayed results, including reentrant callbacks and observations stale before commit.
Apply ownership, publication, and lifecycle contracts at every mutation entry point so an old result cannot overwrite a newer owner's state.
Completion without deadlock does not establish correctness.

## Partial failure and recovery

Trace failures between effects and acknowledgments, including remote success with a lost response.
Use the boundary contract to establish outcomes, retry conditions, cleanup, and recovery authority.
The recovery owner needs evidence distinguishing failure from unknown outcome; a caller error alone cannot justify retry, transactions, or compensation.

For queued work, locate each occurrence's recoverable payload through selection, processing, persistence, and handoff.
Include selected-but-uncommitted batches and failure between transfer and notification.
Preserve the payload until commit, transfer, or explicit consumption/discard; an error report is not a discard.

For reconstruction, follow required distinctions through serialization and restoration.
Rebuilding titles and bodies can reset comment dates or omit relationships despite successful import and matching counts.
Compare supported recovery with reconstruction through a narrower model.
Verify restoration without the original store or caches supplying missing data.
An intentionally lossy import need preserve only what its contract promises, not byte identity.

## Runtime progress

Trace waits and their enabling transitions, including held locks, admission slots, bounded queues, and reentrant callbacks.
Check cycles, starvation, retries without progress, and cancellation or shutdown waiting on work they must release.
Distinguish slow external work from an unresolvable cycle.

A callback cannot await persistence if persistence needs that callback to return.
Retries need a changed condition, wake-up source, or finite stopping rule.
A timeout alone does not establish that a circular wait is resolved; include resulting partial effects in the recovery contract.

## Resource bounds

Identify what drives latency, memory, outstanding work, handles, and external cost.
Trace amplification, such as concurrency × retained bytes or fan-out × retries.
Establish required bounds, capacity behavior, and release on cancellation and cleanup.
Use known workloads or bounded estimates; measure when it can change the design rather than automatically adding benchmarks, caches, queues, or configurable limits.

## Reuse and invalidation

Construct a relevant change that keeps a proposed key or comparison equal but could change a required observation.
Follow every consumer whose work equality suppresses, including helpers, diagnostics, and errors.
Check both its data and the signal that makes it run; complete upstream data cannot refresh a cached consumer alone.

For example, moving an unchanged broken link can leave HTML equal but move a warning's source location.
An HTML-only dependency can retain the old warning location.
Reusing emitted bytes can be correct while reusing the warning is not.
Keep a refresh path through the full dependency, a source-location update, or conservative invalidation.
Inspect helpers and errors before calling a consumer content-only.

When equivalence is unproven, preserve distinctions or invalidate conservatively.
Finer projections are optional; additional comparison machinery needs workload evidence that saved work earns its cost.

## Trust and authority

Trace untrusted data to protected effects, including bypass paths and sensitive diagnostics or persisted data.
Use the boundary contract to name the authorizing caller and enforcing component; privileges do not authorize every request.
Choose controls for that crossing, not a new authentication subsystem for every helper.

## Deployment and evolution

Apply [Compatibility](../../references/change-with-evidence.md#compatibility) to establish what deploys together, persists, or upgrades independently.
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

## Diagnosability

Identify who must understand an unsuccessful operation and their safe next action.
Trace required evidence from effect owner to recovery owner without exposing sensitive data.
Distinguish pending work, failure, committed effects, and unknown outcomes so “request failed” cannot imply that repeating an effect is safe.
Use existing errors, status queries, or records when sufficient.
