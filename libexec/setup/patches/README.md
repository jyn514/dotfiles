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

### Unreleased upstream network-denial fix

The patch backports upstream PR #1098 (`2996d4cab1095d3cda97abcb248343bac8c9c98b`),
which fixes issue #1082 without moving off the published 0.11.0 dependency graph.
An unpaired remote browser now receives its own `networkAccess` denial verdict in
`GET /api/health` and shows **Network not allowed** with **Request access** instead
of **Offline**.
Health uses the same admission predicate as guarded routes without recording denial
events or admission counters; local-proof responses retain priority.
The backport includes the server, shared signal, browser hook, and upstream package-level tests.
It does not include upstream CI/Docker changes, the variant-harness Playwright test,
or upstream agent documentation.
Remove the backported changes when adopting a release that contains #1098.

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
NODE_OPTIONS=--max-old-space-size=4096 pnpm install --frozen-lockfile
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
build deltas. The initial reviewed result contains 138 changed/new uncompressed browser
files; that count is evidence for that build, not a rule for future revisions.

## Check the installed patch and running browser assets

Run these checks on the host, from the dotfiles repository root, with mise's Node and pnpm on `PATH`.
They read the installed package and query the running daemon; they do not install, restart, pair a device, or change configuration.
Start with `pi-dashboard --version` and `pi-dashboard status` to identify the installed release and running daemon.
Do not use `pi-dashboard --help`: this release starts the foreground server for that argument.

The following command checks three different things: the installation matches our patch, the running server returns the denial signal,
and the browser entrypoint it serves matches the patched asset.
It resolves the installation and split web package through the existing setup helpers, not a guessed pnpm store path.
The HTTP checks default to the configured port on loopback, which requires `listenOnLoopback` or a loopback primary listener.
If needed, set `DASHBOARD_CHECK_URL` to the daemon's reachable HTTP origin before running the command.
Do not point it at an unrelated server.
From Fish, enter `bash` before pasting the heredoc below; `exit` returns to Fish.

```sh
python3 - <<'PY'
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import runpy
import urllib.request

root = Path.cwd()
setup = runpy.run_path(str(root / "libexec/setup/setup_dashboard.py"))
command = setup["command"]
install = Path(command("mise", "where", setup["TOOL"])).resolve()
version = setup["pin"]()
core = setup["installed_core"](install)
components = setup["component_roots"](core)
setup["validate_roots"](core, components, version, install)
receipt = json.loads((install / setup["STAMP"]).read_text())
assert receipt["version"] == version, "installed release differs from the mise pin"
patch = setup["patch_file"](version)
assert receipt["patch_sha256"] == hashlib.sha256(patch.read_bytes()).hexdigest(), "installed patch is stale"
for name, expected in receipt["files"].items():
    target = install / name
    actual = hashlib.sha256(target.read_bytes()).hexdigest() if target.exists() else None
    assert actual == expected, f"installed file differs: {name}"
print("Installed files match the current patch receipt")

config = json.loads((Path.home() / ".pi/dashboard/config.json").read_text())
base = os.environ.get("DASHBOARD_CHECK_URL", f"http://127.0.0.1:{config.get('port', 8000)}").rstrip("/")
print(f"Configured primary: {config.get('bindHost')}; checking: {base}")
request = urllib.request.Request(base + "/api/health", headers={"X-Forwarded-For": "203.0.113.9"})
with urllib.request.urlopen(request, timeout=10) as response:
    health = json.load(response)
assert health.get("networkAccess", {}).get("error") == "network_not_allowed", "missing remote denial verdict"
print("Running server reports the unpaired caller's network denial")


def get(path):
    request = urllib.request.Request(base + path, headers={"Accept-Encoding": "gzip"})
    with urllib.request.urlopen(request, timeout=10) as response:
        body = response.read()
        return gzip.decompress(body) if response.headers.get("Content-Encoding") == "gzip" else body


index = components["web"][0] / "dist/index.html"
# Vite's production HTML has a script entrypoint; the server injects its import map separately.
entry_pattern = rb'<script[^>]+src="([^"]+\.js)"'
entry = re.search(entry_pattern, index.read_bytes()).group(1).decode()
served_entry = re.search(entry_pattern, get("/")).group(1).decode()
assert served_entry == entry, "server selects a different browser entrypoint"
asset = get(entry)
assert asset == (index.parent / entry.lstrip("/")).read_bytes(), "served browser asset differs"
assert b"networkAccess" in asset, "browser entrypoint lacks the backported denial handler"
print("Server selects and serves the patched browser entrypoint")
PY
```

The denial check models an unpaired remote caller using a forwarding header and supplies no credentials.
It expects this deployment's `pair` trust mode; a different admission policy can legitimately omit the field.
Health polling does not create denial events or admission counters.
A successful result does not prove the phone can reach the Tailscale listener or complete pairing.
Check those in the actual browser.

A `null` receipt hash means the installer intentionally removed that old asset; absence is the expected result.
The HTML shell is not byte-identical to the installed `index.html`: the server inserts its import map and a per-response CSP nonce.
Compare its selected entrypoint, then the decoded JavaScript bytes, rather than raw HTML equality.
The asset request advertises gzip so a stale compressed sidecar cannot hide behind a correct uncompressed file.

## Validate before installing

Run tests through `dev/test-environment`, from the patched source checkout. Start
with `npm run lint` and the changed tests.
On a memory-limited Linux guest, run typechecking with `dev/test-environment env GOMEMLIMIT=3GiB GOGC=50 npm run lint`
(use the wrapper's absolute path from the upstream checkout).
These variables bound the native TypeScript 7 compiler's Go heap; Node's heap flag does not control it.
Do not reuse only another checkout's root `node_modules` symlink for full typechecking: it does not reconstruct workspace dependency links.
Use the frozen installation above.
Selected-address regressions live in
`server-auto-start-bind.test.ts`, `server-launcher.test.ts`, and
`cli-specific-bind.test.ts`; they exercise real HTTP listeners.
The bridge regression covers a stale primary address with a working loopback listener, before and after launch, and checks the child readiness endpoint.
Primary-only cases require a localhost probe to fail and use an available noninternal IPv4 address (falling back to `127.0.0.2` when none exists).
The CLI fixture also verifies the native
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
TLS, and credential files / 276 tests. The transient-info revision passed TypeScript checking,
a native browser build, and 34 focused files / 386 tests, including live bridge delivery,
reconnect replay, persisted-log filtering, notification floors, and toast expiry during parent rerenders.
Its runtime and source patches apply and reverse exactly, and unchanged regeneration is deterministic.
The web-interface-only revision passed
TypeScript checking and focused shared, extension, preference, and real-server
boundary tests; these counts overlap and are not additive. The exploratory full suite recorded failures outside this patch's
scope and was stopped; it did not establish full-suite acceptance. These local
checks do not establish packaged gzip correctness, a real browser/native-Pi
round trip, or the host's selected Tailscale-IP listener. Validate those through
the installed package before calling the complete integration accepted.
