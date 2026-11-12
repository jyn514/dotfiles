# Guest work cleanup implementation plan

Implement the selected [guest work storage cleanup contract](spec/launcher-interface.typ#guest-work-cleanup).
This plan authorizes no implementation or cleanup of existing volumes.
After the final consumer exits, snapshot tracked JJ workspaces and delete their ignored files inside the guest-only volume.
Preserve tracked content, JJ metadata, registrations, the volume, and unclassified files outside those workspaces.

## Existing path

`workspace_layout.py:workspace_work_volume()` derives stable volume identity from the host checkout.
`codex-sandbox:prepare_workspace_work_volumes()` creates owned volumes for the active checkout and launcher dotfiles; `agent_repository_mounts()` mounts them.
`sandbox-proxies.py` mounts those same volumes into trusted JJ services.
Consequently distinct active projects can share the dotfiles volume without sharing a session lifetime.

`codex-sandbox:cleanup()` removes the agent container before calling `CommandProxySession.finish()`.
`proxy_session.py:SessionLock.finish()` establishes final ownership of one session, not one volume.
Successful session exit can defer trusted-service teardown through `command_proxy_session.py:_defer_cleanup()` and `sandbox-proxies.py:idle_cleanup_main()`.
A remaining JJ proxy is still a volume consumer; cleanup must follow its teardown or explicitly coordinate its final maintenance access.
Do not attach deletion directly to each Pi exit or use Docker volume pruning.

## Implementation steps

1. Extend launcher-owned storage lifetime at volume identity, covering preparation, agent/proxy admission, failed startup, ordinary exit, deferred teardown, reset, and restart.
   Reuse the existing coordination/lifetime lock pattern where applicable, but do not reuse session identity for a volume shared across sessions.
   Acquire multiple volume identities in deterministic order and exclude admission throughout final maintenance.
   Validate owned runtime mounts as well as cooperative holders before deletion, including containers started by older launcher versions.
   Unknown consumers mean retain files and report incomplete cleanup.

2. Add final maintenance through the existing runtime and trusted JJ execution facilities, with the volume mounted at its accepted guest path and backing metadata available.
   Enumerate registered workspace roots inside that volume and validate their backing repository; do not infer workspace authority from arbitrary directory names.
   Snapshot each workspace with native JJ behavior under the existing backing-repository request lock, without the ordinary author-update hooks.
   Use the pinned JJ version's supported file/ignore inspection to classify deletion candidates after snapshotting.
   Preserve tracked files that match ignore rules, nested workspaces, metadata, and unclassified paths.
   Delete without following symlinks or traversing nested mounts; a failed discovery or snapshot leaves affected files intact.
   Keep the maintenance consumer and coordination alive until all deletion finishes, then release them before admitting new work.

3. Connect maintenance completion and errors to existing launcher/deferred-cleanup reporting.
   Preserve the original session failure when cleanup also fails; identify retained storage and recovery action.
   Update the operator guide's persistence description and mark the spec implemented only after runtime acceptance.
   No new dependency, global prune job, host shutdown hook, or automatic commit is needed.

## Verification

Extend existing launcher/runtime and proxy-session suites plus `repository_mounts_integration.py` and the shared-workspace fixtures.
Run them through `dev/test-environment`, using owned disposable checkouts and volumes only.

| Case | Required observation |
| --- | --- |
| Two sessions share one volume | First exit deletes nothing; final consumer teardown triggers maintenance once. |
| Agent exits but deferred JJ proxy remains | No deletion while the proxy remains a consumer. |
| New launch races final teardown | Admission waits until maintenance completes; no writes race deletion. |
| Tracked edits, additions, deletions, conflicts | Snapshot preserves the pending change and authorship without committing. |
| Ignored output beside tracked files matching ignore rules | Only ignored, untracked output disappears; tracked bytes remain. |
| Multiple/nested JJ workspaces | All registered in-volume workspaces survive, including metadata and registrations. |
| Symlink or nested mount leads outside the volume | External canaries and host-backed files remain unchanged. |
| Unclassified files elsewhere in the volume | Files remain. |
| Discovery/snapshot/ownership failure | Affected files remain and incomplete cleanup is reported. |
| Failed startup, reset, restart, interrupted teardown | No deletion with a live consumer; later exclusive cleanup can retry safely. |
| Existing containers from an older launcher | Runtime mount inspection prevents mistaken final ownership. |

Use real JJ and container mounts to establish snapshot preservation and filesystem boundaries; mocked command arguments alone do not establish either.
Check subsequent launch can reopen each preserved workspace and observe the snapshotted contents.
Do not use authoritative user state as a test fixture.

## Resolved implementation decisions

JJ 0.46 supplies registered roots through `workspace list -T 'json(root)'` and tracked paths through `file list -T 'json(path)'`.
It has no ignored-file listing command; maintenance uses Git's compatible ignore matcher with an empty temporary index, subtracting JJ's tracked paths.
Git never performs deletion, and JJ snapshot failures prevent deletion.
`work_cleanup_guest.py` snapshots and classifies every selected workspace before unlinking candidates.

`work_storage.py` serializes preparation, container admission, and final maintenance with short per-volume locks.
Runtime mount inspection supplies consumer lifetime, including older containers and deferred proxies, without persisted consumer counters.
After `reset_session()` stops services, maintenance passes ordinary admission for the recorded runtime and uses the accepted immutable agent image.
Recovery-only runtimes retain their execution prohibition.
Deferred teardown keeps its existing five-minute timeout and saves diagnostics in the session's `cleanup.log`.
See [development acceptance](development.md#guest-work-cleanup-acceptance) for the repeatable checks and verified runtime scope.
