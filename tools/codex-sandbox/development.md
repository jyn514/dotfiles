# Codex sandbox development

Use the [operator guide](README.md) for host setup, session commands, safety, and recovery.
Before running tests or probes, follow the repository
[testing and isolation rules](../../dev/README.md#testing-and-probes).
The startup benchmark below uses the host's real configuration.

## Nested Docker acceptance

The nested Docker wrapper owns one foreground SSH master per Docker invocation.
Docker and Buildx reuse its private control socket instead of authenticating a new connection for each API request.
The socket does not cross invocations or credential contexts.
Normal completion, startup failure, and cancellation close the client and master process groups before removing their private configuration.
The Docker client's terminal descriptors and requested cancellation signal remain unchanged.

Provision the [build VM](../agent-docker/README.md#setup), then build the current
agent image and gateway image with their installed image owners. Run this probe
against the admitted infrastructure VM using its real configuration:

```sh
python3 tools/codex-sandbox/tests/gateway_integration.py \
  --agent-image AGENT_IMAGE --gateway-image GATEWAY_IMAGE
```

This probe deliberately uses host VM state rather than an isolated HOME. It
creates two owned gateways and disposable workloads, checks pinned SSH access,
rootless `docker info`, an agent-originated build consumed by staged Woodpecker,
secret forwarding, pipeline cancellation and workspace/container cleanup,
cross-session network isolation, listener failure, and gateway cancellation.
It removes its containers, networks, and build image. It does not reset shared
services. Follow with Flower's full `bb test ci` in the restarted sandbox to
verify its actual pipeline and locally built CI images.

Challenge the build account from the host through guest-root authority:

```sh
limactl copy tools/agent-docker/tests/guest_role_probe.py \
  agent-build-docker:/tmp/agent-docker-role-probe.py
limactl shell --workdir=/ agent-build-docker sudo python3 /tmp/agent-docker-role-probe.py
limactl shell --workdir=/ agent-build-docker rm /tmp/agent-docker-role-probe.py
```

The probe first proves that a guest-root loopback listener is live and a
privileged rootless container starts. It then verifies that the build account
cannot connect to that listener, read guest-root data through a privileged
container, or redirect setup writes into guest-root files with a symlink.
The guest doctor also checks the loaded network policy, no host shares, no
administrative groups, and no passwordless sudo. The probe uses temporary
canaries and removes them; run it only in the owned build guest.

## TicGit confinement probe

Use this procedure to test the [selected TicGit confinement design](spec/tic-proxy.typ), not a production endpoint.
The spec owns the findings and remaining acceptance requirements; this section describes how to repeat the experiment.
No retained `target/` files are required.

Use disposable repositories, canaries, and containers in the separate [build VM](../agent-docker/README.md).
Do not mount real repositories, HOME, credentials, or the infrastructure Docker socket into the probe container.
The outer container needs relaxed security settings so the inner bubblewrap sandbox can create user/network namespaces and mount procfs.
These settings belong only to the disposable probe container, not the production sandbox:

```sh
dev/test-environment docker create --name tic-confinement-probe \
  --security-opt seccomp=unconfined --security-opt apparmor=unconfined \
  --security-opt systempaths=unconfined node:24-bookworm-slim sleep infinity
dev/test-environment docker start tic-confinement-probe
dev/test-environment docker exec tic-confinement-probe apt-get update
dev/test-environment docker exec tic-confinement-probe apt-get install --yes --no-install-recommends \
  bubblewrap socat ripgrep git gcc libc6-dev libseccomp-dev
dev/test-environment docker exec --user node tic-confinement-probe \
  bwrap --unshare-user --unshare-net --ro-bind / / --proc /proc /bin/true
```

Require the last command to succeed as the non-root `node` user before interpreting confinement results.
Without `systempaths=unconfined`, Docker's masked/read-only proc paths prevented the inner proc mount even after seccomp and AppArmor were disabled.
If namespaces remain unavailable, report a missing prerequisite rather than skipping into a successful verdict or retrying without confinement.

Prepare a fresh upstream SRT checkout at `v0.0.81`, commit `c40cf14a65d025e3cd27f071f13a73c12b3b1f92`.
The tracked [source patch](experiments/tic-confinement/sandbox-runtime-0.0.81.patch) includes its own five Linux regression cases and application instructions.
Apply it to that disposable checkout, not an installed package.
Copy the checkout into the container with `docker cp`; the build VM cannot bind-mount files from the agent's checkout.
Create `/probe`, give `node` ownership of it and the copied checkout, and install Bun inside the container.
The final focused run used Bun `1.3.14`.
Run each command below inside that checkout as `node`, prefixing it with
`dev/test-environment docker exec --user node --workdir CHECKOUT tic-confinement-probe`.
Replace `CHECKOUT` with the container-side path:

```sh
npm ci --ignore-scripts --no-audit --no-fund
npm run typecheck
bun test test/sandbox/linux-read-write-restores.test.ts
npm run build
npm run build:seccomp
npm pack --ignore-scripts --pack-destination /probe
```

Require five executed passing cases, not prerequisite skips.
For the regression comparison, keep the added test file but use the original upstream `linux-sandbox-utils.ts` in a separate disposable copy.
The original source failed four cases; the patched source passed all five, including explicit write-deny precedence.
Report other upstream suites and their prerequisite/platform skips separately; this is not a full-suite acceptance claim.

Install the resulting tarball into a fresh probe project and import SRT through its public package entrypoint.
Do not test only generated arguments or import a private helper as a substitute for this native-consumer check.
Use the supported unmodified TicGit build recorded in the spec, with matching runtime libraries.
The earlier musl environment required an extracted glibc loader and libraries to run the Linux release; loader failures are not confinement denials.

Reconstruct the fixture and checks from the spec's feasibility-probe section.
Use `SandboxRuntimeConfigSchema.parse`, `SandboxManager.checkDependencies`, `SandboxManager.initialize`,
and `SandboxManager.wrapWithSandboxArgv` to validate, initialize, and launch each command under the same policy.
Shell-quote native argv before passing it to `wrapWithSandboxArgv`, then spawn its returned argv with the fixture cwd and private environment.
First run confined `/usr/bin/true`, then native database creation and linked-worktree visibility, then the allowed/denied boundary checks.
Run each forbidden-effect control unconfined on owned fixtures first; a missing file, dead listener, or broken helper cannot prove confinement.
Check resulting files and returned contents, not just child exit status; native automatic setup may ignore a descendant's failure.
Close owned listeners and call `SandboxManager.reset` after the probe.
Record native/runtime provenance, policy, executed cases, and limitations when reporting results; raw logs need not be retained.
Remove the owned container with `dev/test-environment docker rm --force tic-confinement-probe` when finished.

## Startup terminal ownership

Redirecting the detached owner's stdio at fork made BuildKit lose its TUI:
Lima's `sandbox_runtime.py` build path needs both stdin and stderr to be TTYs
so SSH requests a guest PTY for automatic progress display. Keeping only stderr
on the terminal is not sufficient.

Preserve these boundaries when changing launcher output or process ownership:

- During interactive provisioning, `host_pi_owner.detached_frontend` keeps the
  invoking terminal's original stdin, stdout, and stderr. Do not force progress
  with `BUILDKIT_PROGRESS` or plain-progress output.
- Before bootstrap completes, `codex-sandbox.run_agent` starts the guest worker
  with explicit `DEVNULL` stdin and `OWNER_LOG_FD` stdout/stderr; inheriting the
  owner's stdio would retain the source pane's terminal.
- `HostPiOwner.mark_bootstrapped()` redirects owner stdin to `DEVNULL` and
  stdout/stderr to the private owner log before starting attachment service or
  delivering the first Pi launch spec. Keep `OWNER_LOG_FD` open until owner exit.
- Non-TTY startup retains the existing file-log relay. Startup failures remain
  visible without duplicate diagnostics; interactive output preserves carriage
  returns rather than passing through the text-file relay.
- Terminal handling must not change `/split` lifetime: either pane may close
  first, and shared resources remain until the final Pi attachment exits.

Run the regressions from the repository root:

```sh
dev/test-environment python3 -m unittest discover -s tools/codex-sandbox/tests -p host_pi_owner_test.py
dev/test-environment python3 -m unittest discover -s tools/codex-sandbox/tests -p codex_sandbox_test.py
dev/test-environment python3 tools/codex-sandbox/tests/restart_hook_test.py
```

`StartupTerminalTest` checks real PTY descriptors during build startup,
post-bootstrap detachment, exact output bytes, startup failure, and non-TTY
relay behavior. The launcher worker-stdio test checks the production handoff
with a native child. Owner tests also cover either pane closing first.
These local tests do not verify actual VM BuildKit rendering; check that on a
host with the supported runtime before claiming VM acceptance.

## Measure interactive startup

For a phase breakdown of a normal launch, use `env CODEX_SANDBOX_TIMING=1 pi`.
`Sandbox validation:` lines split repository validation into initialization,
lock waits, active-root lookup, workspace discovery, request locks, and mount
planning. These substeps are included in the enclosing `repository validation`
phase; initialization lock/metadata timings are also included in `dotfiles
initialization`. Do not sum nested timings. They are emitted on failure too,
so a slow or failed validation need not be attributed to the entire phase.
Initialized dotfiles checkouts take only the checkout-specific initialization
lock, not the service coordination lock; missing metadata still initializes
under both locks. All workspaces are validated on every launch.

`Sandbox service: role/operation=0.00s` lines split the real operations inside
proxy and TicGit startup and shared-proxy cleanup. They use the same opt-in flag,
write only to stderr (never helper JSON stdout), and emit elapsed time even when
an exception leaves the span (with a `failed` suffix). Roles are fixed `proxies`, `auth`, `tic`, `gh`, `jj`, or
`zulip`; custom command names are reported as `command`, not copied into logs.
No endpoints, arguments, credential values, paths, or resource identities are
included. `command-attach` contains cache/shared-reuse validation or command
startup; per-command spans separate volume initialization, repository mounts,
container run, forwarding publication, and readiness. Authentication attachment
is separate from session publication; nested auth spans distinguish configuration
publication, socket volume, networks, helper and Caddy container starts, the extra
Caddy network attachment, and readiness. Tic spans separate bundle/context work,
client staging and mount checks, broker startup through readiness, the host
bridge, shared gateway startup, readiness publication from gateway logs, and the
single guest help request. TicGit does not start a separate relay container.
Timing never replays that application request. Cleanup separates runtime recovery
query, stopped-holder discovery,
each command registry, and auth cleanup. Registry spans include owner inspection,
removal, and retries.
All spans are inclusive: command workers, Tic startup, and registry cleanup waves
can overlap; child spans are already included in parent preparation/cleanup
phases. Do not sum these lines. Timing serializes only each output line, never
the measured operations.

`Sandbox preparation:` measures launcher preparation, not interactive UI readiness.
TicGit startup overlaps shared proxy startup once its image inputs are settled;
the agent still waits for both, and optional TicGit failures still omit its endpoint.
Preparation phase durations are inclusive and can overlap, so do not add them to
estimate wall time. Cancellation closes the TicGit creation gate and joins all
startup workers before resource cleanup.

`Sandbox cleanup total:` includes final scratch removal. A successful final attachment
leaves published shared proxies warm for 30 seconds and starts a detached idle cleanup;
the next exclusive launch validates the complete published identity before reuse and
replaces mismatched services. Failed or unpublished launches still clean synchronously.
TicGit admission and its
lifetime pipe are revoked synchronously before independent teardown; `TicGit
teardown=... (overlapped)` then runs alongside the existing gateway/shared-proxy
cleanup path. The shared-session final-holder lock remains authoritative, and
scratch removal waits for both paths. Do not add that overlapping teardown span
to the other cleanup durations. Owned runtime cleanup inspects ownership directly
on the present-resource path, lists only to establish absence after inspection
failure, and rechecks ownership before removal; no inspection lifetime cache or
engine-verification bypass is used.

From the checkout being measured, run this repository's probe on a Unix host with local container-socket access:

```sh
TMPDIR=/private/tmp python3 tools/codex-sandbox/tests/interactive_startup.py --runs 3
```

The probe uses the normal launcher and configured extensions in a 30×100 pseudo-terminal, with `--no-session` and Pi's `PI_STARTUP_BENCHMARK` mode.
It makes no model request.
Readiness is the arrival of `interactiveMode.init:` in Pi's timing output, emitted after TUI initialization and a deliberate 150ms terminal-drain pause.
Output reports the observed elapsed time, that pause, and an estimate with the pause subtracted;
process shutdown is excluded.

Each invocation prints a new log directory and retains one raw terminal log per run.
A missing readiness marker or unsuccessful exit fails the probe;
`--timeout` defaults to 30 seconds per run, excluding cleanup.
On macOS, `/private/tmp` avoids the launcher's path-alias assertion.

With `CODEX_SANDBOX_RUNTIME=lima-docker`, the probe also records startup boundaries in JSON beside each log, including on timeout.
Container creation follows `workload_argv end`;
`popen end` marks the attach client's spawn, and `container entry` marks execution inside the container.
The probe mounts diagnostic wrappers and supplies a Node preload through `NODE_OPTIONS` for this run only.
Host markers carry their emission time;
guest markers use host receipt time and include transport delay.
Subtract Pi's own total and the 150ms terminal-drain pause from the Node-preload-to-readiness interval to estimate work before Pi's timer, including early imports.

For stalls, add `PI_STARTUP_PROFILE=1` and `--timeout 90`.
Runtime initialization dumps Python stacks every ten seconds while blocked.
The probe prints a `target/startup-profile-*` directory containing a Node CPU profile and Node's own elapsed/CPU times at readiness and exit.
Profiling begins at the Node preload, adds overhead, and writes its files on normal exit;
forced termination can lose the profile.
These diagnostics distinguish active CPU work from waiting, but host swap allocation alone does not establish paging during a stall.

Record whether images and shared required proxies were already warm, plus host/VM load.
Each run creates fresh agent and optional relay containers, but the probe does not reset caches or shared services.
Compare cold and warm samples separately;
image builds may need a longer timeout.
Do not remove unrelated sessions to manufacture a cold run.

## Tests

Run the Python unit tests together in one process from the repository root:

```sh
dev/test-environment python3 -m unittest discover -s tools/codex-sandbox/tests -p '*_test.py'
```

Socket tests require permission to create local TCP and Unix sockets.
They fail inside Codex's restricted sandbox with `PermissionError` / `Operation not permitted` when creating, binding, or connecting sockets.
Run those tests outside the Codex sandbox, still through `dev/test-environment`; the wrapper does not grant socket permissions.
These permission failures do not establish a regression in the code.
Fixtures register cleanup before fallible setup so a setup failure cannot leave mocks or environment changes active for later tests.
To check those failure paths without opening sockets, add `-k SetupCleanupTest` to the command above.

To check ordinary and linked-worktree mounts on an existing Docker VM, use an
already built sandbox image containing Python and Git. Replace
`codex-sandbox:TAG` with its image reference:

```sh
dev/test-environment env LIMA_HOME="$HOME/.lima" \
  python3 tools/codex-sandbox/tests/repository_mounts_integration.py \
  --state "$HOME/.local/state/codex-sandbox-docker" --image codex-sandbox:TAG
```

This runs the launcher's mount builder with both worktree and shared Git backend
paths. Networkless fixture containers check relative and absolute pointer files,
Git discovery, writable worktree files, and read-only metadata. Fixtures and
containers are removed after each case.

To compare the bundled resolver's ignore filtering with BuildKit, run the
disposable scratch-image probe against an existing Lima-Docker VM:

```sh
dev/test-environment env LIMA_HOME="$HOME/.lima" python3 tools/codex-sandbox/tests/bake_ignore_integration.py --state "$HOME/.local/state/codex-sandbox-docker"
```

The probe checks case sensitivity, wildcard exceptions, ancestor matching, and
Dockerfile-specific ignore precedence through actual Bake builds and container
exports. It removes its containers and tagged images after each case.

Live Caddy checks in `tests/caddy_foundation_test.py` execute the pinned manifest
for the Docker daemon's platform.
The existing native configuration-validation and request-forwarding checks require a reachable Docker engine and may pull the pinned image.
A missing cached image does not skip those checks; validation or execution failures fail the test.
Unit checks verify identity selection for both supported platforms.
Foreign-architecture execution requires emulation and is not part of the default suite.

Caddy preserves the original caller `Authorization` when making its bodyless helper request.
It must not replace that value with the configured instance token: doing so admits unauthenticated callers.
The helper performs constant-time exact bearer-token admission before reading or refreshing credentials.
Missing, wrong, and over-4096-byte Authorization values return bodyless `401` without an application-upstream request.
Only successful admission replaces caller auth/account headers with the helper's trusted values.
Every launcher startup and join probe sends `Authorization: Bearer <instance-token>` to exact bodyless `GET /ready`, with no query.
Readiness checks local credential readability through Caddy and the helper without an application-upstream request or credential refresh/write.
`EgressPairPlan.session_token` supplies both the helper admission token and shared startup probe header;
caller-provided `helper_environment` must not also set `CADDY_PROFILE_TOKEN`.

The additional `LiveCaddyAcceptanceTest` matrix is discovered through `tests/caddy_foundation_test.py` by the normal test runner.
It also runs directly with:

```sh
dev/test-environment python3 tools/codex-sandbox/tests/caddy_acceptance_integration.py
```

This matrix requires the daemon's pinned Caddy manifest and `python:3.12-alpine` already installed locally.
It skips when either image is missing and never pulls images; this restriction applies only to the additional matrix, not the existing native checks.
It creates and removes disposable containers, volumes, and a network, with no live service or VM configuration changes.
The matrix exercises rejected and admitted caller tokens through Caddy and the actual Unix helper,
including authenticated readiness and zero application requests on rejection.

For allowed helper metadata and forbidden log contents, follow the Readiness and observability section of
[the authenticated-egress specification](spec/proxy-design.typ).
Passing admission checks alone does not establish compliance with its logging exclusions.

The Pi runtime staging step uses `npm ls --omit=dev` for the coding-agent workspace's installed dependency graph.
It copies linked workspaces using npm's published file lists and preserves ordinary production dependencies at their installed paths.
It also retains each selected workspace's `src/` directory for inspecting the exact source used to build the installed Pi.
Runtime imports still use the published entrypoints in `dist/`.
Build tools, tests, build configuration, and unrelated workspaces stay in the build stage.
The standalone entrypoint shares the coding-agent `dist` tree through a symlink, including its binary assets.

Before building images or requesting a host rerun, run the native fixture checks:

```sh
dev/pytest -q tools/codex-sandbox/tests/fixture_metadata_test.py
```

These checks do not replace the container probe; report any local-JJ prerequisite skips separately.

The runtime integration test builds real images and requires a working Docker daemon, Docker Buildx with Bake, network access, and local Git and JJ binaries:

```sh
dev/test-environment python3 tools/codex-sandbox/tests/image_runtime_integration.py --expected-revision <full-pi-commit>
```

To build and probe only the JJ proxy, without a Pi installation or revision:

```sh
dev/test-environment python3 tools/codex-sandbox/tests/image_runtime_integration.py --jj-only
```

JJ-only mode builds, probes, and cleans only the JJ image; it retains the shared JJ cache alias.

For shared-workspace fixtures, generate repository metadata and run JJ discovery with the tested image's pinned JJ.
Do not substitute host JJ unless the test explicitly covers cross-version compatibility.

For the full run, use the host commit recorded in `~/.local/share/pi/node/.source-revision`.
The test passes that commit as the required `PI_REVISION` build argument and checks
its recorded revision, retaining Alpine Node and Debian Node-20/Bun coverage.
Its wrapper probe checks public command resolution, successful `bb`, `jj`, and `rg` aliases, and blocked nested wrapper operations in the produced images.
It also runs `jj-conflict check` on a disposable clean file so a missing packaged command fails the probe.
Each guest's binary checksum, runtime, and wrapper checks share one container run.
The same run checks packaged SDK imports, runtime assets, and real read and bash requests through the tool worker.
It uses Node on Alpine and Bun on Debian, matching the Pi entrypoint's runtime selection.
A mounted checkout probe calls the launcher's real JJ mount generator for a disposable repository.
It stages the repository in an owned Docker volume and translates bind source paths for the remote daemon, leaving generated destinations and permissions unchanged.
Through the mounted proxy, it checks out history that removes and restores `.agents/sandbox`, then checks that the working copy is not stale.
The probe removes its container and volume even when checkout fails.
The colocated-workspace probe computes the proxy binary's checksum without copying the binary out of its image.
It also checks the TLS certificate-store alias and starts the proxy server to exercise HTTP/HTTPS fetch helpers under Landlock.
That check uses refused loopback connections with networking disabled, so missing helpers or denied execution cannot pass as expected fetch failures.
In the full run, one Bake invocation builds the JJ proxy and both runtimes, with the runtimes consuming the JJ target directly as a named build context.
Bake schedules independent work concurrently and shares common stages without publishing and resolving an intermediate JJ tag.
All three images are built before the probes run.
Both revision labels share one Docker inspect query, then the three container probes run concurrently.
Checksum validation uses the JJ probe's result, and cleanup waits for every probe to finish even when another fails.
Each run builds against current inputs and checks unique per-run image aliases, which cleanup removes.
Successful builds also retain one shared `:cache` alias per image so later runs reuse unpacked runtime filesystems.
Concurrent runs can update the shared caches without changing another run's test images.
To discard these test caches explicitly:

```sh
docker image rm codex-sandbox-jj-test:cache codex-sandbox-pi-alpine-test:cache codex-sandbox-pi-debian-test:cache
```

Direct Dockerfile builds must also supply `--build-arg PI_REVISION=<full-pi-commit>`;
there is no independent guest revision default.

Check the image caches against a built final image;
test containers run without network access:

```sh
docker build --build-arg PI_REVISION=<full-pi-commit> --target pi-extension-cache -f tools/codex-sandbox/image/Dockerfile -t pi-cache-test .
python3 tools/codex-sandbox/tests/cache_integration.py --runtime <sandbox-image> --builder pi-cache-test
docker image rm pi-cache-test
```

This checks Alpine bytecode reuse, first-launch extension cache hits, edited source, isolation between containers, and build failure on missing packages or extension errors.

## Broker-backed live provider probe

Running this probe makes a live model request through the sandbox broker and may incur model cost.
It uses the installed Pi SDK, private HOME, no model-catalog refresh, and no discovered extensions or sessions.
Unlike `dev/replay-compaction`, it does not need personal configuration or stored authentication.
The parent passes broker credentials through stdin because `dev/test-environment` removes the inherited broker variables.
Do not put the key in command arguments, files, or diagnostic output.

Save these two files in a private temporary directory.
Use an available `openai-codex` model ID when running the launcher from the repository root.

`probe.ts`:

```typescript
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { pathToFileURL } from "node:url";

const packageDir = process.env.PI_PACKAGE_DIR;
assert.ok(packageDir, "Set PI_PACKAGE_DIR to the installed Pi SDK");
const manifest = JSON.parse(readFileSync(resolve(packageDir, "package.json"), "utf8"));
const { ModelRuntime, ModelRegistry } = await import(pathToFileURL(resolve(packageDir, manifest.exports["."].import)).href);
const { default: codexSidecar } = await import(pathToFileURL(resolve("config/pi-agent/pi-extensions/codex-sidecar.ts")).href);
const { baseUrl, apiKey } = await Bun.stdin.json();
assert.ok(baseUrl && apiKey && process.argv[2], "Broker credentials and a model ID are required");
process.env.CODEX_SIDECAR_URL = baseUrl;
process.env.CODEX_SIDECAR_KEY = apiKey;

const runtime = await ModelRuntime.create({ modelsPath: null, allowModelNetwork: false, refreshOnCreate: false });
const registry = new ModelRegistry(runtime);
codexSidecar({ registerProvider: registry.registerProvider.bind(registry) });
const catalogModel = registry.find("openai-codex", process.argv[2]);
assert.ok(catalogModel, "Model is missing from the installed catalog");
// Catalog metadata can retain a different endpoint despite provider registration.
const model = { ...catalogModel, baseUrl };
const response = await registry.complete(model, {
  messages: [{ role: "user", content: [{ type: "text", text: "Reply only PROBE_OK." }], timestamp: Date.now() }],
}, {
  maxTokens: 256, reasoningEffort: "low", transport: "sse", signal: AbortSignal.timeout(60000),
  onPayload: (_payload, requestModel) => {
    assert.equal(requestModel.baseUrl, baseUrl, "Refuse to send broker credentials to another endpoint");
  },
});
assert.equal(response.stopReason, "stop", "Probe did not finish normally");
console.log("Broker request completed.");
```

`run.py`:

```python
import json
import os
from pathlib import Path
import subprocess
import sys

broker = {"baseUrl": os.environ["CODEX_SIDECAR_URL"], "apiKey": os.environ["CODEX_SIDECAR_KEY"]}
probe = Path(__file__).resolve().with_name("probe.ts")
result = subprocess.run(
    ["dev/test-environment", "bun", str(probe), sys.argv[1]],
    input=json.dumps(broker), text=True, check=False,
)
sys.exit(result.returncode)
```

Run `python3 /path/to/run.py MODEL_ID` with broker variables available in the parent environment.
Set `PI_PACKAGE_DIR` if the installed SDK is not discoverable under the original HOME.
The endpoint assertion checks the effective request model before the provider sends HTTP headers.
This SSE probe checks broker connectivity, not WebSocket behavior or the web-search extension.
For offline activity persistence and replay coverage, run `dev/test-environment node --test tests/pi/native_web_search.mjs`.
