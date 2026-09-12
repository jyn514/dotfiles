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

On macOS, new launches expose a separate, session-authenticated Keychain relay
through `CODEX_SANDBOX_KEYCHAIN_ADDRESS` and `CODEX_SANDBOX_KEYCHAIN_TOKEN`.
It accepts only `flower-r2/read`, reading accounts `access-key` then `secret-key`
under service `dev.jyn.flower.r2` with `/usr/bin/security`.
Configure both items to confirm access; choosing Always Allow can defeat repeated prompts.
An approved read discloses reusable credentials to the untrusted sandbox.
The relay keeps no credential cache and returns the pair only if both reads succeed.

Flower's local CI client consumes the framed protocol in
[the relay design](r2-keychain-relay-design.typ); there is no credential-printing command.
Explicit R2 environment credentials bypass the relay, and unavailable relay
credentials skip optional upload without failing CI.
The Keychain listener, token, container, and networks belong to the launch and are
cleaned up independently of the editor/Podman gateway.

Run `python3 tools/codex-sandbox/tests/keychain_bridge_test.py` for socket and
dummy-child tests, and `python3 tools/codex-sandbox/tests/keychain_launcher_test.py`
for launcher tests.
The opt-in `python3 tools/codex-sandbox/tests/keychain_integration_relay.py` exercises
dummy credentials through disposable containers on the existing Docker VM.
The interactive consent probe is `python3 tools/codex-sandbox/tests/r2_keychain_consent_probe.py`;
its disposable Keychain password is `r2-probe-password`.

## Prerequisites and setup

Podman remains the default outer runtime.
[Opt-in Lima launches](lima/launch.md) use a separately provisioned VM, Keychain boot credentials, and runtime-aware image builders.
The [network fixture](lima/README.md) and [runtime contracts](lima/runtime.md) preserve the container boundaries;
`dev/test --lima` includes the disposable host, network, and runtime gate.
The separate [rootless Docker prototype](lima/docker.md) uses Docker's forwarded API socket and has its own opt-in setup and validation commands.
Its [default-readiness record](lima/docker.md#default-readiness) distinguishes
passed bounded tests from unresolved host file-table pressure and sustained-workload validation.

- Run from a Git checkout.
  The launcher uses the current Jujutsu workspace root and initializes a colocated Jujutsu workspace if needed.
- Install Python 3, Git, Jujutsu, tmux, and a `docker`-compatible Podman/Docker CLI.
  Image builds require network access on first use.
- Put this repository's `bin/` on `PATH`;
  `pi` delegates to `codex-sandbox`.
- Provide `~/.codex/config.toml`.
  The launcher injects the Podman secret `codex-github-token` as `GH_TOKEN`;
  exporting a host `GH_TOKEN` does not provision that secret.
  The opt-in [Lima credential helper](lima/credentials.md) imports it into Keychain and retains the Podman secret for rollback;
  guest caching lasts one VM boot.
- Run inside tmux to use the injected host editor and tmux session restart support.
- Optional: create dedicated model credentials with `codex-sandbox auth login`.
  The directory defaults to `~/.codex-sandbox-auth` and may be changed with `CODEX_SANDBOX_AUTH_DIR`.
- Optional: configure Agent Podman separately under `~/.agent-podman-access` or set `AGENT_PODMAN_ACCESS_DIR`.
- Optional: configure [read-only Zulip access](../zulip-proxy/README.md).

A repository may provide executable `.agents/sandbox/base-image` and a version 1 `.agents/sandbox/proxy-commands.json`.
Podman and nerdctl use these executable builders and their existing cache keys.
[Lima-Docker uses fresh Bake declarations and `image-target` selections](lima/docker.md)
through executable `.agents/sandbox/bake`; repository Docker CLI shims are no longer supported.
Repositories without extra command proxies may omit the manifest.
These files are trusted startup policy, not agent configuration.

The agent image key hashes source bytes directly, without Git clean filters or
line-ending normalization, so it tracks the bytes Docker builds.

Alpine images run Pi's bundled Node CLI to reduce module-loading overhead.
Other images use the standalone Bun executable.

Alpine builds validate Node's minimum version and seed its bytecode cache with the final runtime and user.
Each container gets its own writable copy at `/tmp/pi-node-cache`;
startup does not spawn a separate version-check process.

The image build installs the packages selected by `config/pi.json` with npm lifecycle scripts disabled, then loads their extensions without network access to seed Jiti's transpilation cache.
Only the cache enters the final image, at `/tmp/jiti`;
build-time package stores and extension runtime state are discarded.

Jiti checks source hashes before reuse.
Edited or newly installed extensions compile into the disposable container, so `/reload` still sees current source and cache writes never reach host Pi or another session.
Local extension and settings changes invalidate the image;
moving Git refs are captured when the package-install layer builds and may produce runtime cache misses after an upstream update.

The goal extension uses the precompiled npm release pinned in `config/pi.json`.
Its Git distribution loads TypeScript, making cache misses more expensive.

## Common commands

```sh
pi                              # start a new resumable sandbox session
pi --session SESSION_ID         # resume a Pi session
codex-sandbox auth login        # create/update dedicated sandbox OAuth state
codex-sandbox restart-all       # restart registered sessions; run inside tmux
CODEX_SANDBOX_TIMING=1 pi       # report preparation, launch, runtime, and cleanup timings
```

Set `CODEX_SANDBOX_HOST_EDITOR` to override the host editor;
otherwise `VISUAL`, `EDITOR`, then `vi` is used.
The dotfiles profile selects `config/nvim-host-editor.lua`, which applies hardening before loading plugin-free behavior from `config/nvim-shared.lua`;
normal Neovim loads the same shared behavior before its IDE configuration.

Each sandbox has one gateway for the host editor and, when configured, Agent Podman.
It starts in the background after its private link and egress networks are created.
Pi reaches its fixed editor and SSH ports by container DNS name;
early use may report a connection error.
Zulip also skips its readiness probe.
Retry once the service is available.
Authentication and repository-command proxies still require readiness checks.

Shared proxy identity checks run two at a time during attach and publication.
Every check finishes before metadata is published or failure recovery begins.
The launcher holds the session lock directly until cleanup. The first launcher
also holds coordination until publication succeeds; shared joiners validate
concurrently. Failed publication retains coordination through cleanup, and a
launch waiting for another publisher can be cancelled.

Gateway startup failures are reported to stderr and leave Pi running.
On exit, the launcher joins gateway startup before removing its container and networks.
An upstream refusal affects that connection; a listener process failure stops the whole gateway.
Editor-only gateways retain the editor's CPU, memory, and process limits.
Podman-enabled gateways have no such limits, preserving build throughput but sharing
Podman's resource and failure domain with the editor.

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
Container creation falls between `workload_argv end` and `monitor setup begin`;
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
- Zulip credentials are mounted only into its proxy.
  Agent Podman, when configured, is exposed through a separate SSH relay rather than the outer daemon.
- On native Linux, dropped capabilities and `no-new-privileges` disable effective sudo elevation.
  A Podman Machine preserves container sudo without weakening host isolation.
- Proxy and authentication failures fail closed;
  they do not fall back to privileged local execution or mounting credentials in the agent.

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

The authoritative [sandbox command proxy design](proxy-design.typ) defines the trust model, proxy manifest contract, and lifecycle.
Read it before changing a security boundary.
See the [tools overview](../README.md).
