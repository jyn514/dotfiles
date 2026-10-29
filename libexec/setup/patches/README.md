# Maintaining the Dashboard 0.11.0 patch

These patches adapt Dashboard's native bridge and browser UI to the dotfiles
question queue. They are pinned to upstream commit
`f93a27812534b2c1e2465dff52172fa763d631dd` and the published
`@blackbelt-technology/pi-dashboard-web@0.11.0` assets. Do not apply them to another
Dashboard version without reviewing and rebuilding the changes.

## What is installed

- [`pi-dashboard-0.11.0.patch`](pi-dashboard-0.11.0.patch) contains the native
  runtime TypeScript changes and an **additive native Vite build overlay**.
- [`pi-dashboard-0.11.0-source.patch`](pi-dashboard-0.11.0-source.patch) contains
  the complete source and focused regression tests, including the browser source.
  Use this companion to reproduce or revise the build; it is not a second
  installation patch.
- [`regenerate_pi_dashboard_patch.py`](regenerate_pi_dashboard_patch.py) generates
  both patches from an owned source checkout and the published web assets.

The runtime patch uses workspace paths. The
[installer](../setup_dashboard.py) maps `packages/client/dist` to the resolved
web package's `dist`, applies the pinned runtime changes, and maintains its patch
receipt. Installation does not build the browser or install development
packages. Keep obsolete hashed assets: the rebuilt `index.html` and its imports
select the active files. Do not replace this overlay with edits to private
symbols in minified JavaScript.

The installer regenerates gzip sidecars for changed/new compressible assets,
using upstream's size/type policy, and refreshes existing sidecars even when an
asset shrinks. Gzip bytes are not embedded in the patch. Copying only a changed
`.js` file while retaining its old `.gz` can serve the wrong implementation.

Native TypeScript changes preserve ordinary Dashboard dialogs, route queue
questions through PromptBus without blocking agent status, and recognize a valid
relative `./pi-dashboard` package declaration without rewriting settings. The
managed link targets the installed split extension package, whose public
`pi.extensions` entry is `src/bridge.ts`, not the core package's source copy.
Native extension discovery first uses Node resolution from the caller's package
root, preserving the installed extension's runtime dependency closure; bundled
workspace source is a fallback only. Managed settings symlinks are never replaced or written through; an unresolved
or disabled declaration instead produces an actionable warning (or strict-mode
error). The native launch primitive's optional internal `healthHost` carries the
selected HTTP bind address through readiness checks. Extension and CLI callers
use the existing `localDialHost` helper; bridge URLs and UDS transport are
unchanged.

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

## Installation dependencies

The mise declaration pins the root release but does not fully lock its transitive graph.
The reviewed disposable installation resolved all Dashboard components to `0.11.0` and Pi SDK packages to `1.4.0`;
its receipt records the versions actually installed.
Native build approvals are limited to the root Dashboard package, split server, `esbuild`, `koffi`, and `node-pty`.
The per-tool `--config.blockExoticSubdeps=false` permits the server's SheetJS tarball dependency
at `https://cdn.sheetjs.com/xlsx-0.20.3/xlsx-0.20.3.tgz`; it is not a global pnpm policy change.
Recheck those approvals and the tarball dependency when changing the release.

The guest Alpine/musl installation loaded `koffi` and ran `esbuild`, but `node-pty` spawning exited 139.
That probe's cause is unresolved; it does not establish intended-host glibc or macOS terminal compatibility.
The browser queue regression uses a Python PTY and does not exercise Dashboard's host terminal feature.

## Rebuild and regenerate

Use a **fresh, disposable checkout**, not an installed package or a checkout
being mutated by tests. Prerequisites are Git, GNU patch, Python 3, tar, Node/npm,
and the upstream manifest's package manager (`pnpm@11.15.1`). Dependency and
archive downloads need public network access; building does not require a live
Dashboard, Pi session, or Tailscale connection.

Run from the dotfiles repository root. The destination must not already contain
a source checkout. `target/` keeps the resulting artifacts available for review.

