# Blocked-goal resumption implementation plan

Status: implemented; local and selected-host verification pass.
No live activation or release is authorized.

## Contract

Let the agent explicitly reactivate a blocked goal when new information resolves its recorded dependency.
For example, the user resolves conflicting requirements in an ordinary message, without needing `/goal resume`.
A running subagent is not a dependency block: use `wait_agent`.
Blocking still stops automatic continuation; add no polling, timers, subscriptions, or model calls to detect resolution.

| Model operation | Allowed current status | Required input and result |
| --- | --- | --- |
| `update_goal(status: "blocked")` | Active | Non-empty dependency `reason`; reject paused goals with an error suggesting paused annotation. |
| `update_goal(status: "paused")` | Paused | Non-empty `reason`; annotate the saved goal without changing status or usage. |
| `update_goal(status: "active")` | Blocked | Matching `goal_id`, non-empty resolution `reason`, non-aborted call, and remaining budget; activate and clear the blocked reason. |
| `update_goal(status: "complete")` | Existing completion-eligible statuses | Keep current completion semantics; blocked completion remains rejected and repeated completion remains idempotent. |

Keep existing complete/block inputs unchanged; expose `goal_id` only for unblocking.
The agent judges whether evidence resolves the dependency within existing authorization; validation cannot prove that judgment.
Keep the response-to-goal guard and validate the current state immediately before synchronous publication.
Rejected requests do not mutate the saved goal, except that existing accounting may independently settle usage and enforce the budget.

Human `/goal pause` also accepts blocked goals and prevents later agent unblocking.
An interrupted ordinary goal-bound turn cannot perform a pending unblock; if activation already committed, abort pauses it.
Do not let stale-continuation or replaced-goal aborts change an unrelated goal.
Existing command, UI-confirmed, and provider recovery resume paths retain their authority.
Do not allow paused-to-blocked-to-active to bypass a human pause.

Tool unblocking continues the current turn, without queuing a duplicate command-resume turn.
Start active elapsed-time accounting at activation without assigning ownership of the calling response anew.
A response that began blocked is not retroactively charged; later active responses count once.

### Storage and ownership

Add optional `pausedReason` to `ThreadGoal` and its tool projection; retain `blockedReason` and old snapshot compatibility.
Trim annotation text; an unchanged annotation succeeds without changing its timestamp or adding an entry.
Show pause reasons in `/goal` and tool output, not the compact footer, and preserve them through objective edits and reconstruction.
Human blocked-to-paused carries the dependency explanation into `pausedReason` and removes `blockedReason`.
Clear `pausedReason` when leaving paused, including command, provider, UI-confirmed resumption, and completion.

`state.ts` owns validation and derived snapshots; the existing controller/persistence path publishes native custom entries.
The runtime owns accounting and continuation delivery; reuse sufficient existing facilities without requiring a new annotation transition.
Pausing already clears active clocks and continuation state, and ordinary input cancels provider retries before the annotation turn.
Those repeated cleanups do not establish a need for special preservation machinery.
No new status, dependency model, configuration, runtime dependency, or persisted audit format is needed.
The unblock explanation remains in the native tool-call record.

## Implementation steps and logical commits

### 1. `Preserve pause authority while recording dependency reasons`

- Update `src/types.ts`, `src/state.ts`, and `src/format.ts` for pause reasons, compatibility, display, and cleanup.
- Extend the existing tool/controller path with paused annotation, separate from terminal response settlement.
- Reject model paused-to-blocked updates and provide the annotation instruction in the error.
- Update `tools/block-decision-replay.ts` and its tests alongside the newly exposed status.
  Replay starts with an active goal; a paused annotation is ineligible and must be inconclusive, not successful block avoidance.
  Use the registered candidate declaration in the regression rather than relying only on the old copied schema.
- Update tool guidance and `docs/reference.md`; land focused tests with the behavior and pass `npm run check`.

### 2. `Resume resolved blocked goals without bypassing human stops`

- Add blocked-only activation with identity, reason, cancellation, and budget checks in the tool/domain/runtime path.
- Implement human blocked-to-paused and applicable abort handling without widening recovery-pause behavior.
- Keep accounting ownership and native stale-work protection; do not use command resume's extra hidden-turn delivery.
- Extend replay coverage to active requests on its already-active seed, which are also ineligible despite a valid ID and reason.
  Keep these requests inconclusive without building a transition simulator.
- Update standing guidance, full/compact continuations, README controls, and reference docs together.
  Check `prompts/create-goal.md` and goal-scope fixtures for stale manual-only blocked-resume claims.
- Land runtime/native acceptance tests with the behavior and pass the required checks.

## Verification

