# Maintaining the Dashboard patches

The source patches adapt Dashboard's bridge and browser UI to dotfiles.
The source pin and ordered patch paths live in [pi-dashboard-source.json](../../../config/pi-dashboard-source.json).

## What is installed

The [installer](../setup_dashboard.py) applies the ordered source patches to an owned copy, installs the workspace package graph using the frozen pnpm lockfile, and builds it.
It records `source`, `patches` (each with `path` and `sha256`), and `files` in the build root's `.dotfiles-dashboard-patch.json`.
A patch conflict or an already-applied patch fails before activation; patches are not skipped.
The CLI and Pi bridge use the active build at `~/.local/share/pi-dashboard/current`.

The old [runtime overlay patch](pi-dashboard-0.11.0.patch) and [regeneration helper](regenerate_pi_dashboard_patch.py) remain historical maintenance artifacts, not installation inputs.
The overlay targeted published release assets and included gzip handling; the source installer builds the workspace instead.

Native TypeScript changes preserve ordinary Dashboard dialogs, route queue
questions through PromptBus without blocking agent status, and recognize a valid
relative `./pi-dashboard` package declaration without rewriting settings. The
managed link targets the active workspace root, whose public
`pi.extensions` entry is `packages/extension/src/bridge.ts`.
Native extension discovery first uses Node resolution from the caller's package
root, preserving the installed extension's runtime dependency closure; bundled
workspace source is a fallback only. Managed settings symlinks are never replaced or written through; an unresolved
or disabled declaration instead produces an actionable warning (or strict-mode
error). Before each browser-requested spawn, the server rereads that declaration
with the same public-resource checks. A broken declaration returns an immediate
`PREFLIGHT_FAILED` / `DASHBOARD_BRIDGE_UNAVAILABLE` error naming the checked path;
it files no spawn intents, starts no process, and arms no registration watchdog.
Repairing the declaration therefore makes the next spawn eligible without a
Dashboard restart. Server startup remains available in this degraded state so
existing sessions and repair surfaces continue to work.

The check applies only to Pi-backed spawns, not ACP sessions. The native launch
primitive's optional internal `healthHost` carries the
selected HTTP address through readiness checks.
Bridge discovery and readiness use `127.0.0.1` when `listenOnLoopback` is enabled, so changing tailnets does not hide a running daemon.
Without that listener, they use the selected primary bind address.
CLI callers use the existing `localDialHost` helper; bridge URLs and UDS transport are unchanged.

### Reconnect replay

Replay retains only the latest consecutive assistant text snapshot, including
unfinished responses. Thinking deltas, tool-call sub-events, and all intervening
events remain boundaries. Original sequence numbers and the pre-compaction
high-water mark stay unchanged. Only replay shrinks; stored events and live
forwarding do not change.

The patch's `replay-streaming-catchup.test.ts` compares raw and compacted replay
through the real client reducer, including mid-message reconnects, thinking,
tool boundaries, and the next live tool event. Its subscribe-path regression
also checks that delta replay completes without a history window or reset.

### Fixed web-interface-only profile

This downstream build uses Dashboard as a browser interface to Pi, not as an
agent-policy owner. It preserves explicit browser chat, session, question,
abort, model, thinking, editor, terminal, and Git controls. The bridge does not
register extra tools, alter prompts, manage providers or roles, deliver vault or
MCP credentials, decide project trust, invoke automatic naming or continuation,
provision OpenSpec, or install plugin bridges.

The server refuses the corresponding HTTP and WebSocket management commands
before they can write files or start work. Effective configuration clamps the
supported feature switches off even when an older local config enables them.
Stored preferences are also reported with automatic naming and automatic
worktree creation disabled. Authentication, pairing, session projection,
explicit user controls, and the dotfiles PromptBus question projection remain
active.

### Upstream network-denial fix

Upstream PR #1098 (`2996d4cab1095d3cda97abcb248343bac8c9c98b`),
which fixes issue #1082, is included in the pinned source.
An unpaired remote browser now receives its own `networkAccess` denial verdict in
`GET /api/health` and shows **Network not allowed** with **Request access** instead
of **Offline**.
Health uses the same admission predicate as guarded routes without recording denial
events or admission counters; local-proof responses retain priority.

### Optional additional loopback HTTP listener

`listenOnLoopback: true` in Dashboard's native config adds fixed
`127.0.0.1:<HTTP port>` alongside the selected primary bind. Its default is
`false`. It is a restart setting, with no new CLI flag or frontend control. The
primary address stays unchanged: enabling it does not bind every interface or
expose another LAN address. When the primary already covers IPv4 loopback, it
needs no additional listener. There is no requirement for an IPv6 loopback edge.

The additional socket belongs to the same native server process and dispatches
into the same Fastify routes, authentication hooks, and WebSocket upgrade
handler, following the existing native TLS dispatch pattern. It is not another
application instance, proxy process, or replacement for the TLS/model-proxy
ports. Pairing and authorization remain shared; a loopback peer does not gain an
authentication bypass. Credential proofs retain their actual socket endpoint
binding and a separate listener bind-time floor.

