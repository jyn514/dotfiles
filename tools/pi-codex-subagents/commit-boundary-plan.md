# Preserve commit-boundary checkpoints across worker hibernation

## Contract

A logical worker should retain its commit-boundary checkpoint when its child process exits after settling and `send_message` starts that same worker again.
Today, `core.ts` terminates settled children and resumes their transcripts in fresh processes; the boundary controller’s closure disappears with the old process.
Keep one checkpoint `C = { repository, commit, parent } | null` per parent-session ID and stable worker ID in the parent manager’s memory.
The manager owns transport and lifetime; the boundary extension owns interpreting, capturing, checking, restoring, and retiring `C`.

This is not persistence across parent shutdown or reload.
Do not put checkpoints in `AgentInfo`, transcripts, custom session entries, suspension records, or other disk state.
Do not add automatic commits, retained source copies, shell interception, a service, retries, recovery tickets, or longer-lived child processes.

## 1. Add the narrow manager/helper handoff

Change `core.ts` and `child-helper.ts`, add a checkpoint-specific transport contract module, and include that module in `package.json`’s published files.
Keep retained state outside persisted `AgentInfo` and process-scoped `LiveAgent`.
Use the existing transport patterns: an internal extension command through `sendCommand` for restoration, and a reserved `ctx.ui.notify` prefix for child exports, following `child-link.ts` and the notification interception in `core.ts`.
Do not reuse disk-based `CONTROL_ENTRY` receipts or broaden this into a generic extension-state framework.

Represent an export as either a checkpoint or explicit null, with a separate missing-export sentinel in the receiving process state.
Validate the envelope and checkpoint shape without interpreting repository history.
Accept notifications only from the current owned `LiveAgent`, before termination, and intercept them before ordinary broadcasting or logging.
At each native RPC `agent_settled`, replace the retained value with that process’s export; missing or malformed export drops the previous value rather than reusing it.
Clear the pending export after consumption and invalidate retained state when another run starts in a still-live child.

When launching a replacement process, consume the retained value immediately so a crash cannot leave an older copy available for another restart.
After startup synchronization through `get_state`, but before the first prompt or release of a restored-held child, send the restore command, including explicit null when nothing was retained.
Require synchronous controller application before the command completes, followed by an explicit helper restore result on the same private notification transport.
RPC command completion alone is not an acknowledgment; a missing or malformed result fails startup before any prompt or release.
If a non-null checkpoint cannot be restored, drop it and report the unavailable integration without creating a retry obligation.
A worker with no retained checkpoint and no boundary controller is normal; restoration is a silent no-op.

Preserve transferred state only for normal settled hibernation.
Before other termination paths—interrupt, timeout, startup failure, unexpected exit, or shutdown—clear retained and pending state; ignore late exports from those processes.
Clear the manager’s entire map on shutdown.

## 2. Connect the domain-owned boundary controller

Companion work belongs in `config/pi-agent/pi-extensions/commit-boundary.ts` and its tests within a separately writable dotfiles checkout.
Do not import that external path into this package.
Keep integration in `createBoundaryController`, which already serves both native tools and `guest-tools.ts`; `commit-boundary/operations.mjs` should retain its existing checking semantics.

Register checkpoint-specific synchronous event-bus listeners during extension loading.
The helper’s restore command invokes the controller through that bus after startup resets; restoration synchronizes session/cwd and establishes a fresh controller lifetime.
The controller publishes its current checkpoint at the end of its existing awaited `agent_settled` handler, after capture, including no-write turns and explicit null after retirement or abort.
Do not export from the helper’s earlier settled handler or publish shutdown reset as a replacement handoff.

Installed Pi’s `agent-session.ts` awaits extension settled hooks before emitting the RPC settled event, while `event-bus.ts` does not await asynchronous listeners.
Publishing synchronously from the completed controller hook therefore avoids an asynchronous export request after RPC settlement and its admission race.
Do not rely on helper-first loading: `sandbox-host-pi` prepends dotfiles index and guest-tools before supplied extensions.

The manager already explicitly loads `child-helper.ts` on every launch.
Sandbox-host workers already receive index plus guest-tools; native workers disable extension discovery and must explicitly configure `commit-boundary.ts` through existing defaults/template extensions.
Do not silently load dotfiles extensions for other package users.

## Acceptance and verification

Add a manager-checkpoint phase to `test/run-source-tests.ts`, using the real RPC child in `test/source-rpc-child.ts` and a narrow checkpoint peer fixture.
In dotfiles, extend the controller tests in `tests/pi/commit_boundary_test.ts` and the actual native/guest regressions in `tests/pi/native_commit_boundary.mjs` and `tools/codex-sandbox/tests/commit_boundary_test.ts`.
Keep those regressions covered by their existing default adapters, `tests/native/test_native_commit_boundary_session.py` and `tests/native/test_native_commit_boundary.py`.

- Write, settle, and verify process exit; resume the same worker ID and transcript with a different PID, with `C` restored before its first edit.
- Trigger a warning that blocks the write and retires `C`; settle without a successful write, restart again, and verify the next edit has no checkpoint.
- Verify no-write turns preserve `C`, later successful writes replace it, and workers/parent sessions remain isolated.
- Verify missing, malformed, interrupted, or crashed handoffs, restore failure, and late old-process exports never resurrect an earlier checkpoint.
- Verify parent shutdown/recreation with the same transcripts restores nothing, and no checkpoint appears in session, info, or group files.
- Exercise startup-reset ordering, stale controller lifetimes, aborted settlement, and explicit null in controller tests.

Run focused cases through the source-backed driver, then `bun run test:subagents`.
Ordinary unconfigured `bun test` skips native coverage; installed Pi distribution tests are not substitutes for the source runtime described in `test/SOURCE-CORE.md`.
