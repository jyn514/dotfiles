# Source-aware tmux attachment

The launcher, helper, and hooks implement the [attachment policy](README.md#session-attachment).
Linux integration is verified; POSIX interfaces do not establish macOS runtime support.

## Previous behavior

The old `session-created[1]` hook ran before renumbering; the symlinked helper skipped restore mode, prior-session clients, and detached creation.
It selected the first detached session, armed `destroy-unattached` on the new session, and used implicit targets.

Session environment contains only the latest `SSH_CONNECTION`, so it cannot identify every attached client's source.
The old attachment tests checked fake tmux command sequences rather than real outcomes.

## Decisions and boundaries

The README owns source identity, eligibility, fallback, priority, explicit-attachment policy, and reload instructions.
Identity comes from live clients, not session creators or historical occupants; Tailscale names never affect selection.
Preserve restore suppression, in-tmux and detached creation, renumbering, explicit attachments, and `tmux-cssh` behavior.

The tmux server owns live membership; the launcher owns source metadata for its child process's lifetime.
The helper reads only records for live clients on the selected server and does not persist a host registry or labels.
Session environment is not per-client authority; prompt behavior, SSH setup, packages, and Tailscale installation need no changes.

## Client environment experiment and selected capture mechanism

On tmux 3.7c, `display-message -p -c CLIENT '#{SSH_CONNECTION}'` returned the latest session value for both clients.
The tagged source also reads environment formats from session/global environment, not client environment.

The approved `bin/tmux` launcher captures identity before starting the real binary; `attachment.py` owns parsing, supervision, and selection.
Host-local records are keyed by child PID and stay valid only while the launcher holds their lock.
Unlocked records are unknown, including after PID reuse; the helper reads only records for server-reported live clients.
Direct binary invocations remain supported with unknown identity.

`after-new-session[1]` retains the creating client's command context; `session-created[1]` could select an unrelated client.
The old hook is removed on reload, while separate session-created/session-closed hooks still handle renumbering.

## Implemented behavior

The hook passes client, new-session, socket, and server identities explicitly; restore disable/enable remains supported.
The helper snapshots live membership, excludes the new session, and targets every query and mutation explicitly.
It rechecks candidates before switching and serializes selection plus switching with a per-server `flock`.
Lock ownership is process-scoped, so failure, interruption, or process death releases it; stable lock files are not unlinked under waiters.
Tailscale `whois --json` runs with a one-second timeout after lock release; any lookup failure falls back to the IP label.
Label lookup does not affect eligibility, and logs exclude connection environments and full Tailscale responses.
The new session is destroyed only after successful reuse and only when no other client remains attached.

## Failure and cleanup lifecycle

Each query must succeed before its output is consumed; failures leave the new session available and report once.
If a candidate disappears or gains a same-source client, retry selection up to three times, then retain the new session.
Switch failure leaves the new session intact and never arms `destroy-unattached` for a later detach.
After successful reuse, kill only this invocation's new session and only if no clients remain attached.
Client exit removes its source record; process exit releases its lock, and stale unlocked records are ignored.
Do not detach other clients or change their session options.

## Verification

Use real tmux clients to assert final session membership and survival, not only emitted commands.
Load the production attachment hooks while excluding unrelated TPM and environment setup.
Pass the disposable socket explicitly through every subprocess; clear inherited live `TMUX` state.
Use readiness notifications or bounded polling instead of fixed sleeps.

| Existing candidate | Incoming source | Expected result |
| --- | --- | --- |
| Detached | Local or SSH A | Reuse |
| Local client | Local | Retain new session |
| Local client | SSH A | Reuse |
| SSH A client | SSH A, different source port | Retain new session |
| SSH A client | SSH B | Reuse |
| Local and SSH A clients | SSH B | Reuse |
| Local and SSH A clients | Local or SSH A | Retain new session |
| Unknown client source | Known source | Retain new session |

Also cover normalization of IPv6, malformed SSH data, multiple eligible candidates, and preference for detached sessions.
Attach two clients to one session, overwrite its session environment, and verify both sources still affect selection.
Detach or switch a client and verify eligibility follows live membership.
Race two incoming clients from the same source and verify they end in different sessions.
Repeat with distinct sources and verify sharing remains possible.
Test configuration reload with preexisting clients, renumbering, restore suppression, explicit in-tmux creation, and detached scripted creation.
Inject query failure, switch failure, interruption, and candidate disappearance; verify retained sessions and released resources.
Fake Tailscale only for label success and failure cases; changing names must not change membership.

Run `dev/test-environment python3 tests/tmux/attach_session_test.py` for attachment regressions.
Run the tmux suite and relevant setup hook tests through `dev/test-environment` before completion.
Inspect the loaded hooks on the disposable server before interpreting results.
