# Codex sandbox development

Use the [operator guide](README.md) for host setup, session commands, safety, and recovery.
Before running tests or probes, follow the repository
[testing and isolation rules](../../dev/README.md#testing-and-probes).
The startup benchmark below uses the host's real configuration.

## Nested Docker acceptance

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

The helper logging requirements in [the authenticated-egress specification](spec/proxy-design.typ) remain contradictory.
Its metadata table requires logging other headers and original method/URI context;
its observability section and acceptance checks forbid logging that metadata.
The existing helper logs bounded original method/path and result classes, without query values or arbitrary headers.
The caller-token fix preserves that behavior; passing admission checks does not establish compliance with either conflicting logging requirement.

The runtime integration test builds real images and requires a working Docker-compatible daemon and network access:

```sh
python3 tools/codex-sandbox/tests/image_runtime_integration.py --expected-revision <full-pi-commit>
```

Use the full host commit recorded in `~/.local/share/pi/node/.source-revision`.
The test passes that commit as the required `PI_REVISION` build argument and checks
its recorded revision, retaining Alpine Node and Debian Node-20/Bun coverage.
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