An explicitly requested loopback bind is required. A conflict such as
`EADDRINUSE` rejects startup and the existing failure teardown releases the
primary listener and gateway; it does not silently drop loopback. Normal stop
also closes loopback's idle and upgraded sockets. A fresh server can reopen both
addresses at the same port, and proofs predating that listener are rejected.

## Investigating behavior

For desktop window placement, start with [`place-dashboard-pi.py`](../../tmux/place-dashboard-pi.py).
For Dashboard behavior, inspect the active source build or an independently patched checkout.
Prefer searches in the relevant source files over broad searches through the runtime patch, which includes minified browser assets that can overwhelm search output.

## Updating the pin and patch

Change the repository, full revision, or ordered patch list in [pi-dashboard-source.json](../../../config/pi-dashboard-source.json).
Review source changes and update the patches for the new revision.
Remove changes from a patch when they have merged upstream; other patch conflicts can still require resolution.
Use a separate checkout for patch development, and keep the supplied checkout unpatched when testing `./setup dashboard --checkout PATH`: setup applies the same configured patches to its copy.
That command copies current tracked files and non-ignored untracked files without modifying the supplied checkout; it omits deleted files and copies input symlinks as owned files.
A later `./setup dashboard` uses the configured upstream pin again.

Setup builds under `~/.local/share/pi-dashboard/builds/build-*/source` and activates `~/.local/share/pi-dashboard/current`.
It does not restart the daemon or reload Pi.
After switching builds, run `pi-dashboard stop` followed by `pi-dashboard start --no-tunnel`.
The native `restart` command reuses the running daemon's build and Node executable, so it does not activate the new build.
For code-only updates, `/reload` affected Pi sessions; after a Node upgrade, start fresh Pi processes instead.
Reload browser pages to load the updated UI.
Old builds are retained for live processes; remove them manually only after those processes stop.

Mise supplies Node and pnpm; Dashboard is not a mise npm tool.
The guest Alpine/musl installation previously loaded `koffi` and ran `esbuild`, but `node-pty` spawning exited 139.
That probe's cause is unresolved; it does not establish intended-host glibc or macOS terminal compatibility.
The browser queue regression uses a Python PTY and does not exercise Dashboard's host terminal feature.

## Validate before installing

Run tests through `dev/test-environment`, from the patched source checkout. Start
with `npm run lint` and the changed tests.
On a memory-limited Linux guest, run typechecking with `dev/test-environment env GOMEMLIMIT=3GiB GOGC=50 npm run lint`
(use the wrapper's absolute path from the upstream checkout).
These variables bound the native TypeScript 7 compiler's Go heap; Node's heap flag does not control it.
Do not reuse only another checkout's root `node_modules` symlink for full typechecking: it does not reconstruct workspace dependency links.
Use a frozen pnpm installation in the disposable checkout.
Selected-address regressions live in
`server-auto-start-bind.test.ts`, `server-launcher.test.ts`, and
`cli-specific-bind.test.ts`; they exercise real HTTP listeners.
The bridge regression covers a stale primary address with a working loopback listener, before and after launch, and checks the child readiness endpoint.
Primary-only cases require a localhost probe to fail and use an available noninternal IPv4 address (falling back to `127.0.0.2` when none exists).
The CLI fixture also verifies the native
restart HMAC against the accepted socket binding. Registration tests cover valid,
missing, broken, and disabled declarations without changing a managed settings
symlink.

Validate the ordered source patches against a clean checkout of the configured revision.
The additional HTTP listener's native regression is `http-loopback-listener.test.ts`: real primary/private-IP and fixed-loopback listeners share a port, authenticated HTTP and WS work on both, unauthorized requests fail, proofs cannot be relayed between endpoints or replayed after restart, stop closes idle/upgraded sockets, another interface stays unreachable, and a loopback bind conflict rolls back startup.

**Do not run upstream's full `npm test` beside builds or regeneration.** Its
`scripts/__tests__/async-semantics-mutation.test.mjs` deliberately mutates real
source files. Interruption can leave residue; its journal/reconciliation must
finish before reusing that checkout. Use another disposable checkout for the
full suite, and inspect its status afterward.

The initial queue patch passed TypeScript checking, 20 focused files / 466 tests,
the native build, exact forward/reverse patch application, and deterministic
regeneration. The split-registration revision passed 4 registration files / 52
tests. The loopback revision passed TypeScript checking and 5 affected/config,
TLS, and credential files / 276 tests. The transient-info revision passed TypeScript checking,
a native browser build, and 34 focused files / 386 tests, including live bridge delivery,
reconnect replay, persisted-log filtering, notification floors, and toast expiry during parent rerenders.
Its historical runtime and source patches applied and reversed exactly, and unchanged regeneration was deterministic.
The web-interface-only revision passed
TypeScript checking and focused shared, extension, preference, and real-server
boundary tests; these counts overlap and are not additive. The exploratory full suite recorded failures outside this patch's
scope and was stopped; it did not establish full-suite acceptance. These local
checks do not establish packaged gzip correctness, a real browser/native-Pi
round trip, or the host's selected Tailscale-IP listener. Validate those through
the installed package before calling the complete integration accepted.