Use a finite transition matrix and focused regressions in the existing Node suites; no generator or reference model is required.

| Case | Expected result |
| --- | --- |
| Valid paused annotation, repeated annotation, invalid source status, and missing/blank reason | Reason-only update or rejection as applicable; duplicate adds no entry. |
| Annotation after ordinary input on a provider-paused goal | Input already cancels its retry; annotation leaves the goal paused and saved usage unchanged. |
| Paused-to-blocked attempt followed by unblock | Reject the first update and prevent bypassing the pause. |
| Blocked goal plus valid resolution call | Same goal activates; reason clears; no duplicate queued resume turn. |
| Unrelated input, missing/wrong ID, blank reason, absent/replaced/complete/paused/budget-limited goal | No implicit resumption; invalid unblock requests fail. |
| Human pause and cancellation before/after unblock | Human stop wins; an aborted tool signal cannot activate the goal. |
| Late abort or stale accepted continuation | Replacement goals and legitimate ordinary input remain unaffected. |
| Block/unblock, native child calls, and budget crossing | Exact-once accounting; budget cannot be bypassed. |
| Reload, tree/fork, compaction, shutdown, and objective edits | Reasons survive where applicable; inactive goals create no new work. |
| Existing command, provider, and UI-confirmed resume | Existing authority and delivery survive; old pause reasons clear. |
| Historical snapshots and current tool projection | Old records load; new reasons survive round trips and display. |
| Replay using registered extended declarations | Ineligible paused/active requests are inconclusive; valid ordinary-tool requests remain alternative actions. |

Use the existing focused state, transition, controller, persistence, command, prompt, replay, and native lifecycle suites.
Verify cancellation and delivery with native faux-provider cases, not only direct harness calls.
Run `npm run check` with isolated HOME/agent state and a short temporary directory as documented in `docs/development.md`.
Tests must not modify checked-in artifacts, real user state, or shared services, and must not call a live model.
Host-sensitive qualification uses the existing workflow's exact official and maintained-fork targets and retained SDK/CLI evidence.
Locked development dependencies alone do not qualify host compatibility; manual interactive evidence remains a release requirement.
Deterministic tests do not prove the model correctly interprets clarification or approval as resolving a dependency.

## Implementation evidence

The implementation adds neither an annotation-specific transition nor a generated action-sequence framework.
The isolated `npm run check` passes all 457 tests, TypeScript checking, and the package dry run.
The retained local log is `.artifacts/blocked-goal-verification/local/check.log`.

Qualification also passes all 457 tests, TypeScript, and native Git/packed consumer CLI checks on official Pi 1.3.0
and maintained fork `997a2575e0dde7c6690024184feec970d395f9b4`, using their actual companion graphs.
Both lanes use Node 24.16.0 and npm 12.2.0, with workflow-pinned automation and once-resolved host identities.
Exact SDK/CLI hashes, source manifests, and results are retained in `.artifacts/blocked-goal-verification/final-summary.json`.
Only this document's status and qualification result were updated after qualification;
production source, tests, and shipped files remain identical to the qualified snapshot.

| Acceptance area | Evidence |
| --- | --- |
| Paused annotation, admission, trimming, duplicate no-entry, display, and old snapshots | `test/paused-reasons.test.ts` |
| Ordinary provider-paused input cancels retry before annotation | `test/blocked-goals.test.ts` |
| Blocked-only activation matrix, identity/reason/budget refusal, elapsed time, and replacement protection | `test/blocked-resumption.test.ts` |
| Native direct/child activation, exact-once response accounting, no duplicate resume, and later budget crossing | `test/native-lifecycle.test.ts` |
| Native cancellation before/after activation, human pause before publication, and pause persistence through compact/reload/fork | `test/native-lifecycle.test.ts` |
| Command, provider-auto-resume, and UI-confirmed resume preserve authority and clear annotated reasons | `test/paused-reasons.test.ts`, `test/continuation.test.ts` |
| Source-registered replay declarations reject ineligible status requests as avoidance evidence | `test/block-decision-replay.test.ts` |
| Completion idempotence, native recovery, shutdown, tree reload, and stale-work protections | Existing persistence, recovery, native lifecycle, and stale queued-work suites in `npm run check` |

Independent review found no blocking implementation issue.
Its accounting-documentation correction and reason-specific resume and combined budget-crossing coverage gaps are resolved.
Native tool-hook cancellation initially reproduced an interrupted goal remaining blocked because its assistant message still said `toolUse`.
The same native regression passes after terminal handlers also inspect the current abort signal, following stale-work filtering and goal-identity checks.
Manual interactive and model-judgment evidence remain outside this implementation verification; neither has been claimed.
