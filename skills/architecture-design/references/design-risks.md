# Design risks

## Applicability

Use these checks before choosing boundaries, or when reviewing the corresponding behavior in a design.
Revisit only risks introduced or changed by the proposed boundary; do not repeat unrelated checks already settled by evidence.
Select sections from the actual subsystem and the proposed change within scope, not from hypothetical future consumers.
Several sections may apply to the same interaction.

| Subsystem behavior | Read |
| --- | --- |
| Shared mutable state, concurrent callers, or delayed results | [Concurrency safety](#concurrency-safety) |
| Queued work, external effects, persistence, or multi-step publication | [Partial failure and recovery](#partial-failure-and-recovery) |
| Asynchronous work, callbacks, queues, or cancellation | [Runtime progress](#runtime-progress) |
| Input size, concurrency, or fan-out can grow, or latency, memory, or cost limits matter | [Resource bounds](#resource-bounds) |
| Proposed changes to reuse, invalidation, or equality/projection boundaries | [Reuse and invalidation](#reuse-and-invalidation) |
| Data or operations cross trust or privilege boundaries | [Trust and authority](#trust-and-authority) |
| Independently deployed consumers or persisted formats | [Deployment and evolution](#deployment-and-evolution) |
| A user or operator must diagnose or recover an operation | [Diagnosability](#diagnosability) |

For each applicable risk, name the requirement, observed constraint, or concrete failure case that can change the design.
Resolve decision-changing uncertainty with the cheapest sufficient evidence; do not invent workload targets or compatibility requirements.
An applicable risk does not by itself justify locks, retries, monitoring, compatibility layers, or other machinery.
Prefer removing the risky interaction or using its existing owner before adding a mechanism.

Concurrency, publication, authority, and recovery contracts belong to
[boundary contracts](boundary-contracts.md#procedure).
Use its questions during design to expose unresolved contracts before choosing boundaries.
Carry the same contract through handoff; revise only unresolved or changed guarantees.
During review, assess the stated contracts and report gaps rather than treating this reference as permission to redesign.

## Concurrency safety

Apply the boundary contract's state ownership, publication, and lifecycle questions to each competing writer or delayed result.
Trace a concrete interleaving, including callback reentrancy and observations that can become stale before an effect commits.
For example, an old operation's delayed result must not overwrite a newer owner's state.
Check all entry points that can perform the same mutation, not just the preferred API path.
An operation completing without deadlock does not establish that its result is correct.

## Partial failure and recovery

Use the boundary contract to state effect outcomes, safe retry conditions, cleanup ownership, and recovery authority.
Trace failure between effects and acknowledgments, including an operation that succeeds remotely but loses its response.
Check that the proposed boundary leaves the recovery owner enough evidence to distinguish failure from an unknown outcome.
Do not infer that retry is safe because the caller received an error, or require transactions or compensation without a concrete need.

For queued or accepted work, trace each occurrence through the selection, processing, persistence, and handoff stages that exist.
Include selected-but-uncommitted batches and failures between ownership transfer and notification.
At each fallible transition, identify where its payload remains recoverable until commit, transfer, or explicit consumption/discard.
An error report is not a discard.

When faithful reconstruction is required, trace the distinctions that must survive through the actual serialization and restore paths.
For example, rebuilding records through a model that retains titles and bodies can still reset comment dates or omit relationships.
A successful import or matching record count does not establish preservation of those distinctions.
Compare existing supported recovery paths with reconstructing records through a narrower model.
Verify restoration without the original store or caches supplying missing data.
An intentionally lossy import may discard what its contract excludes; do not impose byte identity or claim recovery beyond that contract.

## Runtime progress

For asynchronous lifecycles, trace who waits for whom and what enables each transition.
Include callback reentrancy and resources held across waits—locks, admission slots, and bounded queues—not just explicit task dependencies.
Check for deadlocks (circular waits), livelocks (retries without progress), starvation,
and cancellation or shutdown paths blocked by the work they must release.
Distinguish slow external work from a cycle the design cannot resolve.

For example, a callback cannot await a persistence acknowledgment if persistence requires that callback to return.
Check that retries have a changed condition, wake-up source, or finite stopping rule rather than repeating the same blocked action.
Do not treat a timeout as proof that a circular wait is resolved; include any resulting partial effects in the recovery contract.

## Resource bounds

Identify the workload dimensions that determine latency, memory, outstanding work, handles, and external cost.
Trace amplification, such as concurrency multiplied by retained bytes per request or fan-out multiplied by retry attempts.
Establish the applicable bounds and behavior at capacity: backpressure, rejection, degradation, or an explicitly accepted limit.
Check that cancellation and cleanup release the resources attributed to each operation.
Use known workload evidence or a bounded estimate first; request measurement only when it can change the design.
Do not add a benchmark campaign, cache, queue, or configurable limit merely because this section applies.

## Reuse and invalidation

Apply when the proposed design introduces or changes reuse, invalidation, or an equality/projection boundary.
Name the input distinctions ignored by the key or comparison and the consumer work it can suppress.
For a relevant ignored distinction, construct a change that leaves the compared value equal but could change a required observation.
Trace that change through affected consumers, including helpers, diagnostics, and error paths that can observe it.
Check both the data a consumer receives when it runs and the dependency or change signal that causes it to run.
Keeping complete data upstream does not refresh a consumer whose result stays cached.

For example, moving an unchanged broken link within source can leave emitted HTML unchanged but move a warning's source location.
If the checker depends only on the HTML projection, equal HTML can leave a cached warning at the old location.
Reusing emitted bytes can be correct while reusing the warning is not.
The warning needs a valid refresh path: for example, retain its full dependency, use an existing source-location update, or invalidate it conservatively.
Do not classify a consumer as content-only from its final bytes; check whether its helpers or error paths can also emit diagnostics.

When equivalence for affected consumers is unproven, preserve the distinctions in the key/comparison or invalidate conservatively.
This check does not require finer projections.
Add comparison or dependency machinery only when workload evidence shows that saved work justifies its cost.

## Trust and authority

Use the boundary contract to identify which caller authorizes each effect and which component enforces that authority.
Trace untrusted data to operations on files, credentials, processes, networks, or other protected resources.
Check that a component's own privileges do not silently authorize every request it receives.
Include bypass paths and sensitive data in diagnostics or persisted state, not just the main request's validation.
Choose controls for the actual trust boundary; an internal helper does not automatically need a new authentication subsystem.

## Deployment and evolution

Establish required compatibility using [Change with evidence](../../references/change-with-evidence.md#compatibility).
Identify what changes and deploys together, what persists across deployments, and what can be upgraded independently.
Trace an old/new producer-consumer pair and a persisted-data transition when those combinations must be supported.
Check release order, interrupted migration, and rollback where applicable; reverting code may not undo a data change.
If a transition cannot preserve data or authority, name the required migration or rollout decision before endorsing the boundary.
Do not impose mixed-version support or permanent compatibility where no consumer or requirement needs it.

When identities or representations change, trace affected live leases, queued work, and resumable operations as well as stored records.
For example, rewritten issue IDs can leave an active lease unmatched, making ownership appear absent while its worker can still act.
Compare finishing and releasing old work under its existing identities with translating live state, keeping required continuity fixed.
For the chosen transition, explain when old consumers may act or resume and which identities they use.
An empty request queue alone does not establish that old work has ended.
Preserve ownership and already-delivered effects through any live translation rather than treating restart as sufficient.

Treat every compatibility signal as a bounded claim, not proof of behavioral compatibility.
A version, schema, fixture digest, or contract test covers only the behavior it represents;
it can miss changes to timing, ordering, errors, side effects, and lifecycle semantics.
Define the observable guarantees that cross the boundary before selecting compatibility checks.
Do not compare implementation details, mutable content state, or fields whose changes cannot alter those guarantees;
such checks falsely reject compatible peers and add operational churn without protecting the boundary.
Before replacing exact artifact identity or coordinated deployment with a selective compatibility check,
compare the cost of falsely accepting an incompatible pair with the cost of falsely rejecting a compatible pair.
Require evidence for both directions: accepted variation preserves the guarantees,
and rejection identifies a consequential incompatibility.
When the available evidence cannot support either claim, retain matched implementations or require coordinated replacement;
do not invent a weak signal or broad equality check merely to shift operational friction.

## Diagnosability

Identify who must understand an unsuccessful operation and what safe next action they can take.
Check that observable status distinguishes pending work, failure, committed effects, and unknown outcomes when those distinctions matter.
Trace the evidence from the effect owner to the person or component responsible for recovery, without exposing sensitive data.
For example, a caller's generic “request failed” must not imply that repeating a completed external effect is safe.
Reuse existing errors, status queries, or records when sufficient; do not prescribe a monitoring system or retain extra data by default.