```sh
set -eu
repo=$(pwd -P)
stage="$repo/target/pi-dashboard-maintenance"
mkdir -p "$stage/published-web"
git clone --no-checkout https://github.com/BlackBeltTechnology/pi-agent-dashboard.git "$stage/source"
git -C "$stage/source" checkout --detach f93a27812534b2c1e2465dff52172fa763d631dd
npm pack --ignore-scripts --pack-destination "$stage/published-web" @blackbelt-technology/pi-dashboard-web@0.11.0
tar -xzf "$stage/published-web/blackbelt-technology-pi-dashboard-web-0.11.0.tgz" -C "$stage/published-web"

cd "$stage/source"
pnpm install --frozen-lockfile
patch --batch --fuzz=0 -p1 < "$repo/libexec/setup/patches/pi-dashboard-0.11.0-source.patch"
"$repo/dev/test-environment" env NODE_OPTIONS=--max-old-space-size=4096 npm run build
python3 "$repo/libexec/setup/patches/regenerate_pi_dashboard_patch.py" \
  --source "$stage/source" \
  --published-web-dist "$stage/published-web/package/dist" \
  --output-dir "$repo/libexec/setup/patches"
```

For a native-only revision with no browser source delta, retain the existing
validated native `dist` and omit the build step; do not introduce needless Vite
churn. The loopback and split-registration revisions reused that build. A fresh
reconstruction or browser revision uses the full build procedure above.

The comparison base must be the **published archive's** `package/dist`, not a
second local build. The successful reviewed build used a 4-GiB Node heap; the
2-GiB attempt exhausted its heap. Review the generated source diff and all native
build deltas. The reviewed result contains 138 changed/new uncompressed browser
files; that count is evidence for this build, not a rule for future revisions.

## Validate before installing

Run tests through `dev/test-environment`, from the patched source checkout. Start
with `npm run lint` and the changed tests. Selected-address regressions live in
`server-auto-start-bind.test.ts`, `server-launcher.test.ts`, and
`cli-specific-bind.test.ts`; they exercise real HTTP listeners, require a
localhost probe to fail, and use an available noninternal IPv4 address (falling
back to `127.0.0.2` when none exists). The CLI fixture also verifies the native
restart HMAC against the accepted socket binding. Registration tests cover valid,
missing, broken, and disabled declarations without changing a managed settings
symlink.

Apply the runtime patch with `patch --batch --fuzz=0 -p1` to a separate copy of
the published core package plus the published web `dist` at its workspace path.
Compare every patched file byte-for-byte with the source/build, verify the
`index.html` references exist, and reverse the patch to check restoration and
removal of added files. The additional HTTP listener's native regression is
`http-loopback-listener.test.ts`: real primary/private-IP and fixed-loopback
listeners share a port, authenticated HTTP and WS work on both, unauthorized
requests fail, proofs cannot be relayed between endpoints or replayed after
restart, stop closes idle/upgraded sockets, another interface stays unreachable,
and a loopback bind conflict rolls back startup. Apply the source companion separately to a clean pinned
checkout. Regeneration from unchanged inputs must produce identical patch bytes.

**Do not run upstream's full `npm test` beside builds or regeneration.** Its
`scripts/__tests__/async-semantics-mutation.test.mjs` deliberately mutates real
source files. Interruption can leave residue; its journal/reconciliation must
finish before reusing that checkout. Use another disposable checkout for the
full suite, and inspect its status afterward.

The initial queue patch passed TypeScript checking, 20 focused files / 466 tests,
the native build, exact forward/reverse patch application, and deterministic
regeneration. The split-registration revision passed 4 registration files / 52
tests. The loopback revision passed TypeScript checking and 5 affected/config,
TLS, and credential files / 276 tests. The web-interface-only revision passed
TypeScript checking and focused shared, extension, preference, and real-server
boundary tests; these counts overlap and are not additive. The exploratory full suite recorded failures outside this patch's
scope and was stopped; it did not establish full-suite acceptance. These local
checks do not establish packaged gzip correctness, a real browser/native-Pi
round trip, or the host's selected Tailscale-IP listener. Validate those through
the installed package before calling the complete integration accepted.
