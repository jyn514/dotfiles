# Codex sandbox operator guide

## Purpose

`codex-sandbox` launches Pi in a disposable agent container.
Launcher-owned sibling services provide narrowly scoped access to protected repository operations, Codex authentication, the host editor, optional Zulip, and optional Agent Podman.
The agent can write the working tree, but Git, Jujutsu, sandbox policy, and reusable credentials remain outside its direct authority.

Agent containers drop `NET_RAW` on every backend, including after container-local sudo.
Sidecars drop all capabilities.
This takes effect on new launches;
restart existing sessions to apply it.

The launcher mounts `~/src` read-only at `/src`, then overlays the active repository writable at the same relative path when it is beneath `~/src`—for example, `~/src/dotfiles` becomes `/src/dotfiles`.
Repositories outside `~/src` use `/src/repository`.
The selected path is also the agent and proxy working directory.

For external worktrees whose mountpoints are missing beneath `/src`, the launcher stages those directories in temporary sandbox state and binds the existing source subtrees read-only.
This also accommodates linked Git metadata without creating placeholder directories under `~/src`.
When this staging is needed, new entries in staged parent directories appear on the next launch;
the contents of bound subtrees remain live.

## Flower R2 Keychain access

The [launcher interface](spec/launcher-interface.typ) makes optional services explicit.
Version 2 configuration, capability gating, bounded project-command transport, captured image inputs, explicit refresh and clean rebuild, and accepted-policy/image joins are implemented.

On macOS, launches selecting `flower-r2` expose a separate, session-authenticated Keychain relay through `CODEX_SANDBOX_KEYCHAIN_ADDRESS` and `CODEX_SANDBOX_KEYCHAIN_TOKEN`.
It accepts only `flower-r2/read`, reading accounts `access-key` then `secret-key` under service `dev.jyn.flower.r2` with `/usr/bin/security`.
Configure both items to confirm access;
choosing Always Allow can defeat repeated prompts.
An approved read discloses reusable credentials to the untrusted sandbox.
The relay keeps no credential cache and returns the pair only if both reads succeed.

Flower's local CI client consumes the framed protocol in [the relay design](spec/r2-keychain-relay-design.typ);
there is no credential-printing command. It sends one credential frame after connecting, so one
invocation can produce at most one Keychain consent sequence. Bounded connection-establishment
retry is still pending in the read-only `/src/flower` checkout; until Flower implements it, an
early request can fail instead of waiting for the best-effort relay. Explicit R2 environment
credentials bypass the relay, and unavailable relay credentials skip optional upload without
failing CI.
The lifecycle supervisor owns the per-launch Keychain listener, token, container, networks, startup worker, and owner-validated cleanup; R2 remains separate from authenticated HTTP egress.
The two relay networks are created concurrently. Startup joins both creation workers, fixes the relay address and per-launch token, installs peer authorization, and only then projects the capability. Cleanup first closes creation and request admission, joins prompt work, and removes only resources carrying this launch's owner identity. Relay failure remains warning-only and Flower skips optional upload.

Run `python3 tools/codex-sandbox/tests/keychain_bridge_test.py` for socket and dummy-child tests, and `python3 tools/codex-sandbox/tests/keychain_launcher_test.py` for launcher tests.
The opt-in `python3 tools/codex-sandbox/tests/keychain_integration_relay.py` exercises dummy credentials through disposable containers on the existing Docker VM.
The interactive consent probe is `python3 tools/codex-sandbox/tests/r2_keychain_consent_probe.py`;
its disposable Keychain password is `r2-probe-password`.

## Prerequisites and setup

Lima-Docker is the default outer runtime (`lima-docker`).
Follow the [Docker setup guide](lima/docker.md) before launching;
missing setup is an error, not a fallback to another engine.
Set `CODEX_SANDBOX_RUNTIME=podman` for Podman.
[Opt-in Lima launches](lima/launch.md) use a separately provisioned VM, Keychain boot credentials, and runtime-aware image builders.
The [network fixture](lima/README.md) and [runtime contracts](lima/runtime.md) preserve the container boundaries;
`dev/test --lima` includes the disposable host, network, and runtime gate.
The [rootless Docker backend](lima/docker.md) uses Docker's forwarded API socket and has its own setup and validation commands.
Its [default-readiness record](lima/docker.md#default-readiness) distinguishes passed bounded tests from unresolved host file-table pressure and sustained-workload validation.

- Run from a Git checkout.
  The launcher uses the current Jujutsu workspace root and initializes a colocated Jujutsu workspace if needed.
- Install Python 3, Git, Jujutsu, tmux, and a `docker`-compatible Podman/Docker CLI.
  Image builds require network access on first use.
- Put this repository's `bin/` on `PATH`;
  `pi` delegates to `codex-sandbox`.
- Provide `~/.codex/config.toml`.
  The [Lima credential helper](lima/credentials.md) imports the Podman secret `codex-github-token` into Keychain for injection as `GH_TOKEN` and retains the Podman secret for rollback;
  exporting a host `GH_TOKEN` does not provision it.
  guest caching lasts one VM boot.
- Run inside tmux to use tmux session restart support.
  Repositories select host editing separately.
- Optional: create dedicated model credentials with `codex-sandbox auth login`.
  The directory defaults to `~/.codex-sandbox-auth` and may be changed with `CODEX_SANDBOX_AUTH_DIR`.
- Optional: configure Agent Podman separately under `~/.agent-podman-access` or set `AGENT_PODMAN_ACCESS_DIR`.
- Optional: configure [read-only Zulip access](../zulip-proxy/README.md).

A repository may use a version 2 `.agents/sandbox/proxy-commands.json` to select `host-editor`, `zulip`, `nested-containers`, `flower-r2`, and `agent-room` independently.
Host editing and Zulip default on;
`{"version": 2, "capabilities": {"host-editor": false, "zulip": false}}` disables both.
Zulip requires host credentials;
disabling it skips credential validation and proxy startup.
Nested containers, Flower R2, and agent-room default off. Selecting agent-room adds a fixed TCP relay
from the host's loopback-only `127.0.0.1:3000` to the same `127.0.0.1:3000` inside the agent container.
It accepts no agent-supplied destination and never relays the admin port 3001.
Host-editor and nested-container clients tolerate delayed best-effort listener startup for a
bounded readiness interval. Retries stop before the first request byte; after transmission starts,
transport failure is terminal and a possibly accepted operation is never replayed. Flower R2 does
not yet perform this pre-connection retry; see [Flower R2 Keychain access](#flower-r2-keychain-access).
Version 2 images declare one Bake file or project-command resolver and bind command and base image names.
Resolver commands receive the versioned JSON contract in [the launcher interface](spec/launcher-interface.typ) and run against the admitted engine.
The Bake resolver captures complete local contexts, assigns private content keys, and pins mutable upstream images by provider and platform.
Ordinary resolution reuses saved pins, then local image digests, and queries the registry only when neither is available.
It saves each ordinary resolution immediately so failed builds do not repeat registry lookups.
When `.agents/sandbox/docker-bake.hcl` exists, it becomes the default Bake resolver with base target `base`;
a repository using the default capabilities with no project command proxies can omit `proxy-commands.json`.
An explicit image resolver overrides this convention.
Version 1 and executable `.agents/sandbox/base-image` remain temporarily supported for external repositories.
This repository uses the version 2 bundled Bake resolver;
repository Docker CLI shims are no longer supported.
These files are trusted startup policy, not agent configuration.

The agent image key hashes source bytes directly, without Git clean filters or line-ending normalization, so it tracks the bytes Docker builds.
Without a project base image, the launcher pulls its default Node image into the selected engine if absent, before computing the agent image key.
Later launches reuse the local base;
a failed pull aborts startup.

Alpine images run Pi's bundled Node CLI to reduce module-loading overhead.
Other images use the standalone Bun executable.

Alpine builds validate Node's minimum version and seed its bytecode cache with the final runtime and user.
Each container gets its own writable copy at `/tmp/pi-node-cache`;
startup does not spawn a separate version-check process.

The image build installs the packages selected by `config/agents/pi/pi.json` with npm lifecycle scripts disabled, then loads their extensions without network access to seed Jiti's transpilation cache.
Only the cache enters the final image, at `/tmp/jiti`;
build-time package stores and extension runtime state are discarded.

Jiti checks source hashes before reuse.
Edited or newly installed extensions compile into the disposable container, so `/reload` still sees current source and cache writes never reach host Pi or another session.
Local extension and settings changes invalidate the image;
moving Git refs are captured when the package-install layer builds and may produce runtime cache misses after an upstream update.

The goal extension uses the precompiled npm release pinned in `config/agents/pi/pi.json`.
Its Git distribution loads TypeScript, making cache misses more expensive.

## Common commands

```sh
pi                              # start a new resumable sandbox session
pi --session SESSION_ID         # resume a Pi session
codex-sandbox auth login        # create/update dedicated sandbox OAuth state
codex-sandbox restart-all       # restart registered sessions; run inside tmux
tools/codex-sandbox/sandbox-image refresh --repo .  # update upstream pins and affected images
tools/codex-sandbox/sandbox-image clean --repo .    # rebuild declared images without build cache
CODEX_SANDBOX_TIMING=1 pi       # report preparation, launch, runtime, and cleanup timings
```

`refresh` queries mutable `FROM` and named image-context references, then rebuilds identities affected by changed pins;
it retains BuildKit caches.
Refreshed pins replace the previous pins only after the affected builds succeed.
`clean` retains the current pins but passes `--no-cache`.
Neither command changes images accepted by a live shared session or publishes registry images.

Project resolvers that derive Bake input at startup can delegate capture and building to the installed engine primitive:

```sh
sandbox-image bake --platform linux/arm64 --mode resolve base bug < fresh-bake.hcl
```

Run it from the project root with the launcher's admitted runtime environment.
Stdin accepts Bake HCL or JSON;
`--platform` must match the admitted Lima-Docker engine, and `--mode` is `resolve`, `refresh`, or `clean`.
Stdout contains the version 1 resolver result (`version` and `images`), with immutable references for the requested targets;
diagnostics go to stderr.
The command does not reload repository policy, so a version 2 command resolver can call it without recursion or writing a generated declaration into the checkout.

Set `CODEX_SANDBOX_HOST_EDITOR` to override the host editor;
otherwise `VISUAL`, `EDITOR`, then `vi` is used.
The dotfiles profile selects `config/nvim-host-editor.lua`, which applies hardening before loading plugin-free behavior from `config/nvim-shared.lua`;
normal Neovim loads the same shared behavior before its IDE configuration.

Each sandbox has one gateway for the host editor and, when configured, Agent Podman and agent-room.
It starts in the background after its private link and egress networks are created.
The in-container Python relay binds loopback and verifies its fixed gateway target before Pi starts.
Pi does not start if either step fails; its exit closes the listener and active connections.
Pi reaches its fixed editor and SSH ports by container DNS name. Their clients retry only
connection establishment within a bounded interval and never replay a possibly accepted request.
The separately supervised Zulip and Codex Caddy/helper services and repository-command proxies must be ready
before publication.

Shared proxy identity checks run two at a time during attach and publication.
Every check finishes before metadata is published or failure recovery begins.
The launcher holds the session lock directly until cleanup.
The first launcher also holds coordination until publication succeeds;
shared joiners validate concurrently.
Failed publication retains coordination through cleanup, and a launch waiting for another publisher can be cancelled.

Gateway startup failures are reported to stderr and leave Pi running.
On exit, the launcher joins gateway startup before removing its container and networks.
An upstream refusal affects that connection;
a listener process failure stops the whole gateway.
Editor-only gateways retain the editor's CPU, memory, and process limits.
Podman-enabled gateways have no such limits, preserving build throughput but sharing Podman's resource and failure domain with the editor.

Timing separates launch setup from `docker run`, then uses daemon timestamps to report container creation-to-start and start-to-exit intervals.
It also enables Pi's `PI_TIMING=1` startup breakdown, which excludes initial module imports.
The runtime interval includes the whole session;
use `CODEX_SANDBOX_TIMING=1 pi --help` for a bounded probe, not a measurement of interactive readiness.

Timestamp inspection runs after exit, has a five-second timeout, and preserves the agent's exit status.

### Measure interactive startup

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

## Safety and recovery

### Operational and security boundaries

- Treat the agent, including container root, as untrusted.
  It can modify ordinary working-tree files, the host's shared `~/.agents/skills` directory, and call every mounted proxy, but must not receive the outer daemon or direct writable access to `.git`, `.jj`, or `.agents/sandbox`.
- Trust the checkout and manifest authors before startup.
  Image builders and proxy images are part of the trusted computing base;
  a read-only mount does not make hostile policy safe.
- Networking blocks private and special-use IPv4 ranges.
  A manifest must explicitly enable network access for a proxy.
- The Codex sidecar keeps reusable OAuth tokens outside the agent, but the agent can submit model requests, disclose their contents, consume quota, and incur charges.
- Codex and Zulip credentials are mounted only into their respective profile-helper containers; Caddy and the agent receive no credential mount.
  Agent Podman, when configured, is exposed through a separate SSH relay rather than the outer daemon.
- On native Linux, dropped capabilities and `no-new-privileges` disable effective sudo elevation.
  A Podman Machine preserves container sudo without weakening host isolation.
- Proxy and authentication failures fail closed and surface as request failures.
  They do not terminate an existing agent or fall back to privileged local execution or credentials mounted in the agent.
  New attachments reject an unhealthy session.

### Failure recovery

The launcher preserves the agent's exit status and attempts to remove its containers, relays, networks, temporary files, and—after the final attached session exits—shared proxies.
`SIGINT`, `SIGHUP`, and `SIGTERM` also trigger cleanup.

The first session serializes proxy creation and publication.
Joining sessions validate the published proxies concurrently while holding lifetime locks that prevent reset or replacement;
a join cannot rewrite shared metadata.

- If startup reports invalid repository metadata or sandbox policy, repair the named path;
  do not bypass the validation.
- If authentication is disabled, run `codex-sandbox auth login`, then start a new sandbox.
- If Agent Podman reports an SSH handshake `EOF`, inspect the relay log before restarting the sandbox.
  A relay that accepts the sandbox connection but reports `host.docker.internal:<port>: Connection refused` means the Agent Podman machine is stopped;
  run `tools/agent-podman/start.sh` on the host.
  See [Agent Podman recovery](../agent-podman/README.md#recovery).
- If cached proxy/auth state changed or belongs to another network, run `codex-sandbox restart-all` from tmux.
  It terminates registered launcher processes, resets shared session metadata after cleanup, then resumes their sessions.
  Inherited `remain-on-exit` settings need no pane-local override.
- If automatic cleanup warns about a named resource, inspect and remove only that generated resource with the container CLI, then retry.
  For surviving containers and volumes, the diagnostic includes each resource name and its removal error.
  A volume still referenced by a stopped agent container cannot be removed until that container is removed.
  Do not delete the host coordination lock files manually.
- A stopped shared proxy terminates attached agents.
  Restart the sandbox rather than running the protected operation locally.

## Tests

Run unit tests from the repository root:

```sh
python3 -m unittest tools/codex-sandbox/tests/codex_sandbox_test.py
python3 -m unittest tools/codex-sandbox/tests/sandbox_proxies_test.py
```

The runtime integration test builds real images and requires a working Docker-compatible daemon and network access:

```sh
python3 tools/codex-sandbox/tests/image_runtime_integration.py --expected-revision <full-pi-commit>
```

Use the `PI_REVISION` selected by `image/Dockerfile`.
The test builds the Dockerfile as written and checks its recorded revision against this explicit expectation, retaining Alpine Node and Debian Node-20/Bun coverage.

Check the image caches against a built final image;
test containers run without network access:

```sh
docker build --target pi-extension-cache -f tools/codex-sandbox/image/Dockerfile -t pi-cache-test .
python3 tools/codex-sandbox/tests/cache_integration.py --runtime <sandbox-image> --builder pi-cache-test
docker image rm pi-cache-test
```

This checks Alpine bytecode reuse, first-launch extension cache hits, edited source, isolation between containers, and build failure on missing packages or extension errors.

## Design and reference

The authoritative [sandbox design specification](spec/main.typ) aggregates the sandbox contracts, including the trust model, proxy manifest, image resolution, and lifecycle.
Read it before changing a security boundary.
See the [tools overview](../README.md).
